// Private inherited pipes only. One worker owns the audited C API and model;
// the control thread remains responsive during non-interruptible ORT calls.
#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#include <psapi.h>
#include <tlhelp32.h>
#include <algorithm>
#include <chrono>
#include <cmath>
#include <condition_variable>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <memory>
#include <mutex>
#include <sstream>
#include <string>
#include <thread>
#include <vector>
#include "sherpa-onnx/c-api/c-api.h"

using Clock = std::chrono::steady_clock;
std::mutex output_mutex;
void emit(const std::string& json) {
  std::lock_guard<std::mutex> lock(output_mutex);
  std::cout << json << std::endl;
}
double elapsed(Clock::time_point start) {
  return std::chrono::duration<double>(Clock::now() - start).count();
}
std::string resources() {
  PROCESS_MEMORY_COUNTERS_EX m{}; m.cb = sizeof(m);
  GetProcessMemoryInfo(GetCurrentProcess(), reinterpret_cast<PROCESS_MEMORY_COUNTERS*>(&m), sizeof(m));
  DWORD handles=0, threads=0; GetProcessHandleCount(GetCurrentProcess(), &handles);
  HANDLE snap=CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD,0);
  if(snap!=INVALID_HANDLE_VALUE) {
    THREADENTRY32 e{}; e.dwSize=sizeof(e);
    if(Thread32First(snap,&e)) do { if(e.th32OwnerProcessID==GetCurrentProcessId()) ++threads; } while(Thread32Next(snap,&e));
    CloseHandle(snap);
  }
  return ",\"private_bytes\":"+std::to_string(m.PrivateUsage)+",\"working_set_bytes\":"+std::to_string(m.WorkingSetSize)+
    ",\"handles\":"+std::to_string(handles)+",\"threads\":"+std::to_string(threads);
}
bool key_valid(const std::string& key) {
  return !key.empty() && key.size()<=320 && key.find_first_not_of("0123456789abcdef")==std::string::npos;
}
std::string unhex(const std::string& hex) {
  if(hex.empty() || hex.size()>16000 || hex.size()%2 || hex.find_first_not_of("0123456789abcdef")!=std::string::npos)
    throw std::runtime_error("INVALID_TEXT");
  std::string out;
  for(size_t i=0;i<hex.size();i+=2) out.push_back(static_cast<char>(std::stoi(hex.substr(i,2),nullptr,16)));
  if(out.find('\0')!=std::string::npos || !MultiByteToWideChar(CP_UTF8,MB_ERR_INVALID_CHARS,out.data(),static_cast<int>(out.size()),nullptr,0))
    throw std::runtime_error("INVALID_TEXT");
  return out;
}
void wav(const std::filesystem::path& path,const SherpaOnnxGeneratedAudio& audio) {
  if(audio.n<=0 || audio.n>32*1024*1024 || audio.sample_rate!=44100 || !audio.samples || std::filesystem::exists(path))
    throw std::runtime_error("INVALID_AUDIO");
  double energy=0;
  for(int i=0;i<audio.n;++i) {
    if(!std::isfinite(audio.samples[i])) throw std::runtime_error("INVALID_AUDIO");
    energy+=double(audio.samples[i])*audio.samples[i];
  }
  if(energy/audio.n<1e-10) throw std::runtime_error("EMPTY_AUDIO");
  std::ofstream out(path,std::ios::binary);
  auto u16=[&](uint16_t n){char b[]{char(n),char(n>>8)};out.write(b,2);};
  auto u32=[&](uint32_t n){char b[]{char(n),char(n>>8),char(n>>16),char(n>>24)};out.write(b,4);};
  uint32_t bytes=static_cast<uint32_t>(audio.n)*2;
  out.write("RIFF",4);u32(36+bytes);out.write("WAVEfmt ",8);u32(16);u16(1);u16(1);
  u32(audio.sample_rate);u32(audio.sample_rate*2);u16(2);u16(16);out.write("data",4);u32(bytes);
  for(int i=0;i<audio.n;++i) {
    int n=std::clamp(int(std::round(std::clamp(double(audio.samples[i]),-1.,1.)*32768.)),-32768,32767);
    u16(static_cast<uint16_t>(static_cast<int16_t>(n)));
  }
  out.close();if(!out) throw std::runtime_error("ARTIFACT_FAILED");
}
int wmain(int argc,wchar_t** argv) {
  try {
    if(argc!=3) return 2;
    std::filesystem::path root(argv[1]), output(argv[2]);
    if(!root.is_absolute() || !output.is_absolute() || !std::filesystem::is_directory(output)) return 2;
    auto start=Clock::now();
    emit("{\"type\":\"loading\"}");
    auto model=(root/"model.onnx").u8string(), tokens=(root/"tokens.txt").u8string(), lexicon=(root/"lexicon.txt").u8string();
    auto rules=(root/"date.fst").u8string()+","+(root/"number.fst").u8string();
    SherpaOnnxOfflineTtsConfig c{};
    c.model.vits.model=model.c_str();c.model.vits.tokens=tokens.c_str();c.model.vits.lexicon=lexicon.c_str();
    c.model.vits.noise_scale=.667f;c.model.vits.noise_scale_w=.8f;c.model.vits.length_scale=1.f;
    c.model.num_threads=4;c.model.provider="cpu";c.rule_fsts=rules.c_str();c.max_num_sentences=2;c.silence_scale=.2f;
    using Tts=std::unique_ptr<const SherpaOnnxOfflineTts,decltype(&SherpaOnnxDestroyOfflineTts)>;
    Tts tts(SherpaOnnxCreateOfflineTts(&c),SherpaOnnxDestroyOfflineTts);
    if(!tts || SherpaOnnxOfflineTtsSampleRate(tts.get())!=44100) return 3;
    struct Work {std::string key,text;float speed=1;};
    std::mutex mutex;std::condition_variable cv;Work work;bool pending=false,busy=false,cancelled=false,closing=false;
    std::thread worker([&]{
      std::unique_lock<std::mutex> lock(mutex);
      while(true) {
        cv.wait(lock,[&]{return pending||closing;});if(closing&&!pending) break;
        Work request=work;pending=false;lock.unlock();auto begin=Clock::now();
        std::string error;double duration=0;auto path=output/(request.key+".wav");
        try {
          SherpaOnnxGenerationConfig g{};g.sid=0;g.speed=request.speed;g.silence_scale=.2f;
          using Audio=std::unique_ptr<const SherpaOnnxGeneratedAudio,decltype(&SherpaOnnxDestroyOfflineTtsGeneratedAudio)>;
          Audio audio(SherpaOnnxOfflineTtsGenerateWithConfig(tts.get(),request.text.c_str(),&g,nullptr,nullptr),SherpaOnnxDestroyOfflineTtsGeneratedAudio);
          if(!audio||!audio->samples||audio->n<=0) throw std::runtime_error("SYNTHESIS_FAILED");
          duration=double(audio->n)/audio->sample_rate;
          lock.lock();
          if(!cancelled&&!closing) wav(path,*audio);
          lock.unlock();
        } catch(...) {error="SYNTHESIS_FAILED";if(lock.owns_lock())lock.unlock();}
        lock.lock();
        if(cancelled||closing) {std::error_code ec;std::filesystem::remove(path,ec);error="CANCELLED";}
        busy=false;
        emit("{\"type\":\"result\",\"key\":\""+request.key+"\",\"error\":\""+error+
          "\",\"synthesis_ms\":"+std::to_string(elapsed(begin)*1000)+",\"audio_seconds\":"+std::to_string(duration)+
          ",\"text_chars\":"+std::to_string(std::count_if(request.text.begin(),request.text.end(),[](unsigned char b){return (b&0xc0)!=0x80;}))+resources()+"}");
        if(closing) break;
      }
    });
    emit("{\"type\":\"ready\",\"model\":\"melo-zh-en-v2\",\"version\":\"aurora-local-voice-1\",\"runtime\":\""+
      std::string(SherpaOnnxGetVersionStr())+"\",\"ort\":\""+SherpaOnnxGetOnnxruntimeVersionStr()+
      "\",\"num_threads\":4,\"ready_ms\":"+std::to_string(elapsed(start)*1000)+resources()+"}");
    std::string line;
    while(std::getline(std::cin,line)) {
      if(line.size()>17000) break;
      std::istringstream in(line);std::string verb,key,text,speed;
      std::getline(in,verb,'\t');std::getline(in,key,'\t');
      std::lock_guard<std::mutex> lock(mutex);
      if(verb=="shutdown") break;
      if(verb=="health") {emit(std::string("{\"type\":\"health\",\"ready\":true,\"busy\":")+(busy?"true":"false")+resources()+"}");continue;}
      if(!key_valid(key)) continue;
      if(verb=="cancel") {if(busy&&work.key==key)cancelled=true;continue;}
      if(verb=="synthesize") {
        if(busy) {emit("{\"type\":\"result\",\"key\":\""+key+"\",\"error\":\"BUSY\"}");continue;}
        try {
          std::getline(in,text,'\t');std::getline(in,speed,'\t');float rate=std::stof(speed);
          if(!std::isfinite(rate)||rate<.5f||rate>2.f) throw std::runtime_error("INVALID_RATE");
          work={key,unhex(text),rate};busy=true;pending=true;cancelled=false;cv.notify_one();
        } catch(...) {emit("{\"type\":\"result\",\"key\":\""+key+"\",\"error\":\"INVALID_REQUEST\"}");}
      }
    }
    {std::lock_guard<std::mutex> lock(mutex);closing=true;cancelled=true;cv.notify_one();}
    worker.join();tts.reset();emit("{\"type\":\"closed\"}");return 0;
  } catch(...) {emit("{\"type\":\"failed\",\"error\":\"HOST_FAILED\"}");return 1;}
}
