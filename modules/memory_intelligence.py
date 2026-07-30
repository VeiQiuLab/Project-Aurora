"""Memory candidate analysis helpers for the C5 Intelligence Layer."""

from __future__ import annotations

import re
from copy import deepcopy
from typing import Any


MEMORY_TYPES = {"preference", "fact", "instruction"}
ANALYSIS_VERSION = "memory_intelligence_v1"

SENSITIVE_PATTERNS = [
    r"\b\d{3}[- ]?\d{2}[- ]?\d{4}\b",
    r"\b(?:\d[ -]*?){13,19}\b",
    r"\b\d{6,}\b",
    r"password|passcode|token|api[_ -]?key|secret|credential",
    r"private key|access key|auth token|bearer\s+[a-z0-9._-]+",
    r"身份证|银行卡|验证码|密码|密钥|令牌",
]

TEMPORARY_PATTERNS = [
    r"\btoday\b|\btomorrow\b|\byesterday\b|\btonight\b|\bthis week\b",
    r"\btemporary\b|\bfor now\b|\bone time\b|\bonce\b",
    r"今天|明天|昨天|今晚|这周|临时|一次性|暂时",
]

LOW_QUALITY_PATTERNS = [
    r"\bmaybe\b|\bprobably\b|\btry\b|\btest\b|\bwhatever\b",
    r"可能|也许|试试|测试|随便|不确定",
]

HIGH_VALUE_PATTERNS = [
    r"\balways\b|\bprefer\b|\bimportant\b|\bremember\b|\bdefault\b",
    r"always use|usually use|please remember",
    r"总是|长期|重要|默认|记住|偏好|习惯",
]

CATEGORY_RULES = [
    (
        "communication_style",
        [
            r"\bconcise\b|\bdetailed\b|\btone\b|\bstyle\b|\blanguage\b",
            r"简洁|详细|语气|风格|语言|中文|英文",
        ],
    ),
    (
        "workflow_instruction",
        [
            r"\balways\b|\bnever\b|\bdefault\b|\bwhen\b|\bworkflow\b",
            r"总是|不要|默认|流程|提交|测试|报告",
        ],
    ),
    (
        "project_information",
        [
            r"\bproject\b|\brepo\b|\bbranch\b|\barchitecture\b|\bversion\b",
            r"项目|仓库|分支|架构|版本|模块",
        ],
    ),
    (
        "environment_detail",
        [
            r"\bwindows\b|\bmacos\b|\blinux\b|\bpython\b|\bnode\b|\bdevice\b",
            r"Windows|Python|Node|设备|环境|本地",
        ],
    ),
]


def analyze_memory_candidates(
    messages_or_text: Any,
    *,
    base_candidates: list[dict[str, Any]] | None = None,
    min_score: float = 0.75,
    source: str = "chat",
) -> list[dict[str, Any]]:
    """Return enhanced memory candidates without reading or writing storage."""

    return MemoryIntelligence().analyze(
        messages_or_text,
        base_candidates=base_candidates,
        min_score=min_score,
        source=source,
    )


class MemoryIntelligence:
    """Enhance candidate records with deterministic analysis metadata."""

    def analyze(
        self,
        messages_or_text: Any,
        *,
        base_candidates: list[dict[str, Any]] | None = None,
        min_score: float = 0.75,
        source: str = "chat",
    ) -> list[dict[str, Any]]:
        text = self._message_text(messages_or_text)
        candidates = base_candidates
        if candidates is None:
            candidates = self._fallback_candidates(text, min_score=min_score, source=source)

        enhanced = []
        for raw_candidate in candidates or []:
            if not isinstance(raw_candidate, dict):
                continue
            candidate = deepcopy(raw_candidate)
            candidate.setdefault("source", source)
            candidate["type"] = self._memory_type(candidate.get("type"))
            candidate.setdefault("content", "")
            content = str(candidate.get("content", "")).strip()
            if not content:
                continue
            candidate["content"] = content

            risk = MemoryRiskAnalyzer().analyze(content)
            score = MemoryCandidateScorer().score(candidate, risk)
            category = MemoryCandidateClassifier().classify(candidate)

            candidate.setdefault("category", category)
            candidate.setdefault("confidence", score["confidence"])
            candidate.setdefault("importance_score", score["importance_score"])
            candidate["importance"] = score["importance"]
            candidate.setdefault("risk", risk)
            candidate.setdefault("explanation", self._explanation(candidate, risk))
            candidate.setdefault("source_detail", {
                "kind": source,
                "extractor": ANALYSIS_VERSION,
                "signals": score["signals"],
            })
            candidate.setdefault("analysis_version", ANALYSIS_VERSION)
            if risk["level"] == "high":
                candidate.setdefault("blocked", True)
            enhanced.append(candidate)
        return enhanced

    @staticmethod
    def _message_text(messages_or_text: Any) -> str:
        if isinstance(messages_or_text, str):
            return messages_or_text
        lines = []
        for message in messages_or_text or []:
            if not isinstance(message, dict):
                continue
            if message.get("role") not in {"user", "assistant"}:
                continue
            content = str(message.get("content", "")).strip()
            if content:
                lines.append(content)
        return "\n".join(lines)

    @staticmethod
    def _memory_type(value: Any) -> str:
        memory_type = str(value or "fact").strip()
        return memory_type if memory_type in MEMORY_TYPES else "fact"

    @classmethod
    def _fallback_candidates(cls, text: str, *, min_score: float, source: str) -> list[dict[str, Any]]:
        candidates = []
        for line in re.split(r"[\n\r]+", str(text or "")):
            content = re.sub(r"\s+", " ", line).strip(" .")
            if not content:
                continue
            memory_type = cls._fallback_type(content)
            if memory_type is None:
                continue
            score = 0.85 if memory_type != "fact" else 0.78
            if score < float(min_score):
                continue
            candidates.append({
                "type": memory_type,
                "content": content[:240],
                "score": score,
                "importance": "normal",
                "source": source,
            })
        return candidates

    @staticmethod
    def _fallback_type(content: str) -> str | None:
        text = content.casefold()
        if re.search(r"\bremember that\b|\bplease remember\b|记住|请记住", text):
            return "instruction"
        if re.search(r"\bprefer\b|\blike\b|\busually use\b|\balways use\b|偏好|喜欢|习惯", text):
            return "preference"
        if re.search(r"\bmy (name|role|project|device)\b|我的(名字|角色|项目|设备)", text):
            return "fact"
        return None

    @staticmethod
    def _explanation(candidate: dict[str, Any], risk: dict[str, Any]) -> str:
        if risk["level"] == "high":
            return "risk_high_candidate"
        if candidate.get("category") == "workflow_instruction":
            return "workflow_instruction_candidate"
        if candidate.get("type") == "preference":
            return "preference_candidate"
        return "memory_candidate"


class MemoryRiskAnalyzer:
    """Classify candidate risk using deterministic local rules."""

    def analyze(self, content: str) -> dict[str, Any]:
        reasons = []
        if self._matches(SENSITIVE_PATTERNS, content):
            reasons.append("sensitive_information")
        if self._matches(TEMPORARY_PATTERNS, content):
            reasons.append("temporary_information")
        if self._matches(LOW_QUALITY_PATTERNS, content):
            reasons.append("low_quality_signal")

        if "sensitive_information" in reasons:
            level = "high"
        elif reasons:
            level = "medium"
        else:
            level = "low"
        return {"level": level, "reasons": reasons}

    @staticmethod
    def _matches(patterns: list[str], content: str) -> bool:
        return any(re.search(pattern, str(content or ""), re.IGNORECASE) for pattern in patterns)


class MemoryCandidateClassifier:
    """Assign a user-facing candidate category without changing memory type."""

    def classify(self, candidate: dict[str, Any]) -> str:
        content = str(candidate.get("content", ""))
        memory_type = str(candidate.get("type", "fact"))
        for category, patterns in CATEGORY_RULES:
            if any(re.search(pattern, content, re.IGNORECASE) for pattern in patterns):
                return category
        if memory_type == "preference":
            return "user_preference"
        if memory_type == "instruction":
            return "workflow_instruction"
        return "long_term_fact"


class MemoryCandidateScorer:
    """Produce confidence and importance hints for a candidate."""

    def score(self, candidate: dict[str, Any], risk: dict[str, Any]) -> dict[str, Any]:
        signals = []
        try:
            base_score = float(candidate.get("score", 0.0))
        except (TypeError, ValueError):
            base_score = 0.0
        confidence = max(0.0, min(1.0, base_score))
        importance_score = confidence * 10.0

        memory_type = str(candidate.get("type", "fact"))
        if memory_type == "instruction":
            importance_score += 1.0
            signals.append("instruction_type")
        elif memory_type == "preference":
            importance_score += 0.7
            signals.append("preference_type")

        content = str(candidate.get("content", ""))
        if self._matches(HIGH_VALUE_PATTERNS, content):
            confidence = min(1.0, confidence + 0.08)
            importance_score += 1.0
            signals.append("high_value_signal")
        if self._matches(LOW_QUALITY_PATTERNS, content):
            confidence = max(0.0, confidence - 0.25)
            importance_score -= 2.0
            signals.append("low_quality_signal")
        if risk["level"] == "medium":
            confidence = max(0.0, confidence - 0.15)
            importance_score -= 1.0
            signals.append("medium_risk")
        elif risk["level"] == "high":
            confidence = max(0.0, confidence - 0.45)
            importance_score = min(importance_score, 2.0)
            signals.append("high_risk")

        importance_score = max(0.0, min(10.0, importance_score))
        return {
            "confidence": round(confidence, 3),
            "importance_score": round(importance_score, 2),
            "importance": self._importance_label(importance_score),
            "signals": signals,
        }

    @staticmethod
    def _matches(patterns: list[str], content: str) -> bool:
        return any(re.search(pattern, str(content or ""), re.IGNORECASE) for pattern in patterns)

    @staticmethod
    def _importance_label(score: float) -> str:
        if score >= 8.0:
            return "high"
        if score <= 2.0:
            return "low"
        return "normal"
