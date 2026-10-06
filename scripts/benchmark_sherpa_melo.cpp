// V4-7B.2 benchmark only. Build against the official pinned sherpa C API.
// No production provider, supervisor, network service, or audio playback here.
#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#include <psapi.h>
#include <tlhelp32.h>
#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <memory>
#include <stdexcept>
#include <string>
#include <vector>
#include "sherpa-onnx/c-api/c-api.h"

using Clock = std::chrono::steady_clock;
double seconds(Clock::time_point start) {
  return std::chrono::duration<double>(Clock::now() - start).count();
}
std::string utf8(const wchar_t* value) {
  int n = WideCharToMultiByte(CP_UTF8, 0, value, -1, nullptr, 0, nullptr, nullptr);
  if (n <= 0) throw std::runtime_error("Invalid argument encoding");
  std::vector<char> data(n);
  WideCharToMultiByte(CP_UTF8, 0, value, -1, data.data(), n, nullptr, nullptr);
  return std::string(data.data());
}
uint64_t ticks(FILETIME t) {
  return (static_cast<uint64_t>(t.dwHighDateTime) << 32) | t.dwLowDateTime;
}
double cpu_seconds() {
  FILETIME created{}, exited{}, kernel{}, user{};
  if (!GetProcessTimes(GetCurrentProcess(), &created, &exited, &kernel, &user))
    throw std::runtime_error("GetProcessTimes failed");
  return (ticks(kernel) + ticks(user)) / 1e7;
}
void resources() {
  PROCESS_MEMORY_COUNTERS_EX memory{};
  memory.cb = sizeof(memory);
  if (!GetProcessMemoryInfo(GetCurrentProcess(),
                           reinterpret_cast<PROCESS_MEMORY_COUNTERS*>(&memory),
                           sizeof(memory))) throw std::runtime_error("Memory counter failed");
  DWORD handles = 0;
  GetProcessHandleCount(GetCurrentProcess(), &handles);
  DWORD threads = 0;
  HANDLE snapshot = CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD, 0);
  if (snapshot == INVALID_HANDLE_VALUE) throw std::runtime_error("Thread counter failed");
  THREADENTRY32 entry{};
  entry.dwSize = sizeof(entry);
  if (Thread32First(snapshot, &entry)) do {
    if (entry.th32OwnerProcessID == GetCurrentProcessId()) ++threads;
  } while (Thread32Next(snapshot, &entry));
  CloseHandle(snapshot);
  std::cout << ",\"working_set_bytes\":" << memory.WorkingSetSize
            << ",\"peak_working_set_bytes\":" << memory.PeakWorkingSetSize
            << ",\"private_bytes\":" << memory.PrivateUsage
            << ",\"handles\":" << handles << ",\"threads\":" << threads;
}
std::string decode_hex(const std::string& hex) {
  if (hex.empty() || hex.size() > 16000 || hex.size() % 2)
    throw std::runtime_error("Invalid benchmark text length");
  auto digit = [](char c) -> unsigned {
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
    throw std::runtime_error("Invalid hex input");
  };
  std::string text;
  for (size_t i = 0; i < hex.size(); i += 2)
    text.push_back(static_cast<char>((digit(hex[i]) << 4) | digit(hex[i+1])));
  if (text.find('\0') != std::string::npos ||
      !MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, text.data(),
                          static_cast<int>(text.size()), nullptr, 0))
    throw std::runtime_error("Invalid UTF-8 text");
  return text;
}
void write_pcm(const std::filesystem::path& path, const SherpaOnnxGeneratedAudio& audio) {
  // Explicit PCM16 for existing Rust Audio; no float WAV or wraparound.
  if (std::filesystem::exists(path)) throw std::runtime_error("Refuse WAV overwrite");
  std::ofstream out(path, std::ios::binary);
  if (!out) throw std::runtime_error("WAV open failed");
  auto u16 = [&out](uint16_t x) { char b[]{char(x), char(x >> 8)}; out.write(b, 2); };
  auto u32 = [&out](uint32_t x) { char b[]{char(x), char(x >> 8), char(x >> 16), char(x >> 24)}; out.write(b, 4); };
  uint32_t bytes = static_cast<uint32_t>(audio.n) * 2;
  out.write("RIFF", 4); u32(36 + bytes); out.write("WAVEfmt ", 8);
  u32(16); u16(1); u16(1); u32(audio.sample_rate); u32(audio.sample_rate * 2);
  u16(2); u16(16); out.write("data", 4); u32(bytes);
  for (int32_t i = 0; i < audio.n; ++i) {
    double x = std::clamp(double(audio.samples[i]), -1.0, 1.0);
    int sample = std::clamp(int(std::round(x * 32768.0)), -32768, 32767);
    u16(static_cast<uint16_t>(static_cast<int16_t>(sample)));
  }
  out.close();
  if (!out) throw std::runtime_error("WAV write failed");
}

int wmain(int argc, wchar_t** argv) {
  try {
    if (argc != 4) throw std::runtime_error("Usage: benchmark MODEL_DIR OUTPUT_DIR THREADS");
    const auto started = Clock::now();
    std::filesystem::path model_dir(argv[1]), output(argv[2]);
    if (!std::filesystem::is_directory(model_dir) || std::filesystem::exists(output))
      throw std::runtime_error("Existing model and fresh output directory required");
    std::filesystem::create_directories(output);
    int threads = std::stoi(utf8(argv[3]));
    if (threads < 1 || threads > 16) throw std::runtime_error("Thread count must be 1..16");
    std::string model = (model_dir / "model.onnx").u8string();
    std::string tokens = (model_dir / "tokens.txt").u8string();
    std::string lexicon = (model_dir / "lexicon.txt").u8string();
    std::string dict = (model_dir / "dict").u8string();
    std::string fsts = (model_dir / "date.fst").u8string() + "," +
                       (model_dir / "number.fst").u8string();
    SherpaOnnxOfflineTtsConfig config{};
    config.model.vits.model = model.c_str();
    config.model.vits.tokens = tokens.c_str();
    config.model.vits.lexicon = lexicon.c_str();
    config.model.vits.dict_dir = dict.c_str();
    config.model.vits.noise_scale = .667f;
    config.model.vits.noise_scale_w = .8f;
    config.model.vits.length_scale = 1.0f;
    config.model.num_threads = threads;
    config.model.provider = "cpu";
    config.rule_fsts = fsts.c_str();
    config.max_num_sentences = 2;
    config.silence_scale = .2f;
    const auto load_start = Clock::now();
    using TtsPtr = std::unique_ptr<const SherpaOnnxOfflineTts, decltype(&SherpaOnnxDestroyOfflineTts)>;
    TtsPtr tts(SherpaOnnxCreateOfflineTts(&config), SherpaOnnxDestroyOfflineTts);
    if (!tts) throw std::runtime_error("Native TTS initialization failed");
    double load = seconds(load_start);
    std::cout << std::setprecision(10) << "READY {\"version\":\"" << SherpaOnnxGetVersionStr()
              << "\",\"git_sha\":\"" << SherpaOnnxGetGitSha1()
              << "\",\"onnxruntime\":\"" << SherpaOnnxGetOnnxruntimeVersionStr()
              << "\",\"provider\":\"cpu\",\"pid\":" << GetCurrentProcessId()
              << ",\"num_threads\":" << threads << ",\"model_load_seconds\":" << load
              << ",\"host_initialization_seconds\":" << seconds(started)
              << ",\"sample_rate\":" << SherpaOnnxOfflineTtsSampleRate(tts.get());
    resources(); std::cout << "}" << std::endl;
    std::string line;
    int index = 0;
    while (std::getline(std::cin, line)) {
      if (line == "quit") break;
      size_t tab = line.find('\t');
      std::string label = line.substr(0, tab);
      if (tab == std::string::npos || label.empty() || label.size() > 80 ||
          label.find_first_not_of("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-.") != std::string::npos)
        throw std::runtime_error("Invalid benchmark command");
      std::string text = decode_hex(line.substr(tab + 1));
      const auto begin = Clock::now();
      double cpu = cpu_seconds();
      SherpaOnnxGenerationConfig generation{};
      generation.sid = 0; generation.speed = 1.0f; generation.silence_scale = .2f;
      using AudioPtr = std::unique_ptr<const SherpaOnnxGeneratedAudio, decltype(&SherpaOnnxDestroyOfflineTtsGeneratedAudio)>;
      AudioPtr audio(SherpaOnnxOfflineTtsGenerateWithConfig(tts.get(), text.c_str(), &generation, nullptr, nullptr),
                     SherpaOnnxDestroyOfflineTtsGeneratedAudio);
      double elapsed = seconds(begin), cpu_used = cpu_seconds() - cpu;
      if (!audio || !audio->samples || audio->n <= 0 || audio->sample_rate <= 0)
        throw std::runtime_error("Empty/invalid generated audio");
      double peak = 0, energy = 0; int clipped = 0;
      for (int32_t i = 0; i < audio->n; ++i) {
        double sample = audio->samples[i];
        if (!std::isfinite(sample)) throw std::runtime_error("Nonfinite native sample");
        peak = std::max(peak, std::abs(sample)); energy += sample * sample;
        if (std::abs(sample) >= 1) ++clipped;
      }
      if (peak < 1e-5 || energy / audio->n < 1e-10)
        throw std::runtime_error("Silent generated audio");
      const auto write_start = Clock::now();
      write_pcm(output / ("speech-" + std::to_string(index) + ".wav"), *audio);
      double duration = double(audio->n) / audio->sample_rate;
      size_t chars = std::count_if(text.begin(), text.end(), [](unsigned char c){return (c & 0xc0) != 0x80;});
      std::cout << "{\"index\":" << index++ << ",\"label\":\"" << label
                << "\",\"text_chars\":" << chars << ",\"pid\":" << GetCurrentProcessId()
                << ",\"synthesis_seconds\":" << elapsed << ",\"audio_seconds\":" << duration
                << ",\"rtf\":" << elapsed / duration << ",\"audio_write_seconds\":" << seconds(write_start)
                << ",\"cpu_one_core_percent\":" << cpu_used / elapsed * 100
                << ",\"sample_rate\":" << audio->sample_rate << ",\"channels\":1,\"rms\":" << std::sqrt(energy/audio->n)
                << ",\"peak\":" << peak << ",\"clipped_fraction\":" << double(clipped)/audio->n;
      audio.reset(); resources(); std::cout << "}" << std::endl;
    }
    tts.reset(); std::cout << "CLOSED" << std::endl;
    return 0;
  } catch (const std::exception& error) {
    std::cerr << "BENCH_ERROR " << error.what() << std::endl;
    return 1;
  }
}
