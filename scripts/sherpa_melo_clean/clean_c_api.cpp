// Feasibility-only subset of v1.13.8 C ABI. NOT a general sherpa replacement.
// Reuses untouched upstream Melo frontend/inference/FST/silence utilities.
#include <array>
#include <cmath>
#include <cstdio>
#include <memory>
#include <stdexcept>
#include <string>
#include <vector>
#include "sherpa-onnx/c-api/c-api.h"
#include "sherpa-onnx/csrc/melo-tts-lexicon.h"
#include "sherpa-onnx/csrc/offline-tts.h"
#include "sherpa-onnx/csrc/offline-tts-vits-model.h"
#include "sherpa-onnx/csrc/text-utils.h"
#include "kaldifst/csrc/text-normalizer.h"

struct SherpaOnnxOfflineTts {
  std::unique_ptr<sherpa_onnx::OfflineTtsVitsModel> model;
  std::unique_ptr<sherpa_onnx::MeloTtsLexicon> frontend;
  std::vector<std::unique_ptr<kaldifst::TextNormalizer>> rules;
  int batch = 2;
  bool debug = false;
};
static std::string value(const char* s) { return s ? s : ""; }
// Same blank interspersing as OfflineTtsImpl::AddBlank (ID 0).
static std::vector<int64_t> blanks(const std::vector<int64_t>& x) {
  std::vector<int64_t> out(x.size() * 2 + 1, 0);
  for (size_t i = 0; i < x.size(); ++i) out[2 * i + 1] = x[i];
  return out;
}
extern "C" {
const char* SherpaOnnxGetVersionStr() { return "1.13.8-clean-melo-experiment"; }
const char* SherpaOnnxGetGitSha1() { return "11afbd009a7f8c08f4bcf2fc1b265d0df4670fbf"; }
const char* SherpaOnnxGetOnnxruntimeVersionStr() { return OrtGetApiBase()->GetVersionString(); }
const SherpaOnnxOfflineTts* SherpaOnnxCreateOfflineTts(const SherpaOnnxOfflineTtsConfig* c) {
  try {
    if (!c || !value(c->model.vits.data_dir).empty() || !value(c->rule_fars).empty())
      throw std::invalid_argument("Only Melo lexicon + rule FST supported");
    sherpa_onnx::OfflineTtsModelConfig model;
    model.num_threads = c->model.num_threads;
    model.provider = value(c->model.provider);
    model.debug = c->model.debug != 0;
    model.vits.model = value(c->model.vits.model);
    model.vits.tokens = value(c->model.vits.tokens);
    model.vits.lexicon = value(c->model.vits.lexicon);
    model.vits.noise_scale = c->model.vits.noise_scale ? c->model.vits.noise_scale : .667f;
    model.vits.noise_scale_w = c->model.vits.noise_scale_w ? c->model.vits.noise_scale_w : .8f;
    model.vits.length_scale = c->model.vits.length_scale ? c->model.vits.length_scale : 1.f;
    auto result = std::make_unique<SherpaOnnxOfflineTts>();
    result->debug = model.debug;
    result->batch = c->max_num_sentences;
    result->model = std::make_unique<sherpa_onnx::OfflineTtsVitsModel>(model);
    if (!result->model->GetMetaData().is_melo_tts)
      throw std::invalid_argument("Only audited Melo model supported");
    result->frontend = std::make_unique<sherpa_onnx::MeloTtsLexicon>(model.vits.lexicon,
        model.vits.tokens, result->model->GetMetaData(), model.debug);
    std::vector<std::string> rules;
    sherpa_onnx::SplitStringToVector(value(c->rule_fsts), ",", false, &rules);
    for (const auto& rule : rules)
      result->rules.push_back(std::make_unique<kaldifst::TextNormalizer>(rule));
    return result.release();
  } catch (const std::exception& e) { std::fprintf(stderr, "clean create: %s\n", e.what()); return nullptr; }
}
void SherpaOnnxDestroyOfflineTts(const SherpaOnnxOfflineTts* t) { delete t; }
int32_t SherpaOnnxOfflineTtsSampleRate(const SherpaOnnxOfflineTts* t) {
  return t ? t->model->GetMetaData().sample_rate : 0;
}
const SherpaOnnxGeneratedAudio* SherpaOnnxOfflineTtsGenerateWithConfig(
    const SherpaOnnxOfflineTts* t, const char* raw, const SherpaOnnxGenerationConfig* c,
    SherpaOnnxGeneratedAudioProgressCallbackWithArg callback, void* arg) {
  try {
    if (!t || !raw || !c || !std::isfinite(c->speed) || c->speed <= 0)
      throw std::invalid_argument("Invalid generation arguments");
    std::string text(raw);
    if (t->debug) std::fprintf(stderr, "Raw text: %s\n", raw);
    for (const auto& rule : t->rules) {
      text = rule->Normalize(text);
      if (t->debug) std::fprintf(stderr, "After normalizing: %s\n", text.c_str());
    }
    auto sentences = t->frontend->ConvertTextToTokenIds(text);
    if (sentences.empty()) throw std::runtime_error("No text tokens");
    if (t->model->GetMetaData().add_blank) for (auto& s : sentences) {
      s.tokens = blanks(s.tokens);
      s.tones = blanks(s.tones);
    }
    const size_t batch = t->batch > 0 ? size_t(t->batch) : sentences.size();
    std::vector<float> samples;
    for (size_t begin = 0; begin < sentences.size(); begin += batch) {
      std::vector<int64_t> tokens, tones;
      for (size_t i = begin; i < std::min(begin + batch, sentences.size()); ++i) {
        tokens.insert(tokens.end(), sentences[i].tokens.begin(), sentences[i].tokens.end());
        tones.insert(tones.end(), sentences[i].tones.begin(), sentences[i].tones.end());
      }
      if (tokens.empty() || tokens.size() != tones.size()) throw std::runtime_error("Invalid tokens/tones");
      auto memory = Ort::MemoryInfo::CreateCpu(OrtDeviceAllocator, OrtMemTypeDefault);
      std::array<int64_t, 2> shape{1, int64_t(tokens.size())};
      auto x = Ort::Value::CreateTensor(memory, tokens.data(), tokens.size(), shape.data(), 2);
      auto tone = Ort::Value::CreateTensor(memory, tones.data(), tones.size(), shape.data(), 2);
      auto audio = t->model->Run(std::move(x), std::move(tone), c->sid, c->speed);
      const auto n = audio.GetTensorTypeAndShapeInfo().GetElementCount();
      const auto* p = audio.GetTensorData<float>();
      sherpa_onnx::GeneratedAudio part;
      part.sample_rate = t->model->GetMetaData().sample_rate;
      part.samples.assign(p, p + n);
      part = part.ScaleSilence(c->silence_scale);
      samples.insert(samples.end(), part.samples.begin(), part.samples.end());
      if (callback && !callback(part.samples.data(), int32_t(part.samples.size()),
          float(std::min(begin + batch, sentences.size())) / sentences.size(), arg)) break;
    }
    auto result = std::make_unique<SherpaOnnxGeneratedAudio>();
    auto data = std::make_unique<float[]>(samples.size());
    std::copy(samples.begin(), samples.end(), data.get());
    result->samples = data.release();
    result->n = int32_t(samples.size());
    result->sample_rate = t->model->GetMetaData().sample_rate;
    return result.release();
  } catch (const std::exception& e) { std::fprintf(stderr, "clean generate: %s\n", e.what()); return nullptr; }
}
void SherpaOnnxDestroyOfflineTtsGeneratedAudio(const SherpaOnnxGeneratedAudio* audio) {
  if (audio) { delete[] audio->samples; delete audio; }
}
}
