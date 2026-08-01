"""Section-aware ranking for normalized retrieval results."""

from copy import deepcopy


_IMPORTANCE_VALUES = {
    "low": 0.25,
    "normal": 0.5,
    "medium": 0.5,
    "high": 1.0,
}

_DEFAULT_WEIGHTS = {
    "knowledge": {
        "vector": 0.45,
        "keyword": 0.35,
        "importance": 0.0,
        "confidence": 0.0,
        "freshness": 0.10,
        "source": 0.10,
    },
    "memory": {
        "vector": 0.0,
        "keyword": 0.20,
        "importance": 0.45,
        "confidence": 0.25,
        "freshness": 0.10,
        "source": 0.0,
    },
    "default": {
        "vector": 0.35,
        "keyword": 0.30,
        "importance": 0.15,
        "confidence": 0.10,
        "freshness": 0.05,
        "source": 0.05,
    },
}


def _clamp(value):
    return max(0.0, min(1.0, value))


def normalize_score(value, method):
    """Normalize one score to the range 0.0-1.0 without changing the input."""

    name = str(method or "").casefold()
    if value is None:
        return 0.0
    if name == "importance" and isinstance(value, str):
        return _IMPORTANCE_VALUES.get(value.casefold(), 0.0)
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return 0.0
    if name == "keyword":
        if numeric <= 0:
            return 0.0
        return numeric / (numeric + 10.0)
    if name == "importance" and numeric > 1.0:
        numeric /= 10.0
    return _clamp(numeric)


class RAGRanker:
    """Rank normalized retrieval results without calling retrieval services."""

    def rank_results(self, results, *, section=None, weights=None):
        if not isinstance(results, (list, tuple)):
            return []

        ranked = []
        for index, result in enumerate(results):
            if not isinstance(result, dict):
                continue
            ranked.append((index, self.rank_result(result, section=section, weights=weights)))
        ranked.sort(key=lambda item: (-item[1]["rank_score"], item[0]))
        return [item[1] for item in ranked]

    def rank_result(self, result, *, section=None, weights=None):
        ranked = deepcopy(result) if isinstance(result, dict) else {}
        resolved_section = self._section(result, section)
        resolved_weights = deepcopy(_DEFAULT_WEIGHTS.get(resolved_section, _DEFAULT_WEIGHTS["default"]))
        if isinstance(weights, dict):
            resolved_weights.update({key: float(value) for key, value in weights.items() if key in resolved_weights})

        features = self._features(ranked)
        active_weights = {
            key: weight
            for key, weight in resolved_weights.items()
            if weight > 0 and features.get(key) is not None
        }
        weight_total = sum(active_weights.values())
        rank_score = 0.0
        if weight_total > 0:
            rank_score = sum(features[key] * weight for key, weight in active_weights.items()) / weight_total
        details = {
            key: features.get(key)
            for key in ("vector", "keyword", "importance", "confidence", "freshness", "source")
        }
        details["section"] = resolved_section
        details["weights"] = active_weights
        details["reason"] = self._reason(details, active_weights)
        ranked["rank_score"] = rank_score
        ranked["ranking_details"] = details
        return ranked

    @staticmethod
    def _section(result, section):
        if section:
            return str(section).casefold()
        source = result.get("source") if isinstance(result, dict) else {}
        if isinstance(source, dict) and source.get("kind"):
            return str(source["kind"]).casefold()
        return "default"

    @staticmethod
    def _features(result):
        score_details = result.get("score_details") if isinstance(result.get("score_details"), dict) else {}
        metadata = result.get("metadata") if isinstance(result.get("metadata"), dict) else {}
        retrieval_method = result.get("retrieval_method") or score_details.get("method")
        raw_score = result.get("score")

        vector = score_details.get("vector")
        keyword = score_details.get("keyword")
        if vector is None and keyword is None and raw_score is not None:
            if str(retrieval_method or "").casefold() == "keyword":
                keyword = raw_score
            else:
                vector = raw_score

        return {
            "vector": normalize_score(vector, "vector") if vector is not None else None,
            "keyword": normalize_score(keyword, "keyword") if keyword is not None else None,
            "importance": (
                normalize_score(score_details.get("importance", metadata.get("importance")), "importance")
                if score_details.get("importance", metadata.get("importance")) is not None
                else None
            ),
            "confidence": (
                normalize_score(score_details.get("confidence", metadata.get("confidence")), "confidence")
                if score_details.get("confidence", metadata.get("confidence")) is not None
                else None
            ),
            "freshness": (
                normalize_score(score_details.get("freshness", metadata.get("freshness")), "freshness")
                if score_details.get("freshness", metadata.get("freshness")) is not None
                else None
            ),
            "source": (
                normalize_score(score_details.get("source", metadata.get("source_quality")), "source")
                if score_details.get("source", metadata.get("source_quality")) is not None
                else None
            ),
        }

    @staticmethod
    def _reason(details, active_weights):
        parts = [
            f"{key}={details[key]:.3f}"
            for key in ("vector", "keyword", "importance", "confidence", "freshness", "source")
            if key in active_weights and details.get(key) is not None
        ]
        return f"{details['section']} ranking: " + ", ".join(parts) if parts else f"{details['section']} ranking: no scores"


def rank_results(results, *, section=None, weights=None):
    """Rank normalized results with the default RAGRanker."""

    return RAGRanker().rank_results(results, section=section, weights=weights)
