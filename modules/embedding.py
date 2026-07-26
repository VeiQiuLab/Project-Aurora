"""Ollama embedding provider abstraction for Project Aurora."""

import json
import urllib.error
import urllib.request

from modules.settings import settings


DEFAULT_EMBEDDING_TIMEOUT = 60


class EmbeddingError(Exception):
    """Raised when embedding generation fails."""


class OllamaEmbeddingProvider:
    """Generate embeddings through the configured Ollama endpoint."""

    def __init__(self, model=None, host=None, timeout=DEFAULT_EMBEDDING_TIMEOUT):
        self.model = str(model or settings.get("embedding_model", "nomic-embed-text:latest") or "").strip()
        self.host = str(host or settings.get("ollama.host", "http://127.0.0.1:11434") or "").strip().rstrip("/")
        self.timeout = timeout

    def embed_text(self, text):
        content = str(text or "").strip()
        if not content:
            return []
        if not self.host:
            raise EmbeddingError("Ollama host is not configured.")
        if not self.model:
            raise EmbeddingError("Embedding model is not configured.")

        payload = {
            "model": self.model,
            "prompt": content
        }
        request = urllib.request.Request(
            f"{self.host}/api/embeddings",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            raise EmbeddingError(f"Ollama embedding request failed. HTTP {error.code}.") from error
        except (OSError, ValueError, json.JSONDecodeError) as error:
            raise EmbeddingError(f"Ollama embedding response invalid: {error}") from error

        embedding = data.get("embedding")
        if not isinstance(embedding, list):
            raise EmbeddingError("Ollama embedding response missing vector.")
        return [float(value) for value in embedding]


def get_embedding_provider(model=None, host=None, timeout=DEFAULT_EMBEDDING_TIMEOUT):
    return OllamaEmbeddingProvider(model=model, host=host, timeout=timeout)
