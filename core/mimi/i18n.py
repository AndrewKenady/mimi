"""Core's own words in the interface language (English, Spanish, French).

The interface sends its language with every request (the ``x-mimi-locale`` header), and
``LocaleMiddleware`` makes it the current locale for everything that request runs,
including a streamed chat turn. Core uses it for the text it writes itself: chat status
lines, tool activity, citation-check reasons, book status notes and error messages.
Free text that Core passes along (book titles, article text, the user's words, model
output) is never translated.

Messages are keyed by their English text (``i18n_messages.py``), so the English code
reads as it always did and a missing translation falls back to English.

- ``tr(template, **params)`` words a message in the current locale.
- ``localize(text)`` translates text Core has already written in English (an error
  ``detail``, a stored book note, a tool label) by matching it against the templates.
  Placeholder values stay as they are, except those named in ``_TRANSLATED_PARAMS``
  ("the library", "talks"), which are looked up themselves.
"""

from __future__ import annotations

import re
from contextvars import ContextVar
from functools import cache

from .i18n_messages import MESSAGES

LOCALES = ("en", "es", "fr")
LANGUAGE_NAMES = {"en": "English", "es": "Spanish", "fr": "French"}  # as the model reads them
_current: ContextVar[str] = ContextVar("mimi_locale", default="en")
_TRANSLATED_PARAMS = {"where", "noun"}


def normalize(value: str | None) -> str:
    base = (value or "").strip().lower().split("-")[0]
    return base if base in LOCALES else "en"


def current() -> str:
    return _current.get()


def use(locale: str | None):
    """Make `locale` current until the returned token is reset (``_current.reset``)."""
    return _current.set(normalize(locale))


def tr(template: str, /, **params) -> str:
    msg = MESSAGES.get(current(), {}).get(template, template)
    return msg.format(**params) if params else msg


@cache
def _patterns(locale: str) -> list[tuple[re.Pattern, str, str]]:
    out = []
    for en in MESSAGES.get(locale, {}):
        if "{" not in en:
            continue
        rx = "".join(f"(?P<{p[1:-1]}>.+?)" if p.startswith("{") else re.escape(p) for p in re.split(r"(\{\w+\})", en) if p)
        out.append((re.compile(rx + r"\Z", re.S), en, rx))
    out.sort(key=lambda x: -len(x[2]))  # most specific first
    return out


def localize(text: str | None) -> str | None:
    """`text`, written by Core in English, in the current locale when a message matches."""
    loc = current()
    if not text or loc == "en":
        return text
    table = MESSAGES.get(loc, {})
    if text in table:
        return table[text]
    for rx, en, _ in _patterns(loc):
        m = rx.match(text)
        if m:
            params = {k: (localize(v) if k in _TRANSLATED_PARAMS else v) for k, v in m.groupdict().items()}
            return table[en].format(**params)
    return text


def join(names: list[str]) -> str:
    """"A, B and C" in the current language."""
    if len(names) < 2:
        return "".join(names)
    return ", ".join(names[:-1]) + tr(" and ") + names[-1]


class LocaleMiddleware:
    """ASGI middleware: the request's ``x-mimi-locale`` is current for as long as it runs."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket"):
            return await self.app(scope, receive, send)
        raw = next((v for k, v in scope.get("headers") or [] if k == b"x-mimi-locale"), b"")
        token = use(raw.decode("latin-1"))
        try:
            await self.app(scope, receive, send)
        finally:
            _current.reset(token)


# --------------------------------------------------------------------------- detection
_WORD = re.compile(r"[a-záéíóúüñàâçèêëîïôûùœ'’-]+")
_MARKERS = {
    "en": set("the and of to is are was were what how why when where which who you your it this that with for not can should do does "
              "my i have has".split()),
    "es": set("el la los las del que qué y es son está están cómo como cuándo dónde por para con un una no se su lo mi tengo puedo "
              "debo hay muy pero más cuál cuánto cuántos quién".split()),
    "fr": set("le la les des du et est sont que qui quoi comment pourquoi quand où un une pas ne je vous mon ma mes dans pour avec "
              "sur ce cette il elle peut dois faut est-ce".split()),
}
_ONLY = {"es": re.compile(r"[ñ¿¡]"), "fr": re.compile(r"[çœàèêâîôûù]")}


def detect(text: str | None) -> str | None:
    """'en', 'es' or 'fr' when the text is clearly in one of them, else None (too short, mixed)."""
    words = _WORD.findall((text or "").lower())
    if not words:
        return None
    score = {lang: sum(w in m for w in words) for lang, m in _MARKERS.items()}
    for lang, rx in _ONLY.items():
        if rx.search(text or ""):
            score[lang] += 2
    best = max(score, key=score.get)
    second = sorted(score.values())[-2]
    return best if score[best] >= 2 and score[best] > second else None
