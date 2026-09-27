"""MIMI's persona and system prompt.

The prompt is deliberately compact: on a handheld GPU every prompt token costs
prompt-processing time, so each line has to earn its place.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from .settings import Assistant

IDENTITY = (
    "You are MIMI — Machine Intelligence, Minus the Internet: a calm, capable assistant that runs entirely on this "
    "device with no internet connection. (Your name nods to Mímir, the Norse keeper of wisdom whose counsel Odin carried.)"
)

RULES = """How to answer:
- For factual questions, first call search_library, then answer from what you found and cite inline like [1] or [2], matching the numbered results. Never invent sources, numbers or quotes.
- One good search is usually enough; search again only if the results clearly miss the question.
- If the library doesn't cover it, say so in one short sentence, then give your best general knowledge, clearly labeled as such.
- Health, poisonous plants or mushrooms, electricity, chemicals or other safety-critical topics: stay close to the sources, add a one-line safety note and suggest professional help when appropriate.
- Don't write a reference list or "Sources:" section — the app shows the sources. Only cite numbers that appear in the search results.
- Use Markdown only when it helps (short lists, numbered steps, small tables). No filler, no preamble, no "As an AI"."""

VOICE_RULES = (
    "Spoken reply: this turn is a live voice conversation, so answer in one to three short, natural sentences. "
    "No Markdown, lists, emoji or citation markers. If you used the library, you may say where it came from in words."
)


def load_modes(config_dir: Path) -> dict:
    data = json.loads((config_dir / "modes.json").read_text("utf-8"))
    return {k: v for k, v in data.items() if not k.startswith("$")}


def _tone(a: Assistant) -> str:
    length = "Be brief and to the point" if a.verbosity < 30 else ("Be thorough and detailed when useful" if a.verbosity > 70 else "Be concise but complete")
    register = "warm and casual" if a.formality < 30 else ("polished and formal" if a.formality > 70 else "friendly and clear")
    wit = " A touch of dry wit is welcome when it fits; never be cutesy or sycophantic." if a.wit else " Keep a neutral, professional tone."
    return f"Voice: {register}. {length}.{wit}"


def build_system_prompt(
    *,
    assistant: Assistant,
    user_name: str | None,
    mode: dict | None,
    units: str,
    has_library: bool,
    has_files: bool,
) -> str:
    """The stable part of the prompt. It must not change between turns (or between text
    and voice turns), so the model server can reuse its cached computation (a big latency win)."""
    parts = [IDENTITY]
    if user_name:
        parts.append(f"You're talking with {user_name}. Preferred units: {units}.")
    parts.append(_tone(assistant))
    if has_library:
        parts.append(RULES)
    else:
        parts.append("The offline library is not installed yet, so answer from general knowledge and say so when facts matter.")
    if has_files:
        parts.append("The user's own documents and voice notes are searchable with search_my_files.")
    if assistant.about_me.strip():
        parts.append(f"The user describes themselves: {assistant.about_me.strip()}")
    parts.append("Each user message may start with a bracketed context note from MIMI (time, location, memories). The user didn't write it; use it quietly. "
                 "If the user shares a lasting personal fact or preference (or asks you to remember something), call remember.")
    if mode and mode.get("instructions"):
        parts.append(f"Mode — {mode['name']}: {mode['instructions']}")
    if assistant.custom_instructions.strip():
        parts.append(f"User's instructions: {assistant.custom_instructions.strip()}")
    return "\n\n".join(parts)


def build_context(*, memories: list[dict], location: str | None, time_format: str, voice: bool = False,
                  now: datetime | None = None) -> str:
    """Per-turn facts, prepended to the user's message (outside the cached prefix)."""
    now = now or datetime.now()
    clock = now.strftime("%I:%M %p").lstrip("0") if time_format == "12h" else now.strftime("%H:%M")
    bits = [f"{now.strftime('%A, %d %B %Y')}, {clock}"]
    if location:
        bits.append(f"location: {location}")
    note = "[Context — " + " · ".join(bits) + "]"
    if memories:
        note += "\n[Remembered about the user — " + "; ".join(m["text"].rstrip(".") for m in memories) + "]"
    if voice:
        note += f"\n[{VOICE_RULES}]"
    return note


TITLE_FOLLOWUP = (
    "Now write a short, specific title for this conversation: 3 to 6 words, no quotes, no trailing period. "
    "Reply with only the title."
)

TITLE_PROMPT = (
    "Write a short, specific title (3–6 words, no quotes, no trailing period) for a conversation that starts with this message:\n\n{text}"
)
