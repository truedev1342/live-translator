"""Translation engine abstraction.

Supports free (no-key) engines via `deep-translator` and optional official
APIs (Google Cloud Translation, DeepL) when an API key is supplied.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict, List


# ---------------------------------------------------------------------------
# Language table (name -> ISO code understood by the engines)
# ---------------------------------------------------------------------------
LANGUAGES: Dict[str, str] = {
    "Auto detect": "auto",
    "English": "en",
    "Vietnamese": "vi",
    "Spanish": "es",
    "French": "fr",
    "German": "de",
    "Italian": "it",
    "Portuguese": "pt",
    "Russian": "ru",
    "Japanese": "ja",
    "Korean": "ko",
    "Chinese (Simplified)": "zh-CN",
    "Chinese (Traditional)": "zh-TW",
    "Thai": "th",
    "Indonesian": "id",
    "Arabic": "ar",
    "Hindi": "hi",
    "Dutch": "nl",
    "Polish": "pl",
    "Turkish": "tr",
    "Ukrainian": "uk",
}


@dataclass
class EngineSpec:
    """Metadata describing a translation engine and how to build it."""

    name: str
    needs_key: bool
    supports_auto_source: bool
    factory: Callable  # (source, target, api_key) -> object with .translate(text)


class _CloudGoogle:
    """Thin wrapper around google-cloud-translate if the user provides a key."""

    def __init__(self, source: str, target: str, api_key: str):
        from google.cloud import translate_v2 as gtranslate  # lazy import

        self._client = gtranslate.Client(api_key=api_key)
        self._source = None if source == "auto" else source
        self._target = target

    def translate(self, text: str) -> str:
        result = self._client.translate(
            text, target_language=self._target, source_language=self._source
        )
        return result["translatedText"]


def _make_deep(engine_cls_name: str):
    """Return a factory that builds a deep-translator engine by class name."""

    def factory(source: str, target: str, api_key: str):
        import deep_translator  # lazy import

        cls = getattr(deep_translator, engine_cls_name)
        kwargs = {"source": source, "target": target}
        if api_key:
            kwargs["api_key"] = api_key
        return cls(**kwargs)

    return factory


ENGINES: Dict[str, EngineSpec] = {
    "Google (free)": EngineSpec(
        "Google (free)", False, True, _make_deep("GoogleTranslator")
    ),
    "MyMemory (free)": EngineSpec(
        "MyMemory (free)", False, True, _make_deep("MyMemoryTranslator")
    ),
    "Google Cloud (API key)": EngineSpec(
        "Google Cloud (API key)", True, True,
        lambda s, t, k: _CloudGoogle(s, t, k),
    ),
    "DeepL (API key)": EngineSpec(
        "DeepL (API key)", True, False, _make_deep("DeeplTranslator")
    ),
}


class Translator:
    """Builds and caches the active engine, exposes a single translate() call."""

    def __init__(self):
        self._engine = None
        self._key = (None, None, None, None)  # engine, source, target, api_key

    def configure(self, engine_name: str, source: str, target: str, api_key: str = ""):
        key = (engine_name, source, target, api_key)
        if key == self._key and self._engine is not None:
            return
        spec = ENGINES[engine_name]
        eff_source = source
        if source == "auto" and not spec.supports_auto_source:
            eff_source = "en"  # DeepL etc. need an explicit source
        self._engine = spec.factory(eff_source, target, api_key)
        self._key = key

    def translate(self, text: str) -> str:
        if not self._engine:
            raise RuntimeError("Translator not configured")
        text = text.strip()
        if not text:
            return ""
        return self._engine.translate(text)
