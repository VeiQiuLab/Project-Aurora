// Oracle-only instrumentation in THIS isolated process. No file/DLL patching,
// no remote process injection. Never linked into the performance/clean host.
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <mutex>
#include <stdexcept>
#include <vector>
#include "onnxruntime_c_api.h"
namespace {
const OrtApi* api;
decltype(OrtApi::Run) original;
std::ofstream output;
std::mutex mutex;
void check(OrtStatus* status) {
  if (!status) return;
  std::string error(api->GetErrorMessage(status));
  api->ReleaseStatus(status);
  throw std::runtime_error(error);
}
OrtStatus* ORT_API_CALL traced(OrtSession* session, const OrtRunOptions* options,
    const char* const* names, const OrtValue* const* inputs, size_t count,
    const char* const* output_names, size_t output_count, OrtValue** outputs) noexcept {
  try {
    std::lock_guard<std::mutex> guard(mutex);
    output << "{\"inputs\":[";
    for (size_t i = 0; i < count; ++i) {
      OrtTensorTypeAndShapeInfo* info = nullptr;
      check(api->GetTensorTypeAndShape(inputs[i], &info));
      struct Owner { OrtTensorTypeAndShapeInfo* p; ~Owner() { api->ReleaseTensorTypeAndShapeInfo(p); } } owner{info};
      size_t rank = 0, n = 0;
      ONNXTensorElementDataType type;
      check(api->GetDimensionsCount(info, &rank));
      std::vector<int64_t> dims(rank);
      check(api->GetDimensions(info, dims.data(), rank));
      check(api->GetTensorShapeElementCount(info, &n));
      check(api->GetTensorElementType(info, &type));
      if (n > 100000) throw std::runtime_error("Unexpected oracle tensor size");
      void* data = nullptr;
      check(api->GetTensorMutableData(const_cast<OrtValue*>(inputs[i]), &data));
      if (i) output << ',';
      // Input names are controlled by the pinned ONNX model, not user text.
      output << "{\"name\":\"" << names[i] << "\",\"dtype\":" << type << ",\"shape\":[";
      for (size_t k = 0; k < rank; ++k) { if (k) output << ','; output << dims[k]; }
      output << "],\"values\":[" << std::setprecision(9);
      for (size_t k = 0; k < n; ++k) {
        if (k) output << ',';
        if (type == ONNX_TENSOR_ELEMENT_DATA_TYPE_INT64) output << static_cast<int64_t*>(data)[k];
        else if (type == ONNX_TENSOR_ELEMENT_DATA_TYPE_FLOAT) output << static_cast<float*>(data)[k];
        else throw std::runtime_error("Unexpected oracle dtype");
      }
      output << "]}";
    }
    output << "]}\n";
    output.flush();
    if (!output) throw std::runtime_error("Trace write failure");
  } catch (const std::exception& e) {
    std::cerr << "ORACLE_CAPTURE_FAILED: " << e.what() << '\n';
  }
  return original(session, options, names, inputs, count, output_names, output_count, outputs);
}
struct Trace {
  bool installed = false;
  Trace() {
    const wchar_t* path = _wgetenv(L"AURORA_ORACLE_TRACE");
    if (!path) return;
    if (std::filesystem::exists(path)) throw std::runtime_error("Trace output must be fresh");
    output.open(std::filesystem::path(path));
    if (!output) throw std::runtime_error("Trace open failed");
    api = OrtGetApiBase()->GetApi(ORT_API_VERSION);
    if (!api) throw std::runtime_error("Oracle ORT API mismatch");
    auto* slot = &const_cast<OrtApi*>(api)->Run;
    original = *slot;
    DWORD old = 0;
    if (!VirtualProtect(slot, sizeof(*slot), PAGE_READWRITE, &old))
      throw std::runtime_error("Oracle API table cannot be instrumented");
    *slot = traced;
    DWORD ignored;
    VirtualProtect(slot, sizeof(*slot), old, &ignored);
    installed = true;
  }
  ~Trace() {
    if (!installed) return;
    auto* slot = &const_cast<OrtApi*>(api)->Run;
    DWORD old, ignored;
    if (VirtualProtect(slot, sizeof(*slot), PAGE_READWRITE, &old)) {
      *slot = original;
      VirtualProtect(slot, sizeof(*slot), old, &ignored);
    }
  }
} trace;
}
