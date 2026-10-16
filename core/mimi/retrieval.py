"""Library ranking: pure functions, no I/O (unit-tested with fakes).

The library is many books searched at once: kiwix-serve's Xapian index per
language group, our own FTS5 index of PDF pages (libindex.py) and a title
lookup. Their raw scores aren't comparable, so we fuse *ranks*:

    score(item) = prior(collection | intent) × Σ_lists  w_list / (K + rank)

* **Reciprocal-rank fusion** (RRF, Cormack et al. 2009) only needs each list's
  order, so a Stack Exchange answer ranked 1st can't drown a WikiMed article
  ranked 1st just because Xapian's scores for short posts run higher. Results
  of one multi-book Xapian query are split per book first, so every book's
  best hit competes on equal terms.
* **Intent priors** nudge collections that suit the question: "how do I stop
  bleeding" prefers Medicine (WikiMed, the medical PDFs) over Q&A; "replace a
  phone screen" prefers iFixit. Priors are multipliers in a narrow band, so a
  strong match from the "wrong" shelf still surfaces.
* **Semantic rerank** (optional) blends the fused score with the cosine
  similarity of bge-m3 embeddings of the query and each candidate's
  title + snippet. It only runs when the embedding server is already up.
* **Passage selection** scores an article's paragraphs with BM25 over the
  query's stemmed terms (IDF across the article's own paragraphs), plus a
  bonus when the section heading matches, plus optional embedding similarity.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Hashable, Iterable, Sequence

STOPWORDS = set(
    "a an and are as at be by can do does for from how i if in into is it its me my of on or should the this to was what when where which who why will with you your".split()
)

# Smaller K makes rank differences count for more; our lists are short (≤ 20),
# so the textbook K = 60 would flatten them until the priors decided everything.
RRF_K = 10

# --------------------------------------------------------------------------- terms
_SUFFIXES = ("ations", "ation", "ions", "ion", "ingly", "ments", "ment", "ness", "ings", "ing", "edly", "ies", "ied", "ed", "ly")


def stem(word: str) -> str:
    """A light English stemmer: strips one common suffix, keeps ≥ 3 letters.

    bleeding/bleeds → "bleed", infections/infected → "infect", bites/biting →
    "bit", injuries/injury → "injury". Deliberately conservative: a wrong merge
    hurts ranking more than a miss. (The PDF index uses SQLite's Porter stemmer.)
    """
    w = word.lower()
    if len(w) <= 3 or w.isdigit():
        return w
    for suf in _SUFFIXES:
        if w.endswith(suf) and len(w) - len(suf) >= 3:
            if suf == "ed" and w.endswith("eed"):  # bleed, need, speed: not a past tense
                break
            base = w[: -len(suf)]
            if suf in ("ies", "ied"):
                return base + "y"
            if suf in ("ing", "ed", "edly", "ings") and len(base) >= 4 and base[-1] == base[-2] and base[-1] not in "lsz":
                base = base[:-1]  # stopping → stop, planned → plan
            w = base
            break
    else:
        if w.endswith(("ches", "shes", "xes", "zes", "sses")):
            w = w[:-2]  # matches → match, glasses → glass
        elif w.endswith("s") and not w.endswith(("ss", "us", "is")):
            w = w[:-1]  # burns → burn, but not glass, virus, tetanus, axis
    if len(w) >= 4 and w.endswith("e") and not w.endswith("ee"):
        w = w[:-1]  # cure/cured/curing → cur, bite/bites → bit
    return w


def tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def query_terms(query: str) -> list[str]:
    """Distinct stemmed content words of a query, in order."""
    out: list[str] = []
    for t in tokens(query):
        if t in STOPWORDS or len(t) < 2:
            continue
        s = stem(t)
        if s not in out:
            out.append(s)
    return out


# --------------------------------------------------------------------------- intent
@dataclass(frozen=True)
class Intent:
    name: str
    pattern: re.Pattern
    priors: dict[str, float]


def _rx(words: str) -> re.Pattern:
    return re.compile(r"\b(" + words + r")", re.I)


# Baseline priors (no intent detected): Stack Exchange is huge and its short
# posts win on keywords, so it starts slightly behind curated references.
BASE_PRIORS: dict[str, float] = {"qa": 0.85, "dictionary": 0.8}

INTENTS: list[Intent] = [
    Intent("medical", _rx(
        r"bleed|blood|wound|burn|fever|infect|fractur|broken bone|sprain|bite|sting|poison|venom|pain|ache|symptom|"
        r"diagnos|treat|medic|medicine|drug|dose|dosage|mg\b|antibiot|allerg|asthma|diabet|pregnan|birth|labou?r|"
        r"diarrh|vomit|dehydrat|cpr|first aid|injur|disease|illness|sick|rash|cough|chok|unconscious|seizure|heart attack|"
        r"stroke|shock|hypotherm|heat ?stroke|frostbite|splint|tourniquet|suture|stitch|tooth|teeth|dental|malaria|cholera"),
        {"medicine": 1.45, "survival": 1.15, "encyclopedia": 1.0, "qa": 0.55, "repair": 0.45, "travel": 0.5}),
    Intent("repair", _rx(
        r"repair|fix|broken|replac|disassembl|teardown|screen|battery|won'?t (turn|charge|start|boot)|crack|hinge|"
        r"iphone|ipad|android|laptop|macbook|console|controller|charger|charging port|zipper|faucet|leak"),
        {"repair": 1.45, "qa": 0.95, "encyclopedia": 0.8, "medicine": 0.6}),
    Intent("survival", _rx(
        r"purif|drinking water|filter water|boil water|shelter|fire ?start|tinder|knot|rope|snare|forag|edible|"
        r"food storage|canning|preserv|ration|navigat|compass|signal|rescue|disaster|earthquake|flood|hurricane|evacuat"),
        {"survival": 1.4, "medicine": 1.1, "encyclopedia": 1.0, "qa": 0.7}),
    Intent("travel", _rx(r"travel|visit|itinerar|things to do|where to stay|how to get to|sightsee|hostel|hotel|airport|visa\b"),
           {"travel": 1.45, "encyclopedia": 1.0, "qa": 0.6}),
    Intent("tech", _rx(r"linux|windows|ubuntu|terminal|command line|bash|python|javascript|error|install|compile|git\b|sql|regex|server|network|wifi|router"),
           {"qa": 1.35, "repair": 1.0, "encyclopedia": 0.9}),
    Intent("define", _rx(r"define |definition|meaning of|what does .+ mean|synonym|antonym|pronounc|etymolog"),
           {"dictionary": 1.5, "encyclopedia": 1.0}),
]


def detect_intent(query: str) -> Intent | None:
    """The first intent whose cue words appear most often in the query."""
    best, best_n = None, 0
    for it in INTENTS:
        n = len(it.pattern.findall(query))
        if n > best_n:
            best, best_n = it, n
    return best


def prior(collection: str, intent: Intent | None) -> float:
    if intent and collection in intent.priors:
        return intent.priors[collection]
    return BASE_PRIORS.get(collection, 1.0)


# --------------------------------------------------------------------------- fusion
@dataclass
class Candidate:
    """One result as seen by the ranker. `key` identifies it across lists."""
    key: Hashable
    collection: str
    book: str
    text: str = ""          # title + snippet, used for the semantic rerank
    score: float = 0.0
    sources: list[str] = field(default_factory=list)


@dataclass
class RankedList:
    name: str
    items: list[Candidate]
    weight: float = 1.0


def split_by_book(lst: RankedList) -> list[RankedList]:
    """One multi-book result list → one list per book, keeping relative order."""
    per: dict[str, list[Candidate]] = {}
    for c in lst.items:
        per.setdefault(c.book, []).append(c)
    return [RankedList(f"{lst.name}:{b}", items, lst.weight) for b, items in per.items()]


def rrf(lists: Sequence[RankedList], intent: Intent | None = None, k: int = RRF_K) -> list[Candidate]:
    """Reciprocal-rank fusion with per-collection priors. Highest score first; ties keep first-seen order."""
    merged: dict[Hashable, Candidate] = {}
    order: dict[Hashable, int] = {}
    for lst in lists:
        for rank, c in enumerate(lst.items, start=1):
            m = merged.get(c.key)
            if m is None:
                m = merged[c.key] = Candidate(c.key, c.collection, c.book, c.text)
                order[c.key] = len(order)
            elif len(c.text) > len(m.text):
                m.text = c.text
            m.score += lst.weight / (k + rank)
            m.sources.append(lst.name)
    for m in merged.values():
        m.score *= prior(m.collection, intent)
    return sorted(merged.values(), key=lambda c: (-c.score, order[c.key]))


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def _minmax(xs: list[float]) -> list[float]:
    lo, hi = min(xs), max(xs)
    if hi - lo < 1e-12:
        return [1.0 for _ in xs]
    return [(x - lo) / (hi - lo) for x in xs]


def semantic_rerank(cands: list[Candidate], qvec: Sequence[float], vecs: Sequence[Sequence[float]], alpha: float = 0.5) -> list[Candidate]:
    """Blend min-max-normalised fused scores with cosine similarity to the query.

    `vecs[i]` belongs to `cands[i]`. alpha = 0 keeps the fused order; 1 is pure
    semantic order. Scores are rewritten so callers can keep sorting by them.
    """
    if not cands or len(vecs) != len(cands):
        return cands
    fused = _minmax([c.score for c in cands])
    sims = [cosine(qvec, v) for v in vecs]
    simn = _minmax(sims)
    for c, f, s in zip(cands, fused, simn):
        c.score = (1 - alpha) * f + alpha * s
    return sorted(cands, key=lambda c: -c.score)


def cap_per_key(cands: Iterable[Candidate], group, cap: int) -> list[Candidate]:
    """Keep at most `cap` candidates per group(c) (e.g. pages of one PDF)."""
    seen: dict = {}
    out = []
    for c in cands:
        g = group(c)
        if seen.get(g, 0) >= cap:
            continue
        seen[g] = seen.get(g, 0) + 1
        out.append(c)
    return out


# --------------------------------------------------------------------------- passages
def bm25_scores(paragraphs: Sequence[str], terms: Sequence[str], k1: float = 1.2, b: float = 0.75,
                weights: dict[str, float] | None = None) -> list[float]:
    """BM25 of each paragraph against stemmed query terms.

    IDF comes from the paragraphs themselves, so a word on every line of the
    article (its own title, usually) counts for little, while the paragraph that
    alone mentions "tourniquet" stands out. Term weights let callers damp terms.
    """
    if not paragraphs or not terms:
        return [0.0] * len(paragraphs)
    docs = [[stem(t) for t in tokens(p)] for p in paragraphs]
    n = len(docs)
    avgdl = (sum(len(d) for d in docs) / n) or 1.0
    df = {t: sum(1 for d in docs if t in d) for t in terms}
    idf = {t: math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5)) for t in terms}
    w = weights or {}
    out = []
    for d in docs:
        if not d:
            out.append(0.0)
            continue
        tf: dict[str, int] = {}
        for t in d:
            tf[t] = tf.get(t, 0) + 1
        s = 0.0
        for t in terms:
            f = tf.get(t, 0)
            if f:
                s += w.get(t, 1.0) * idf[t] * f * (k1 + 1) / (f + k1 * (1 - b + b * len(d) / avgdl))
        out.append(s)
    return out


def blend_passage_scores(lexical: Sequence[float], sims: Sequence[float] | None, beta: float = 0.4) -> list[float]:
    """Lexical scores, optionally blended with embedding similarity (both min-max normalised).

    A paragraph with no query word at all keeps a zero lexical part, so a
    semantically close but off-topic paragraph needs real similarity to win.
    """
    if not lexical:
        return []
    if not sims or len(sims) != len(lexical):
        return list(lexical)
    lex = _minmax(list(lexical)) if max(lexical) > 0 else [0.0] * len(lexical)
    sim = _minmax(list(sims))
    return [(1 - beta) * l + beta * s for l, s in zip(lex, sim)]


def chunk_text(text: str, target: int = 420, hard: int = 700) -> list[str]:
    """Split running text (e.g. a PDF page) into sentence-aligned chunks of about `target` chars."""
    text = re.sub(r"-\n(?=[a-z])", "", text)        # re-join hyphenated line breaks
    text = re.sub(r"[ \t]*\n[ \t]*", "\n", text)
    paras = [re.sub(r"\s+", " ", p).strip() for p in re.split(r"\n{2,}", text)]
    out: list[str] = []
    for p in paras:
        if not p:
            continue
        sents = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9“\"(])", p)
        cur = ""
        for s in sents:
            while len(s) > hard:  # a run-on "sentence" (tables, lists): cut at a space
                cut = s[:hard].rsplit(" ", 1)[0] or s[:hard]
                if cur:
                    out.append(cur)
                    cur = ""
                out.append(cut)
                s = s[len(cut):].lstrip()
            if cur and len(cur) + 1 + len(s) > target:
                out.append(cur)
                cur = s
            else:
                cur = f"{cur} {s}".strip()
        if cur:
            out.append(cur)
    return [c for c in out if len(c) >= 25]
