"""Citation grounding: is each claim actually supported by the passage it cites?

`chat.sanitize_citations` only removes [n] markers that point at no source. This module
goes one step further and checks the *content*: it splits an answer into sentences
(claims), finds the [n] markers attached to each, and scores how well the cited
passage(s) support that sentence.

The scoring is lexical and deliberately cheap (pure Python, no model, a few ms per
answer):

* weighted content-word coverage of the claim by the best 1–3 sentence window of the
  source, blended with coverage by the whole source (stems, light fuzzy matching);
* numbers are checked separately and strictly: a number, dose, duration, temperature or
  year that is in the claim but not in the source is the classic hallucination, so a
  missing number caps the verdict ("Take 1000 mg" vs a source that says 500 mg);
* names (capitalised runs: people, places, drugs) must appear in the source too, so a
  swapped name is caught even when every other word matches;
* a polarity check catches "apply butter" cited to "do not apply butter";
* an optional embedding hook (any callable that turns texts into vectors, e.g. Mimi's
  bge-m3 server) can rescue honest paraphrases that share few words with the source.
  Embeddings never override the number/name checks; they are blind to "5 mg" vs "50 mg".

It is a proxy, not a proof: lexical overlap can't follow multi-step reasoning or
synonyms it doesn't know. Treat "unsupported" as "a human (or a judge model) should
look", and "supported" as "nothing obviously wrong". See docs/EVALUATION.md.

Intended chat.py integration (not wired yet)
--------------------------------------------
After generation, `ChatService.send` already has the final answer and `state.sources`.
The full passage text the model read lives only in the tool result (`ToolResult.text`,
blocks of "[n] Title — Book\\n<passage>"); sources keep a 240-char `snippet`. To wire this:

1. In `tools.search_library` / `read_article`, keep the passage per source number on the
   turn, e.g. `st.passages[n] = p.text` (a new `TurnState.passages: dict[int, str]`; not
   persisted, so the database doesn't grow).
2. After `answer = sanitize_citations(...)`:

       report = grounding.check_answer(answer, state.passages)          # ~ms, sync
       # or, to use the bge-m3 server when it is already running:
       # report = await grounding.check_answer_async(answer, state.passages, embed=svc.models.embed)
       meta["grounding"] = report.summary()
       flags = report.flags()       # only weak/unsupported/invalid citations
       if flags:
           yield {"event": "grounding", "data": {"flags": flags}}

3. The UI marks the flagged [n] chips (e.g. a dotted underline with "This source may not
   say this — check it"), using each flag's `start`/`end` offsets into the answer text.

Keep it advisory: never rewrite or drop the answer based on this score.
"""

from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Awaitable, Callable, Iterable, Mapping, Sequence

__all__ = [
    "Thresholds", "Claim", "CitationCheck", "ClaimResult", "GroundingReport",
    "split_claims", "is_factual", "extract_numbers", "extract_entities", "support",
    "check_answer", "check_answer_async",
]

SUPPORTED, WEAK, UNSUPPORTED, INVALID = "supported", "weak", "unsupported", "invalid"
MAX_SOURCE_CHARS = 60_000

EmbedFn = Callable[[list[str]], Any]                # texts -> sequence of vectors
AsyncEmbedFn = Callable[[list[str]], Awaitable[Any]]


@dataclass(frozen=True)
class Thresholds:
    supported: float = 0.5        # score at or above: supported (if no red flags)
    weak: float = 0.25            # score below: unsupported
    window_weight: float = 0.7    # lexical = w * best window coverage + (1 - w) * whole-source coverage
    number_penalty: float = 0.35  # multiplier per missing number
    entity_penalty: float = 0.6   # multiplier per missing name
    polarity_penalty: float = 0.6
    emb_floor: float = 0.45       # cosine at/below which an embedding says "unrelated" (bge-m3 scale)
    emb_ceiling: float = 0.85     # cosine at/above which it says "same meaning"


DEFAULT = Thresholds()

# --------------------------------------------------------------------------- vocabulary
STOPWORDS = set(
    "a about above after again against all also am an and any are as at be because been before being below between both but by "
    "can could did do does doing down during each else few for from further had has have having he her here hers herself him "
    "himself his how however i if in into is it its itself just let me more most my myself nor of off on once only or other "
    "our ours ourselves out over own same she should so some such than that the their theirs them themselves then there these "
    "they this those through thus to too under until up upon very via was we were what when where which while who whom whose "
    "why will with within would you your yours yourself yourselves etc eg ie may might must shall one ones".split()
)
# Words so common in answers that matching them says little.
GENERIC = set(
    "use used using make made take taken get keep help helps important common commonly usually often typically generally "
    "include includes including called known well like many much several various different way ways thing things part "
    "need needs needed time times good best better new first also especially particularly certain".split()
)
NEGATIONS = re.compile(r"\b(not|no|never|none|nothing|neither|nor|without|avoid|avoiding|don'?t|doesn'?t|didn'?t|isn'?t|aren'?t|"
                       r"wasn'?t|weren'?t|shouldn'?t|can'?t|cannot|won'?t|mustn'?t|instead of|rather than)\b", re.I)
_RESTRICT = re.compile(r"\b(only|unless|except|no|not|never|without|nor|none)\b|n't\b", re.I)
_GENERIC_ENTITY = {"mount", "mt", "river", "lake", "saint", "st", "north", "south", "east", "west", "new", "university",
                   "dr", "mr", "mrs", "ms", "sir", "king", "queen", "national", "park", "the"}
_ABBREV = re.compile(r"\b(e\.g|i\.e|etc|vs|approx|dr|mr|mrs|ms|st|mt|no|fig|ca|u\.s|u\.k|a\.m|p\.m|jr|sr)\.", re.I)
_CITE = re.compile(r"\[(\d+(?:\s*,\s*\d+)*)\]")
_CITE_ANY = re.compile(r"\s*\[\d+(?:\s*,\s*\d+)*\]")
_SENT_END = re.compile(r"[.!?]+[\"”’')]*((?:\s*\[\d+(?:\s*,\s*\d+)*\])*)(?=\s+[^a-z\s]|\s*$)")

_NUM_WORDS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
    "nineteen": 19, "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80,
    "ninety": 90, "hundred": 100, "dozen": 12,
}
# Unit -> (category, factor to the category's base unit)
_UNITS: dict[str, tuple[str, float]] = {
    "mcg": ("mass", 0.001), "µg": ("mass", 0.001), "μg": ("mass", 0.001), "ug": ("mass", 0.001), "mg": ("mass", 1.0),
    "g": ("mass", 1000.0), "gram": ("mass", 1000.0), "grams": ("mass", 1000.0), "kg": ("mass", 1e6),
    "ml": ("volume", 1.0), "l": ("volume", 1000.0), "liter": ("volume", 1000.0), "liters": ("volume", 1000.0),
    "litre": ("volume", 1000.0), "litres": ("volume", 1000.0),
    "iu": ("dose", 1.0), "unit": ("dose", 1.0), "units": ("dose", 1.0),
    "%": ("percent", 1.0), "percent": ("percent", 1.0),
    "°c": ("temp_c", 1.0), "°f": ("temp_f", 1.0), "c": ("temp_c", 1.0), "f": ("temp_f", 1.0),
    "degrees": ("temp", 1.0), "degree": ("temp", 1.0),
    "mm": ("length", 0.1), "cm": ("length", 1.0), "m": ("length", 100.0), "km": ("length", 1e5),
    "in": ("inch", 1.0), "inch": ("inch", 1.0), "inches": ("inch", 1.0), "ft": ("feet", 1.0), "feet": ("feet", 1.0),
    "mi": ("mile", 1.0), "mile": ("mile", 1.0), "miles": ("mile", 1.0),
    "lb": ("pound", 1.0), "lbs": ("pound", 1.0), "pound": ("pound", 1.0), "pounds": ("pound", 1.0), "oz": ("ounce", 1.0),
    "s": ("time", 1.0), "sec": ("time", 1.0), "secs": ("time", 1.0), "second": ("time", 1.0), "seconds": ("time", 1.0),
    "min": ("time", 60.0), "mins": ("time", 60.0), "minute": ("time", 60.0), "minutes": ("time", 60.0),
    "h": ("time", 3600.0), "hr": ("time", 3600.0), "hrs": ("time", 3600.0), "hour": ("time", 3600.0), "hours": ("time", 3600.0),
    "day": ("time", 86400.0), "days": ("time", 86400.0), "week": ("time", 604800.0), "weeks": ("time", 604800.0),
    "month": ("time", 2.6298e6), "months": ("time", 2.6298e6), "year": ("time", 3.15576e7), "years": ("time", 3.15576e7),
    "times": ("count", 1.0),
}
_CRITICAL = {"mass", "volume", "dose", "percent", "temp_c", "temp_f", "temp"}  # a wrong one of these can hurt someone
_UNIT_RE = "|".join(sorted((re.escape(u) for u in _UNITS), key=len, reverse=True))
_NUM_RE = re.compile(
    r"(?<![\w.])(\d{1,3}(?:,\d{3})+(?!\d)|\d+(?:\.\d+)?)"
    r"(?:\s?(" + _UNIT_RE + r")(?![\w]))?", re.I)
_RANGE_RE = re.compile(r"^\s*(?:-|–|—|to|or|and)\s*$", re.I)


# --------------------------------------------------------------------------- data
@dataclass
class Claim:
    """One sentence of an answer, with the [n] markers attached to it."""
    index: int
    text: str                 # cleaned: no markdown, no [n]
    raw: str                  # as written in the answer
    start: int                # offsets of `raw` in the answer
    end: int
    citations: list[int]
    block: int                # paragraph / list item it belongs to
    factual: bool


@dataclass
class CitationCheck:
    n: int
    score: float
    verdict: str
    lexical: float = 0.0
    embedding: float | None = None
    missing_numbers: list[str] = field(default_factory=list)
    missing_entities: list[str] = field(default_factory=list)
    polarity_mismatch: bool = False
    evidence: str = ""        # the best-matching source window (trimmed)
    better_source: int | None = None

    @property
    def reasons(self) -> list[str]:
        out = []
        if self.verdict == INVALID:
            return ["citation points to no source"]
        if self.missing_numbers:
            out.append("number not in source: " + ", ".join(self.missing_numbers))
        if self.missing_entities:
            out.append("name not in source: " + ", ".join(self.missing_entities))
        if self.polarity_mismatch:
            out.append("source says the opposite (negation mismatch)")
        if self.verdict != SUPPORTED and not out:
            out.append("little overlap with the cited passage")
        if self.better_source:
            out.append(f"[{self.better_source}] supports this better")
        return out


@dataclass
class ClaimResult:
    claim: Claim
    checks: list[CitationCheck]
    verdict: str | None       # best verdict over its citations; None when uncited
    score: float              # 0..1 contribution to faithfulness
    covered_by: list[int] = field(default_factory=list)  # paragraph-level citations that support an uncited sentence


@dataclass
class GroundingReport:
    claims: list[ClaimResult]
    n_sources: int

    # ---- aggregate views
    @property
    def checks(self) -> list[tuple[Claim, CitationCheck]]:
        return [(c.claim, k) for c in self.claims for k in c.checks]

    def count(self, verdict: str) -> int:
        return sum(1 for _, k in self.checks if k.verdict == verdict)

    @property
    def factual(self) -> list[ClaimResult]:
        return [c for c in self.claims if c.claim.factual]

    @property
    def uncited_factual(self) -> list[Claim]:
        return [c.claim for c in self.factual if not c.claim.citations and not c.covered_by]

    @property
    def faithfulness(self) -> float | None:
        """Mean support over factual sentences (supported 1, weak ½, unsupported/uncited 0)."""
        f = self.factual
        return round(sum(c.score for c in f) / len(f), 4) if f else None

    @property
    def citation_precision(self) -> float | None:
        ks = [k for _, k in self.checks]
        return round(sum(k.verdict == SUPPORTED for k in ks) / len(ks), 4) if ks else None

    @property
    def coverage(self) -> float | None:
        f = self.factual
        return round(sum(bool(c.claim.citations or c.covered_by) for c in f) / len(f), 4) if f else None

    def summary(self) -> dict:
        """Small JSON-able digest, suitable for message meta."""
        return {
            "faithfulness": self.faithfulness, "citation_precision": self.citation_precision, "coverage": self.coverage,
            "citations": len(self.checks), "supported": self.count(SUPPORTED), "weak": self.count(WEAK),
            "unsupported": self.count(UNSUPPORTED), "invalid": self.count(INVALID),
            "factual_sentences": len(self.factual), "uncited_factual": len(self.uncited_factual),
        }

    def flags(self) -> list[dict]:
        """One entry per citation that the UI should mark (weak, unsupported or invalid)."""
        out = []
        for claim, k in self.checks:
            if k.verdict == SUPPORTED:
                continue
            out.append({"n": k.n, "verdict": k.verdict, "score": round(k.score, 3), "sentence": claim.text,
                        "start": claim.start, "end": claim.end, "reasons": k.reasons, "better_source": k.better_source})
        return out

    def ui_flags(self) -> list[dict]:
        """The citations worth interrupting a reader for: high precision, low noise.

        `flags()` lists everything short of "supported", which suits the eval scoreboard.
        A warning in the chat has to be right nearly every time or people learn to ignore it,
        so this keeps only citations that are unsupported or invalid (a missing number or
        name, a contradiction, or no real overlap), and skips any claim that another of its
        citations does support ("… [1][2]" where [1] carries it). "Weak" usually means an
        honest paraphrase that shares few words with the source.
        """
        out = []
        for c in self.claims:
            if c.verdict == SUPPORTED:
                continue
            for k in c.checks:
                if k.verdict in (UNSUPPORTED, INVALID):
                    out.append({"n": k.n, "verdict": k.verdict, "score": round(k.score, 3), "sentence": c.claim.text,
                                "start": c.claim.start, "end": c.claim.end, "reasons": k.reasons, "better_source": k.better_source})
        return out

    def to_dict(self) -> dict:
        d = self.summary()
        d["claims"] = []
        for c in self.claims:
            cd = asdict(c.claim)
            cd.update(verdict=c.verdict, score=round(c.score, 4), covered_by=c.covered_by,
                      checks=[{**asdict(k), "score": round(k.score, 4), "lexical": round(k.lexical, 4), "reasons": k.reasons}
                              for k in c.checks])
            d["claims"].append(cd)
        d["uncited_factual"] = [c.text for c in self.uncited_factual]
        return d


# --------------------------------------------------------------------------- text helpers
def _strip_markdown(s: str) -> str:
    s = re.sub(r"!?\[([^\]]+)\]\((?:[^)]+)\)", r"\1", s)          # links / images
    s = re.sub(r"^\s{0,3}(#{1,6}\s+|>\s?|[-*+•]\s+|\d{1,2}[.)]\s+)", "", s)  # heading, quote, bullet, list number
    s = re.sub(r"(\*\*|__|\*|_|`)(?=\S)(.+?)(?<=\S)\1", r"\2", s)
    return s.replace("**", "").replace("`", "")


def _clean_claim(raw: str) -> str:
    s = _CITE_ANY.sub("", raw)
    s = _strip_markdown(s.strip())
    s = re.sub(r"\s+([.,;:!?])", r"\1", s)
    return re.sub(r"\s+", " ", s).strip()


def _protect(s: str) -> str:
    # Keep offsets stable: replace the dot of an abbreviation with a same-length placeholder.
    return _ABBREV.sub(lambda m: m.group(0)[:-1] + "\x00", s)


def _sentence_spans(text: str) -> list[tuple[int, int]]:
    """Sentence spans within one block; trailing [n] markers stay with their sentence."""
    prot = _protect(text)
    spans, start = [], 0
    for m in _SENT_END.finditer(prot):
        end = m.end()
        if text[start:end].strip():
            spans.append((start, end))
        start = end
    if text[start:].strip():
        spans.append((start, len(text)))
    out = []
    for a, b in spans:  # trim whitespace
        while a < b and text[a].isspace():
            a += 1
        while b > a and text[b - 1].isspace():
            b -= 1
        out.append((a, b))
    return out


def _blocks(answer: str) -> list[tuple[int, int]]:
    """Paragraphs and list items, as spans. A list item or heading is its own block."""
    out, start, pos = [], None, 0
    for line in answer.splitlines(keepends=True):
        stripped = line.strip()
        item = re.match(r"\s{0,3}([-*+•]|\d{1,2}[.)]|#{1,6})\s", line) is not None
        if not stripped or item:
            if start is not None:
                out.append((start, pos))
                start = None
        if stripped:
            if item:
                out.append((pos, pos + len(line.rstrip("\r\n"))))
            elif start is None:
                start = pos
        pos += len(line)
    if start is not None:
        out.append((start, pos))
    return out


_META = re.compile(
    r"^(i\b|i'm|i’m|i've|i’ve|i'd|let me|let's|here's|here is|here are|sure\b|okay\b|ok\b|great question|good question|hope|"
    r"feel free|would you like|do you want|if you('d| would) like|if you want me|let me know|stay safe|good luck|take care|"
    r"in summary|to summari[sz]e|sources?:|references?:|note:?$|disclaimer:?$)", re.I)


def is_factual(sentence: str) -> bool:
    """Heuristic: does this sentence assert something checkable about the world?

    Questions, headings, greetings and statements about Mimi itself ("I couldn't find…",
    "Let me know…") are not; anything with a number or a name, or three or more content
    words, is.
    """
    s = _clean_claim(sentence)
    if not s or s.endswith("?") or s.endswith(":") or _META.match(s):
        return False
    if extract_numbers(s, for_claim=True) or extract_entities(s):
        return True
    return len([t for t in _words(s) if t not in STOPWORDS]) >= 3


def split_claims(answer: str) -> list[Claim]:
    """Split an answer into sentences with their [n] citations and character offsets."""
    claims: list[Claim] = []
    for bi, (b0, b1) in enumerate(_blocks(answer or "")):
        block = answer[b0:b1]
        for a, b in _sentence_spans(block):
            raw = block[a:b]
            text = _clean_claim(raw)
            if not text and not _CITE.search(raw):
                continue
            cites: list[int] = []
            for m in _CITE.finditer(raw):
                for x in m.group(1).split(","):
                    n = int(x)
                    if n not in cites:
                        cites.append(n)
            if not text and claims and claims[-1].block == bi:  # a bare "[2]" after a sentence: give it to that sentence
                claims[-1].citations += [n for n in cites if n not in claims[-1].citations]
                continue
            claims.append(Claim(index=len(claims), text=text, raw=raw, start=b0 + a, end=b0 + b, citations=cites,
                                block=bi, factual=is_factual(text)))
    return claims


# --------------------------------------------------------------------------- tokens, numbers, names
_WORD = re.compile(r"[a-z][a-z'’]*")


def _words(s: str) -> list[str]:
    return [w.replace("’", "'").removesuffix("'s").strip("'") for w in _WORD.findall(s.lower())]


_SUFFIXES = ("ational", "ization", "ations", "ation", "nesses", "ments", "ment", "ness", "ingly", "edly", "ings", "ing",
             "ies", "ied", "ed", "es", "ly", "s")


def _stem(w: str) -> str:
    for suf in _SUFFIXES:
        if w.endswith(suf) and len(w) - len(suf) >= 3:
            w = w[: -len(suf)] + ("y" if suf in ("ies", "ied") else "")
            break
    if len(w) > 4 and w.endswith("e"):
        w = w[:-1]
    return w


def _content(s: str) -> list[str]:
    return [_stem(w) for w in _words(s) if w not in STOPWORDS and len(w) > 1 and w not in _NUM_WORDS]


def _similar(a: str, b: str) -> bool:
    """Same stem, or a long shared prefix ("immersion" ~ "immerse", not "hypothermia" ~ "hypothalamus")."""
    if a == b:
        return True
    if len(a) < 5 or len(b) < 5:
        return False
    p = 0
    for x, y in zip(a, b):
        if x != y:
            break
        p += 1
    return p >= max(5, min(len(a), len(b)) - 2)


def _index(stems: Iterable[str]) -> dict[str, set[str]]:
    idx: dict[str, set[str]] = {}
    for s in stems:
        idx.setdefault(s[:4], set()).add(s)
    return idx


def _words_to_digits(s: str, for_claim: bool) -> str:
    def rep(m: re.Match) -> str:
        w = m.group(0).lower()
        parts = re.split(r"[-\s]", w)
        if for_claim and w in ("one", "hundred", "dozen"):  # "one of the…" is rarely a factual number
            return m.group(0)
        if len(parts) == 2 and parts[0] in _NUM_WORDS and parts[1] in _NUM_WORDS and _NUM_WORDS[parts[0]] >= 20:
            return str(_NUM_WORDS[parts[0]] + _NUM_WORDS[parts[1]])
        return str(_NUM_WORDS.get(parts[0], w)) if len(parts) == 1 else m.group(0)

    names = "|".join(_NUM_WORDS)
    return re.sub(rf"\b(?:{names})(?:[-\s](?:{names}))?\b", rep, s, flags=re.I)


@dataclass(frozen=True)
class Num:
    text: str
    value: float
    unit: str | None          # normalised unit key
    category: str | None

    @property
    def base(self) -> float:
        return self.value * (_UNITS[self.unit][1] if self.unit else 1.0)

    @property
    def critical(self) -> bool:
        return self.category in _CRITICAL


def extract_numbers(s: str, for_claim: bool = False) -> list[Num]:
    """Numbers with their units ("500 mg", "20 minutes", "1953", "37 °C"). Ranges share the trailing unit."""
    s = _CITE_ANY.sub(" ", s)
    s = re.sub(r"(\d)\s*°\s*([cf])\b", r"\1 °\2", s, flags=re.I)
    s = _words_to_digits(s, for_claim)
    found: list[tuple[int, int, Num]] = []
    for m in _NUM_RE.finditer(s):
        raw = m.group(1)
        try:
            v = float(raw.replace(",", ""))
        except ValueError:
            continue
        unit = (m.group(2) or "").lower() or None
        if unit in ("in", "m", "s", "c", "f", "l", "h") and not re.match(r"\s?" + re.escape(m.group(2)) + r"\b", s[m.end(1):]):
            unit = None
        if unit in ("c", "f") and "°" not in s[m.end(1):m.end()]:
            unit = None  # a bare "c"/"f" after a number is too ambiguous
        if unit == "in" and re.match(r"\s?in\s+(the|a|an|my|your|this|that|each|every|\d)", s[m.end(1):], re.I):
            unit = None  # "20 in the morning"
        cat = _UNITS[unit][0] if unit else None
        found.append((m.start(), m.end(), Num(m.group(0).strip(), v, unit, cat)))
    # propagate a unit backwards over a range: "100 to 120 per minute", "2–3 days"
    for i in range(len(found) - 2, -1, -1):
        a0, a1, a = found[i]
        b0, b1, b = found[i + 1]
        if a.unit is None and b.unit and _RANGE_RE.match(s[a1:b0]):
            found[i] = (a0, a1, Num(a.text, a.value, b.unit, b.category))
    return [n for _, _, n in found]


def _num_in(n: Num, pool: list[Num]) -> bool:
    for p in pool:
        if n.unit and p.unit and n.category == p.category:
            if math.isclose(n.base, p.base, rel_tol=1e-6):
                return True
        elif math.isclose(n.value, p.value, rel_tol=1e-9):
            if n.unit and p.unit and n.category != p.category:
                continue  # 5 mg is not 5 ml
            return True
    return False


_CAP = re.compile(r"\b(?:[A-Z][\w'’.-]*[A-Za-z0-9]|[A-Z])\b")


def extract_entities(s: str) -> list[str]:
    """Capitalised runs that look like names ("Edmund Hillary", "Mount Everest", "CPR").

    A single capitalised word at the start of the sentence is ignored (it is just the
    first word), unless it is an acronym.
    """
    s = _clean_claim(s)
    tokens = list(re.finditer(r"[A-Za-z][\w'’.-]*[A-Za-z0-9]|[A-Za-z]", s))
    runs: list[list[tuple[int, str]]] = []
    cur: list[tuple[int, str]] = []
    starts = {0}  # token indexes that open a sentence (a claim can hold two: "**Don't rub.** Rough handling…")
    for i, m in enumerate(tokens):
        w = m.group(0).rstrip(".")
        if i > 0:
            prev = tokens[i - 1].group(0)
            gap = s[tokens[i - 1].end():m.start()]
            if re.search(r"[!?]", gap) or ("." in gap + prev[-1:] and len(prev.rstrip(".")) > 3):
                starts.add(i)
        if cur and i > 0:  # punctuation, or a full stop after a non-abbreviation, ends a name
            if re.search(r"[;:!?()\"“”]", gap) or ("." in gap + prev[-1:] and len(prev.rstrip(".")) > 3):
                runs.append(cur)
                cur = []
        if w[0].isupper():
            cur.append((i, w))
        elif cur and w.lower() in ("of", "de", "von", "van", "da", "del", "la", "le") and i + 1 < len(tokens) and tokens[i + 1].group(0)[0].isupper():
            cur.append((i, w))
        else:
            if cur:
                runs.append(cur)
            cur = []
    if cur:
        runs.append(cur)
    out = []
    for run in runs:
        # the sentence's first word is capitalised anyway; drop it unless it's an acronym
        if run[0][0] in starts and not (len(run[0][1]) >= 2 and run[0][1].isupper()):
            run = run[1:]
        while run and run[0][1].lower() in STOPWORDS:
            run = run[1:]
        if not run:
            continue
        name = " ".join(w for _, w in run)
        if len(name) >= 2 and name.lower() not in STOPWORDS:
            out.append(name)
    return out


# --------------------------------------------------------------------------- sources
@dataclass
class _Source:
    n: int
    text: str
    windows: list[str]
    win_stems: list[set[str]]
    win_span: list[tuple[int, int]]   # (first sentence, number of sentences)
    sents: list[str]
    sent_stems: list[set[str]]
    all_stems: set[str]
    index: dict[str, set[str]]
    words: set[str]
    numbers: list[Num]


def _split_sentences(text: str) -> list[str]:
    prot = _protect(text)
    parts = re.split(r"(?<=[.!?])[\"”’')]*\s+|\n+", prot)
    return [p.replace("\x00", ".").strip() for p in parts if p and p.strip()][:3000]


def _prepare(n: int, text: str) -> _Source:
    text = (text or "")[:MAX_SOURCE_CHARS]
    sents = _split_sentences(text)
    windows, stems, spans = [], [], []
    sent_stems = [set(_content(x)) for x in sents]
    for size in (1, 2, 3):  # single sentences first, so ties go to the tightest window
        for i in range(0, max(0, len(sents) - size + 1)):
            windows.append(" ".join(sents[i:i + size]))
            stems.append(set().union(*sent_stems[i:i + size]))
            spans.append((i, size))
    all_stems = set().union(*sent_stems) if sent_stems else set()
    return _Source(n=n, text=text, windows=windows, win_stems=stems, win_span=spans, sents=sents, sent_stems=sent_stems, all_stems=all_stems,
                   index=_index(all_stems), words={_stem(w) for w in _words(text)} | set(_words(text)),
                   numbers=extract_numbers(text))


def _normalise_sources(sources: Any) -> dict[int, str]:
    if not sources:
        return {}
    if isinstance(sources, Mapping):
        return {int(k): (v if isinstance(v, str) else _source_text(v)) for k, v in sources.items()}
    out = {}
    for i, s in enumerate(sources):
        if isinstance(s, str):
            out[i + 1] = s
        else:
            out[int(s.get("n") or i + 1)] = _source_text(s)
    return out


def _source_text(s: Any) -> str:
    if isinstance(s, str):
        return s
    if not isinstance(s, Mapping):
        return ""
    body = s.get("text") or s.get("passage") or s.get("content") or s.get("snippet") or ""
    title = s.get("title") or ""
    return f"{title}. {body}" if title and title not in body[:200] else body


# --------------------------------------------------------------------------- scoring
def _coverage(claim: list[str], matched: dict[str, set[str]], stems: set[str]) -> float:
    """Weighted share of claim words present in `stems` (via their precomputed exact/fuzzy matches)."""
    tot = got = 0.0
    for t in claim:
        w = 0.4 if t in GENERIC else 1.0
        tot += w
        if matched[t] & stems:
            got += w
    return got / tot if tot else 0.0


def _neg_targets(text: str) -> set[str]:
    """Stems of the content words a negation applies to: "do not use ice or butter" -> {"ice", "butter"}."""
    out: set[str] = set()
    for m in NEGATIONS.finditer(text):
        # The scope runs to the end of the clause: a list ("ice, iced water, butter or creams") stays
        # in it, a prepositional tail ("not ice, for 20 minutes") or a new clause doesn't.
        scope = re.split(r"[;:.!?()]|\b(?:but|then|because|so|which|while|for|to|with|in|on|at|by|from|until|unless|except|after|before|during|if|when)\b",
                         text[m.end():], maxsplit=1)[0]
        if "," not in scope:
            scope = re.split(r"\band\b", scope, maxsplit=1)[0]
        out.update(t for t in _content(scope)[:6] if t not in GENERIC)
    return out


def _support_lexical(claim_text: str, src: _Source, th: Thresholds) -> tuple[float, int, list[str], list[str], bool]:
    """(lexical score, best window index, missing numbers, missing names, polarity mismatch)."""
    toks = _content(claim_text)
    lexical, best_i = 0.0, -1
    matched: dict[str, set[str]] = {}
    if toks and src.windows:
        for t in set(toks):
            cands = src.index.get(t[:4], set())
            matched[t] = {c for c in cands if _similar(t, c)}
        best = 0.0
        for i, ws in enumerate(src.win_stems):
            c = _coverage(toks, matched, ws)
            if c > best + 1e-9:
                best, best_i = c, i
        whole = _coverage(toks, matched, src.all_stems)
        lexical = th.window_weight * best + (1 - th.window_weight) * whole
    missing_nums = [n.text for n in extract_numbers(claim_text, for_claim=True) if not _num_in(n, src.numbers)]
    missing_ents = []
    for e in extract_entities(claim_text):
        parts = [p for p in re.split(r"[\s-]+", e.lower().rstrip(".")) if p and p not in STOPWORDS]
        key = [p for p in parts if p not in _GENERIC_ENTITY] or parts
        if not all(p.removesuffix("'s") in src.words or _stem(p) in src.words for p in key):
            missing_ents.append(e)
    polarity = False
    if best_i >= 0 and lexical >= th.weak:
        # Negation is checked sentence by sentence inside the best window, where it is local enough to mean something.
        first, size = src.win_span[best_i]
        c_neg = _neg_targets(claim_text)
        s_neg = set().union(*(_neg_targets(src.sents[j]) for j in range(first, first + size)))
        span_stems = src.win_stems[best_i]
        asserted = {t for t in toks if t not in c_neg and t not in GENERIC}
        # the source negates something the claim asserts ("do not apply butter" vs "apply butter") …
        if any(matched[t] & s_neg for t in asserted):
            polarity = True
        # … or the claim negates something the source asserts plainly. A source sentence with any
        # restriction in it ("only an expert can…", "unless…") is too subtle for this check.
        elif not any(_RESTRICT.search(src.sents[j]) for j in range(first, first + size)) and \
                any(matched.get(t, set()) & span_stems for t in c_neg):
            polarity = True
    return lexical, best_i, missing_nums, missing_ents, polarity


def _emb_scale(cos: float, th: Thresholds) -> float:
    return max(0.0, min(1.0, (cos - th.emb_floor) / max(1e-6, th.emb_ceiling - th.emb_floor)))


def _verdict(score: float, nums_total: int, missing_nums: list[str], ents: list[str], polarity: bool,
             critical_missing: bool, th: Thresholds) -> str:
    # A contradiction, an invented dose, or numbers that are mostly not in the source: unsupported
    # however many other words match.
    if score < th.weak or polarity or critical_missing or (missing_nums and len(missing_nums) * 2 >= max(1, nums_total)):
        return UNSUPPORTED
    if score >= th.supported and not missing_nums and not ents and not polarity:
        return SUPPORTED
    return WEAK


def _check(claim_text: str, src: _Source | None, n: int, th: Thresholds, emb_cos: float | None = None) -> CitationCheck:
    if src is None:
        return CitationCheck(n=n, score=0.0, verdict=INVALID)
    lexical, wi, mnums, ments, polarity = _support_lexical(claim_text, src, th)
    emb = _emb_scale(emb_cos, th) if emb_cos is not None else None
    base = max(lexical, (lexical + emb) / 2) if emb is not None else lexical
    claim_nums = extract_numbers(claim_text, for_claim=True)
    critical = any(not _num_in(x, src.numbers) and x.critical for x in claim_nums)
    score = base * (th.number_penalty ** len(mnums)) * (th.entity_penalty ** len(ments)) * (th.polarity_penalty if polarity else 1.0)
    verdict = _verdict(score, len(claim_nums), mnums, ments, polarity, critical, th)
    evidence = src.windows[wi][:300] if wi >= 0 else ""
    return CitationCheck(n=n, score=round(score, 4), verdict=verdict, lexical=round(lexical, 4), embedding=None if emb is None else round(emb, 4),
                         missing_numbers=mnums, missing_entities=ments, polarity_mismatch=polarity, evidence=evidence)


def support(claim: str, passage: str, *, thresholds: Thresholds = DEFAULT, embedding_cosine: float | None = None) -> CitationCheck:
    """Score one claim against one passage (n=1). Handy for tests and ad-hoc checks."""
    return _check(_clean_claim(claim), _prepare(1, passage), 1, thresholds, embedding_cosine)


_VALUE = {SUPPORTED: 1.0, WEAK: 0.5, UNSUPPORTED: 0.0, INVALID: 0.0}
_RANK = {SUPPORTED: 3, WEAK: 2, UNSUPPORTED: 1, INVALID: 0}


class _Run:
    """Lexical pass over an answer; embeddings (if any) are filled in afterwards."""

    def __init__(self, answer: str, sources: Any, th: Thresholds):
        self.th = th
        self.claims = split_claims(answer)
        self.srcs = {n: _prepare(n, t) for n, t in _normalise_sources(sources).items()}
        # (claim index, source n) pairs we score; uncited factual claims are scored against their paragraph's citations
        self.pairs: list[tuple[int, int]] = []
        for c in self.claims:
            for n in c.citations:
                self.pairs.append((c.index, n))
        self.context: dict[int, list[int]] = {}
        for c in self.claims:
            if c.factual and not c.citations:
                ctx = []
                for o in self.claims:
                    if o.block == c.block:
                        ctx += [n for n in o.citations if n not in ctx]
                self.context[c.index] = ctx
                for n in ctx:
                    self.pairs.append((c.index, n))

    def embed_texts(self) -> list[str]:
        texts: list[str] = []
        for ci, n in self.pairs:
            src = self.srcs.get(n)
            if src is None:
                continue
            _, wi, *_ = _support_lexical(self.claims[ci].text, src, self.th)
            texts += [self.claims[ci].text, src.windows[wi] if wi >= 0 else src.text[:1500]]
        return list(dict.fromkeys(texts))

    def finish(self, cos: Callable[[str, str], float] | None = None) -> GroundingReport:
        th = self.th
        results: list[ClaimResult] = []

        def check(c: Claim, n: int) -> CitationCheck:
            src = self.srcs.get(n)
            e = None
            if cos is not None and src is not None:
                _, wi, *_ = _support_lexical(c.text, src, th)
                e = cos(c.text, src.windows[wi] if wi >= 0 else src.text[:1500])
            return _check(c.text, src, n, th, e)

        for c in self.claims:
            checks = [check(c, n) for n in c.citations]
            for k in checks:  # a citation that fails: does another source in this answer say it?
                if k.verdict in (WEAK, UNSUPPORTED):
                    alts = [check(c, m) for m in self.srcs if m != k.n]
                    good = [a for a in alts if a.verdict == SUPPORTED]
                    if good:
                        k.better_source = max(good, key=lambda a: a.score).n
            if checks:
                best = max(checks, key=lambda k: (_RANK[k.verdict], k.score))
                results.append(ClaimResult(c, checks, best.verdict, _VALUE[best.verdict] if c.factual else 0.0))
                continue
            covered: list[int] = []
            value = 0.0
            for n in self.context.get(c.index, []):
                k = check(c, n)
                if k.verdict in (SUPPORTED, WEAK):
                    covered.append(n)
                    value = max(value, _VALUE[k.verdict])
            results.append(ClaimResult(c, [], None, value, covered))
        return GroundingReport(results, len(self.srcs))


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return dot / (na * nb)


def _cos_lookup(texts: list[str], vecs: Any) -> Callable[[str, str], float]:
    table = {t: [float(x) for x in v] for t, v in zip(texts, vecs)}

    def cos(a: str, b: str) -> float:
        va, vb = table.get(a), table.get(b)
        return _cosine(va, vb) if va is not None and vb is not None else 0.0

    return cos


def check_answer(answer: str, sources: Any, *, embed: EmbedFn | None = None, thresholds: Thresholds = DEFAULT) -> GroundingReport:
    """Check every [n] citation in `answer` against the text of source n.

    `sources` may be a mapping {n: passage text}, a list of Mimi source dicts (with "n" and
    "text"/"passage"/"snippet"), or a plain list of passage strings numbered from 1.
    `embed`, if given, is called once with a list of texts and must return one vector per
    text (e.g. a sync wrapper around bge-m3). Pure and fast without it.
    """
    run = _Run(answer, sources, thresholds)
    if embed is None:
        return run.finish()
    texts = run.embed_texts()
    return run.finish(_cos_lookup(texts, embed(texts)) if texts else None)


async def check_answer_async(answer: str, sources: Any, *, embed: AsyncEmbedFn | None = None,
                             thresholds: Thresholds = DEFAULT) -> GroundingReport:
    """Same as `check_answer`, with an async embedder such as `svc.models.embed`.

    If the embedder fails (server not running, out of memory) the lexical report is
    returned instead; grounding must never break a chat turn.
    """
    run = _Run(answer, sources, thresholds)
    if embed is None:
        return run.finish()
    texts = run.embed_texts()
    if not texts:
        return run.finish()
    try:
        vecs = await embed(texts)
    except Exception:
        return run.finish()
    return run.finish(_cos_lookup(texts, vecs))
