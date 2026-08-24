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


class _FreeGoogle:
    """Free Google translation over the endpoints Chrome itself uses.

    deep-translator scrapes translate.google.com/m, which now answers 500 (or
    HTML we cannot parse) often enough to break live use. These JSON endpoints
    are stable and fast; the second is tried only if the first fails.
    """

    _ENDPOINTS = (
        "https://clients5.google.com/translate_a/t?client=dict-chrome-ex",
        "https://translate.googleapis.com/translate_a/single?client=gtx&dt=t",
    )
    _HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
        )
    }

    def __init__(self, source: str, target: str, api_key: str = ""):
        import requests  # lazy import

        self._session = requests.Session()
        self._source = source or "auto"
        self._target = target

    def translate(self, text: str) -> str:
        import urllib.parse

        params = "&sl=%s&tl=%s&q=%s" % (
            self._source, self._target, urllib.parse.quote(text)
        )
        last = None
        for base in self._ENDPOINTS:
            try:
                resp = self._session.get(
                    base + params, headers=self._HEADERS, timeout=10
                )
                if resp.status_code != 200:
                    last = f"HTTP {resp.status_code}"
                    continue
                out = self._parse(resp.json())
                if out:
                    return out
                last = "empty response"
            except Exception as exc:            # network / JSON errors
                last = f"{type(exc).__name__}: {exc}"
        raise RuntimeError(f"Google (free) failed: {last}")

    @staticmethod
    def _parse(data) -> str:
        """Handle every shape these endpoints return."""
        # dict-chrome-ex: ["text"]  or  [["text", "detected-src"]]
        if isinstance(data, list) and data and isinstance(data[0], str):
            return data[0].strip()
        if isinstance(data, list) and data and isinstance(data[0], list):
            first = data[0]
            if first and isinstance(first[0], str) and len(first) <= 2:
                return first[0].strip()
            # gtx: [[["chunk", "src", ...], ...], ...]
            parts = [p[0] for p in first if isinstance(p, list) and p and p[0]]
            return "".join(parts).strip()
        if isinstance(data, dict):              # {"sentences": [{"trans": ...}]}
            return "".join(
                s.get("trans", "") for s in data.get("sentences", [])
            ).strip()
        return ""


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
        "Google (free)", False, True, lambda s, t, k: _FreeGoogle(s, t, k)
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
