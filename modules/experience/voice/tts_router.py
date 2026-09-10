"""Provider-neutral TTS routing with reserved extension points."""

from __future__ import annotations

from collections.abc import Mapping
from threading import Event

from .interfaces import TTSProvider
from .models import TTSRequest, TTSResponse, VoiceOptions


RESERVED_TTS_PROVIDERS = (
    "local_cosyvoice",
    "remote_cosyvoice",
    "cloud_tts",
)


class TTSRouter(TTSProvider):
    """Select a configured provider without exposing provider details upstream."""

    def __init__(
        self,
        providers: Mapping[str, TTSProvider],
        *,
        default_provider: str,
    ) -> None:
        self._providers = dict(providers)
        self.default_provider = default_provider
        if default_provider not in self._providers:
            raise ValueError(f"default TTS provider is not registered: {default_provider}")

    @property
    def providers(self) -> tuple[str, ...]:
        """Names available to the application (reserved providers are not implied)."""

        return tuple(self._providers)

    def provider_for(self, name: str | None = None) -> TTSProvider:
        selected = name or self.default_provider
        try:
            return self._providers[selected]
        except KeyError as exc:
            if selected in RESERVED_TTS_PROVIDERS:
                raise ValueError(f"TTS provider is reserved but not implemented: {selected}") from exc
            raise ValueError(f"unsupported TTS provider: {selected}") from exc

    def synthesize(
        self,
        text: str,
        options: VoiceOptions | None = None,
        *,
        timeout_seconds: float | None = None,
        cancel_event: Event | None = None,
    ) -> TTSResponse:
        return self.synthesize_request(
            TTSRequest(
                text=text,
                options=options or VoiceOptions(),
                timeout_seconds=timeout_seconds,
                cancel_event=cancel_event,
            )
        )

    def synthesize_request(self, request: TTSRequest) -> TTSResponse:
        if not isinstance(request, TTSRequest):
            raise TypeError("request must be a TTSRequest")
        return self.provider_for(request.provider).synthesize_request(request)
