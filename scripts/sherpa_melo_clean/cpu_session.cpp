// Experimental CPU-only adapter; matches upstream CPU thread settings.
#include <stdexcept>
#include "sherpa-onnx/csrc/session.h"
namespace sherpa_onnx {
Ort::SessionOptions GetSessionOptionsImpl(int32_t threads,
    const std::string& provider, const ProviderConfig*) {
  if (provider != "cpu" || threads < 1 || threads > 16)
    throw std::invalid_argument("CPU provider and 1..16 threads required");
  Ort::SessionOptions options;
  options.SetIntraOpNumThreads(threads);
  options.SetInterOpNumThreads(threads);
  return options;
}
}
