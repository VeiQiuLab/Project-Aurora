// Aurora's minimal adapter, not imported DesktopPet application code.
// Cubism Core/Framework are external, separately licensed build inputs.
#include <windows.h>
#include <d3d11.h>
#include <dxgi1_2.h>
#include <dcomp.h>
#include <wincodec.h>
#include <wrl/client.h>
#include <filesystem>
#include <fstream>
#include <memory>
#include <vector>
#include <algorithm>
#include <cmath>
#include <stdexcept>
#include <CubismFramework.hpp>
#include <ICubismAllocator.hpp>
#include <CubismModelSettingJson.hpp>
#include <Model/CubismUserModel.hpp>
#include <Motion/CubismMotion.hpp>
#include <Physics/CubismPhysics.hpp>
#include <Id/CubismIdManager.hpp>
#include <Rendering/D3D11/CubismRenderer_D3D11.hpp>
#include <Rendering/D3D11/CubismDeviceInfo_D3D11.hpp>
using namespace Live2D::Cubism::Framework;
using namespace Live2D::Cubism::Framework::Rendering;
using Microsoft::WRL::ComPtr;
namespace fs = std::filesystem;
namespace {
void check(HRESULT hr) { if (FAILED(hr)) throw std::runtime_error("native operation failed"); }
struct Allocator final : ICubismAllocator {
    void* Allocate(csmSizeType n) override { return malloc(n); }
    void Deallocate(void* p) override { free(p); }
    void* AllocateAligned(csmSizeType n, csmUint32 a) override { return _aligned_malloc(n,a); }
    void DeallocateAligned(void* p) override { _aligned_free(p); }
} allocator;
fs::path shaderRoot;
CubismFramework::Option options{}; // Framework retains this pointer through shutdown.
std::vector<csmByte> read(const fs::path& path, size_t cap=64*1024*1024) {
    std::ifstream stream(path,std::ios::binary|std::ios::ate);
    if (!stream) throw std::runtime_error("file unavailable");
    auto size=stream.tellg();
    if (size<=0 || static_cast<uint64_t>(size)>cap) throw std::runtime_error("file size");
    std::vector<csmByte> data(static_cast<size_t>(size)); stream.seekg(0);
    if (!stream.read(reinterpret_cast<char*>(data.data()),size)) throw std::runtime_error("file read");
    return data;
}
csmByte* shaderFile(const std::string path,csmSizeInt* size) {
    *size=0;
    try {
        auto name=fs::u8path(path).filename();
        if(name!=L"CubismEffect.fx" && name!=L"CubismBlendMode.fx") return nullptr;
        auto data=read(shaderRoot/name,2*1024*1024);
        auto result=new csmByte[data.size()]; memcpy(result,data.data(),data.size());
        *size=static_cast<csmSizeInt>(data.size()); return result;
    } catch (...) { return nullptr; }
}
void releaseBytes(csmByte* p) { delete[] p; }
fs::path asset(const fs::path& root,const char* relative) {
    if(!relative || !*relative) throw std::runtime_error("missing asset");
    auto part=fs::u8path(relative);
    if(part.is_absolute()||part.has_root_name()) throw std::runtime_error("absolute asset");
    for(const auto& p:part) if(p==L"..") throw std::runtime_error("traversal");
    auto real=fs::canonical(root/part), base=fs::canonical(root);
    auto mismatch=std::mismatch(base.begin(),base.end(),real.begin(),real.end());
    if(mismatch.first!=base.end()) throw std::runtime_error("asset escape");
    return real;
}
class Model final : public CubismUserModel {
    std::unique_ptr<CubismModelSettingJson> settings;
    std::vector<ComPtr<ID3D11ShaderResourceView>> textures;
    ACubismMotion* idle=nullptr;
    float elapsed=0;
public:
    ~Model() { _motionManager->StopAllMotions(); if(idle) ACubismMotion::Delete(idle); DeleteRenderer(); }
    void load(const fs::path& path, ID3D11Device* device) {
        auto json=read(path,1024*1024); auto root=path.parent_path();
        settings=std::make_unique<CubismModelSettingJson>(json.data(),static_cast<csmSizeInt>(json.size()));
        auto moc=read(asset(root,settings->GetModelFileName()));
        LoadModel(moc.data(),static_cast<csmSizeInt>(moc.size()),true);
        if(!GetModel()) throw std::runtime_error("moc invalid");
        auto physics=settings->GetPhysicsFileName();
        if(physics&&*physics) { auto bytes=read(asset(root,physics)); LoadPhysics(bytes.data(),static_cast<csmSizeInt>(bytes.size())); }
        if(settings->GetMotionCount("Idle")>0) {
            auto bytes=read(asset(root,settings->GetMotionFileName("Idle",0)));
            idle=LoadMotion(bytes.data(),static_cast<csmSizeInt>(bytes.size()),"Idle");
            if(!idle) throw std::runtime_error("motion invalid");
        }
        CubismRenderer_D3D11::SetConstantSettings(2,device); CreateRenderer(480,640);
        auto renderer=GetRenderer<CubismRenderer_D3D11>();
        if(!renderer) throw std::runtime_error("renderer invalid");
        renderer->IsPremultipliedAlpha(false);
        int count=settings->GetTextureCount();
        if(count<1||count>16) throw std::runtime_error("texture count");
        ComPtr<IWICImagingFactory> wic;
        check(CoCreateInstance(CLSID_WICImagingFactory,nullptr,CLSCTX_INPROC_SERVER,IID_PPV_ARGS(&wic)));
        for(int i=0;i<count;i++) {
            auto file=asset(root,settings->GetTextureFileName(i));
            if(fs::file_size(file)>64*1024*1024) throw std::runtime_error("texture size");
            ComPtr<IWICBitmapDecoder> decoder; ComPtr<IWICBitmapFrameDecode> frame;
            ComPtr<IWICFormatConverter> pixels;
            check(wic->CreateDecoderFromFilename(file.c_str(),nullptr,GENERIC_READ,WICDecodeMetadataCacheOnLoad,&decoder));
            check(decoder->GetFrame(0,&frame)); check(wic->CreateFormatConverter(&pixels));
            check(pixels->Initialize(frame.Get(),GUID_WICPixelFormat32bppRGBA,WICBitmapDitherTypeNone,nullptr,0,WICBitmapPaletteTypeCustom));
            UINT w,h; check(pixels->GetSize(&w,&h));
            if(!w||!h||w>8192||h>8192||uint64_t(w)*h>16*1024*1024) throw std::runtime_error("texture dimensions");
            std::vector<BYTE> rgba(size_t(w)*h*4); check(pixels->CopyPixels(nullptr,w*4,static_cast<UINT>(rgba.size()),rgba.data()));
            D3D11_TEXTURE2D_DESC desc{};desc.Width=w;desc.Height=h;desc.MipLevels=1;desc.ArraySize=1;
            desc.Format=DXGI_FORMAT_R8G8B8A8_UNORM;desc.SampleDesc.Count=1;desc.Usage=D3D11_USAGE_IMMUTABLE;desc.BindFlags=D3D11_BIND_SHADER_RESOURCE;
            D3D11_SUBRESOURCE_DATA init{rgba.data(),w*4,0}; ComPtr<ID3D11Texture2D> texture;
            check(device->CreateTexture2D(&desc,&init,&texture)); ComPtr<ID3D11ShaderResourceView> view;
            check(device->CreateShaderResourceView(texture.Get(),nullptr,&view)); renderer->BindTexture(i,view.Get()); textures.push_back(view);
        }
        GetModelMatrix()->SetHeight(1.8f); GetModelMatrix()->SetPosition(0,0);
        GetModel()->SaveParameters();
    }
    void draw(ID3D11DeviceContext* context,float delta,int state,UINT width,UINT height) {
        elapsed+=delta; GetModel()->LoadParameters();
        if(idle&&_motionManager->IsFinished()) _motionManager->StartMotionPriority(idle,false,1);
        _motionManager->UpdateMotion(GetModel(),delta); GetModel()->SaveParameters();
        auto ids=CubismFramework::GetIdManager();
        // Small high-level pose only. No amplitude mouth animation or lip-sync claim.
        float tilt=state==1?5.0f:state==2?2.0f*std::sin(elapsed*3):0.0f;
        GetModel()->AddParameterValue(ids->GetId("ParamAngleZ"),tilt);
        if(_physics) _physics->Evaluate(GetModel(),delta);
        GetModel()->Update();
        CubismMatrix44 projection; projection.Scale(float(height)/width,1); projection.MultiplyByMatrix(GetModelMatrix());
        auto renderer=GetRenderer<CubismRenderer_D3D11>(); renderer->SetRenderTargetSize(width,height);
        renderer->StartFrame(context); renderer->SetMvpMatrix(&projection); renderer->DrawModel(); renderer->EndFrame();
    }
};
LRESULT CALLBACK windowProc(HWND window,UINT msg,WPARAM w,LPARAM l) {
    if(msg==WM_CLOSE){DestroyWindow(window);return 0;}
    if(msg==WM_MOUSEACTIVATE)return MA_NOACTIVATE;
    if(msg==WM_NCHITTEST)return HTTRANSPARENT;
    if(msg==WM_DPICHANGED){auto r=reinterpret_cast<RECT*>(l);SetWindowPos(window,nullptr,r->left,r->top,r->right-r->left,r->bottom-r->top,SWP_NOACTIVATE|SWP_NOZORDER);return 0;}
    return DefWindowProcW(window,msg,w,l);
}
struct Surface {
    DWORD owner=GetCurrentThreadId(); HWND window=nullptr; bool com=false,framework=false,visible=false;
    ComPtr<ID3D11Device> device; ComPtr<ID3D11DeviceContext> context;
    ComPtr<IDXGISwapChain1> swap; ComPtr<ID3D11RenderTargetView> target;
    ComPtr<IDCompositionDevice> composition; ComPtr<IDCompositionTarget> destination; ComPtr<IDCompositionVisual> visual;
    std::unique_ptr<Model> model; UINT width=480,height=640;
    fs::path capturePath;
    ~Surface(){model.reset(); CubismDeviceInfo_D3D11::ReleaseAllDeviceInfo();
        if(framework){CubismFramework::Dispose();CubismFramework::CleanUp();}
        if(context){context->ClearState();context->Flush();}
        visual.Reset();destination.Reset();composition.Reset();target.Reset();swap.Reset();context.Reset();device.Reset();
        if(window&&IsWindow(window))DestroyWindow(window);if(com)CoUninitialize();}
    void init(const fs::path& modelFile,const fs::path& shaders) {
        check(CoInitializeEx(nullptr,COINIT_APARTMENTTHREADED));com=true;
        SetProcessDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2);
        WNDCLASSW wc{};wc.hInstance=GetModuleHandleW(nullptr);wc.lpszClassName=L"AuroraLive2DNative";wc.lpfnWndProc=windowProc;
        if(!RegisterClassW(&wc)&&GetLastError()!=ERROR_CLASS_ALREADY_EXISTS)throw std::runtime_error("window class");
        RECT work{};SystemParametersInfoW(SPI_GETWORKAREA,0,&work,0);
        window=CreateWindowExW(WS_EX_NOREDIRECTIONBITMAP|WS_EX_TOOLWINDOW|WS_EX_NOACTIVATE|WS_EX_TRANSPARENT,
            wc.lpszClassName,L"Aurora Character",WS_POPUP,work.right-480,work.bottom-640,480,640,nullptr,nullptr,wc.hInstance,nullptr);
        if(!window)throw std::runtime_error("window create");
        D3D_FEATURE_LEVEL level;
        check(D3D11CreateDevice(nullptr,D3D_DRIVER_TYPE_HARDWARE,nullptr,D3D11_CREATE_DEVICE_BGRA_SUPPORT,nullptr,0,D3D11_SDK_VERSION,&device,&level,&context));
        ComPtr<IDXGIDevice> dxgi;check(device.As(&dxgi));ComPtr<IDXGIAdapter> adapter;check(dxgi->GetAdapter(&adapter));
        ComPtr<IDXGIFactory2> factory;check(adapter->GetParent(IID_PPV_ARGS(&factory)));
        DXGI_SWAP_CHAIN_DESC1 desc{};desc.Width=width;desc.Height=height;desc.Format=DXGI_FORMAT_B8G8R8A8_UNORM;
        desc.SampleDesc.Count=1;desc.BufferUsage=DXGI_USAGE_RENDER_TARGET_OUTPUT;desc.BufferCount=2;
        desc.SwapEffect=DXGI_SWAP_EFFECT_FLIP_SEQUENTIAL;desc.AlphaMode=DXGI_ALPHA_MODE_PREMULTIPLIED;
        check(factory->CreateSwapChainForComposition(device.Get(),&desc,nullptr,&swap));
        check(DCompositionCreateDevice(dxgi.Get(),IID_PPV_ARGS(&composition)));
        check(composition->CreateTargetForHwnd(window,TRUE,&destination));check(composition->CreateVisual(&visual));
        check(visual->SetContent(swap.Get()));check(destination->SetRoot(visual.Get()));check(composition->Commit());
        shaderRoot=fs::canonical(shaders); read(shaderRoot/L"CubismEffect.fx",2*1024*1024);read(shaderRoot/L"CubismBlendMode.fx",2*1024*1024);
        options.LoggingLevel=CubismFramework::Option::LogLevel_Off;
        options.LoadFileFunction=shaderFile;options.ReleaseBytesFunction=releaseBytes;
        if(!CubismFramework::StartUp(&allocator,&options))throw std::runtime_error("cubism startup");
        CubismFramework::Initialize();framework=true;model=std::make_unique<Model>();model->load(fs::canonical(modelFile),device.Get());
    }
    int tick(float delta,int state,bool show,int x,int y) {
        if(owner!=GetCurrentThreadId())throw std::runtime_error("thread affinity");
        MSG msg;while(PeekMessageW(&msg,nullptr,0,0,PM_REMOVE)){TranslateMessage(&msg);DispatchMessageW(&msg);}
        if(!IsWindow(window))return 1;
        if(visible!=show){ShowWindow(window,show?SW_SHOWNOACTIVATE:SW_HIDE);visible=show;}
        if(x!=INT_MIN&&y!=INT_MIN){POINT p{x,y};MONITORINFO info{sizeof(info)};GetMonitorInfoW(MonitorFromPoint(p,MONITOR_DEFAULTTONEAREST),&info);
            RECT old;GetWindowRect(window,&old);int nx=std::clamp<LONG>(x,info.rcWork.left, std::max(info.rcWork.left,info.rcWork.right-int(width)));
            int ny=std::clamp<LONG>(y,info.rcWork.top,std::max(info.rcWork.top,info.rcWork.bottom-int(height)));
            if(old.left!=nx||old.top!=ny)SetWindowPos(window,nullptr,nx,ny,0,0,SWP_NOSIZE|SWP_NOACTIVATE|SWP_NOZORDER);}
        if(!show)return 0;
        RECT bounds;GetClientRect(window,&bounds);UINT w=std::max(1L,bounds.right),h=std::max(1L,bounds.bottom);
        if(w!=width||h!=height){context->OMSetRenderTargets(0,nullptr,nullptr);target.Reset();check(swap->ResizeBuffers(2,w,h,DXGI_FORMAT_UNKNOWN,0));width=w;height=h;}
        if(!target){ComPtr<ID3D11Texture2D> buffer;check(swap->GetBuffer(0,IID_PPV_ARGS(&buffer)));check(device->CreateRenderTargetView(buffer.Get(),nullptr,&target));}
        ID3D11RenderTargetView* rt=target.Get();context->OMSetRenderTargets(1,&rt,nullptr);
        float clear[4]{};context->ClearRenderTargetView(rt,clear);D3D11_VIEWPORT viewport{0,0,float(width),float(height),0,1};context->RSSetViewports(1,&viewport);
        model->draw(context.Get(),std::clamp(delta,0.0f,0.1f),state,width,height);
        if(!capturePath.empty()) {capture();capturePath.clear();}
        check(swap->Present(1,0));return 0;
    }
    void capture() {
        // Opt-in test evidence from the actual submitted GPU surface, not a mock
        // render or OS screenshot. Never used in ordinary production frames.
        ComPtr<ID3D11Texture2D> buffer,staging;check(swap->GetBuffer(0,IID_PPV_ARGS(&buffer)));
        D3D11_TEXTURE2D_DESC desc;buffer->GetDesc(&desc);desc.Usage=D3D11_USAGE_STAGING;desc.BindFlags=0;desc.CPUAccessFlags=D3D11_CPU_ACCESS_READ;desc.MiscFlags=0;
        check(device->CreateTexture2D(&desc,nullptr,&staging));context->CopyResource(staging.Get(),buffer.Get());
        D3D11_MAPPED_SUBRESOURCE mapped{};check(context->Map(staging.Get(),0,D3D11_MAP_READ,0,&mapped));
        std::vector<BYTE> data(size_t(width)*height*4);
        for(UINT y=0;y<height;y++)memcpy(data.data()+size_t(y)*width*4,static_cast<BYTE*>(mapped.pData)+size_t(y)*mapped.RowPitch,size_t(width)*4);
        context->Unmap(staging.Get(),0);
        ComPtr<IWICImagingFactory> wic;check(CoCreateInstance(CLSID_WICImagingFactory,nullptr,CLSCTX_INPROC_SERVER,IID_PPV_ARGS(&wic)));
        ComPtr<IWICStream> stream;check(wic->CreateStream(&stream));check(stream->InitializeFromFilename(capturePath.c_str(),GENERIC_WRITE));
        ComPtr<IWICBitmapEncoder> encoder;check(wic->CreateEncoder(GUID_ContainerFormatPng,nullptr,&encoder));check(encoder->Initialize(stream.Get(),WICBitmapEncoderNoCache));
        ComPtr<IWICBitmapFrameEncode> frame;ComPtr<IPropertyBag2> bag;check(encoder->CreateNewFrame(&frame,&bag));check(frame->Initialize(bag.Get()));check(frame->SetSize(width,height));
        WICPixelFormatGUID format=GUID_WICPixelFormat32bppBGRA;check(frame->SetPixelFormat(&format));
        if(format!=GUID_WICPixelFormat32bppBGRA)throw std::runtime_error("capture format");
        check(frame->WritePixels(height,width*4,static_cast<UINT>(data.size()),data.data()));check(frame->Commit());check(encoder->Commit());
    }
};
}
extern "C" __declspec(dllexport) void* aurora_create(const wchar_t* model,const wchar_t* shaders) noexcept {
    try{auto surface=std::make_unique<Surface>();surface->init(model,shaders);return surface.release();}catch(...){return nullptr;}
}
extern "C" __declspec(dllexport) int aurora_frame(void* handle,float delta,int state,int visible,int x,int y) noexcept {
    try{return static_cast<Surface*>(handle)->tick(delta,state,visible!=0,x,y);}catch(...){return -1;}
}
extern "C" __declspec(dllexport) void aurora_destroy(void* handle) noexcept {try{delete static_cast<Surface*>(handle);}catch(...){}}
extern "C" __declspec(dllexport) void aurora_capture_next(void* handle,const wchar_t* path) noexcept {try{static_cast<Surface*>(handle)->capturePath=path;}catch(...){}}
