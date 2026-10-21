"""The honest library: document collections inside ZIMs, the PDF text index,
fused ranking and reader safety. No kiwix-serve, model or network needed:
kiwix-serve is faked with httpx.MockTransport and embeddings with a stub."""

import asyncio
import re
from urllib.parse import unquote

import httpx
import pytest


# --------------------------------------------------------------------- fixtures
def make_pdf(pages: list[str], labels_from: int | None = None, nums: str = "") -> bytes:
    """A tiny, valid PDF with one line of Helvetica text per page (and optional page labels)."""
    objs: list[bytes] = []
    n = len(pages)
    kids = " ".join(f"{3 + 2 * i} 0 R" for i in range(n))
    font = 3 + 2 * n
    nums = nums or (f"0 << /S /D /St {labels_from} >>" if labels_from else "")
    labels = f" /PageLabels << /Nums [{nums}] >>" if nums else ""
    objs.append(f"<< /Type /Catalog /Pages 2 0 R{labels} >>".encode())
    objs.append(f"<< /Type /Pages /Kids [{kids}] /Count {n} >>".encode())
    for i, text in enumerate(pages):
        safe = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        stream = f"BT /F1 12 Tf 72 720 Td ({safe}) Tj ET".encode()
        objs.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents {4 + 2 * i} 0 R "
                    f"/Resources << /Font << /F1 {font} 0 R >> >> >>".encode())
        objs.append(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
    objs.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, o in enumerate(objs, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    for off in offsets:
        out += b"%010d 00000 n \n" % off
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)
    return bytes(out)


NAUTILUS_HOME = """<!DOCTYPE html><html><head><title>Medical Library</title></head><body>
<header><a href="home"><img src="main-logo.png"></a></header>
<section><ul id="doc-list" class="event-list"></ul><div class="no-result"><p>No result for this search request.</p></div>
<div id="loader"><span>Loading…</span></div></section>
<script src="vendors/pouchdb.min.js"></script><script src="nautilus.js"></script><script src="init.js"></script></body></html>"""

# The real format (nautiluszim 1.1.1): a Python-repr-like JS literal, single quotes, trailing comma.
DATABASE_JS = """var DATABASE = [
{'_id': '00000', 'ti': 'Where there is no Doctor ', 'dsc': 'A village healthcare handbook', 'aut': 'David Werner', 'fp': ['First Aid and Medicine (11).pdf']},
{'_id': '00001', 'ti': 'Field Kit Video', 'dsc': 'How to pack a kit', 'aut': 'Somebody', 'fp': ['kit.mp4']},
];
"""

TED_INDEX = """<html><body><select id="language-select" aria-label="Language"><option value="fr">Français</option><option value="en">English</option></select>
<ul id="video-items" class="rig grid"></ul><script src="assets/app.js"></script></body></html>"""
TED_DATA = 'window.json_data = [{"id":66,"slug":"the_power_of_vulnerability","title":"The power of vulnerability","speaker":"Brené Brown"}]'

ARTICLE = """<html><head><title>Burn</title></head><body><h1>Burn</h1><div class="mw-parser-output">
<p>A burn is an injury to skin or other tissues caused by heat, cold, electricity or chemicals.</p>
<h2>Management</h2><p>Cool the burn with clean running water for twenty minutes, then cover it loosely with a clean dressing.</p>
</div></body></html>"""


class FakeKiwix:
    """Just enough of kiwix-serve's HTTP API for the client: content, redirects, search, suggest, catalog."""

    def __init__(self):
        self.content: dict[tuple[str, str], tuple[bytes, str]] = {}
        self.mains: dict[str, str] = {}
        self.search_results: dict[str, list[tuple[str, str, str]]] = {}  # book → [(path, title, snippet)]
        self.titles: dict[str, list[tuple[str, str]]] = {}  # book → [(path, title)] for /suggest
        self.redirects: dict[tuple[str, str], str] = {}  # (book, path) → the path it redirects to
        self.requests: list[str] = []
        self.searches: list[tuple[str, list[str]]] = []  # (pattern, books) of every full-text search

    def add(self, book: str, path: str, body, ctype: str = "text/html"):
        self.content[(book, path)] = (body.encode() if isinstance(body, str) else body, ctype)

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = unquote(request.url.raw_path.decode().split("?")[0])
        self.requests.append(path)
        if path == "/search":
            books = request.url.params.get_list("books.name")
            self.searches.append((request.url.params.get("pattern"), books))
            items = "".join(
                f"<item><title>{t}</title><link>/content/{b}/{p}</link><description>{s}</description><wordCount>100</wordCount></item>"
                for b in books for p, t, s in self.search_results.get(b, []))
            return httpx.Response(200, text=f"<rss><channel>{items}</channel></rss>")
        if path == "/suggest":  # like kiwix-serve: titles holding every word of the term, in any order
            want = set(re.findall(r"\w+", request.url.params.get("term", "").lower()))
            got = [{"kind": "path", "value": t, "path": p} for p, t in self.titles.get(request.url.params.get("content"), [])
                   if want <= set(re.findall(r"\w+", t.lower()))]
            return httpx.Response(200, json=got[: int(request.url.params.get("count", "10"))])
        m = re.match(r"^/content/([^/]+)/?(.*)$", path)
        if m:
            book, p = m.group(1), m.group(2)
            if not p:
                return httpx.Response(302, headers={"location": f"/content/{book}/{self.mains.get(book, 'index')}"})
            if (book, p) in self.redirects:
                return httpx.Response(302, headers={"location": f"/content/{book}/{self.redirects[(book, p)]}"})
            if (book, p) in self.content:
                body, ctype = self.content[(book, p)]
                return httpx.Response(200, content=body, headers={"content-type": ctype, "content-length": str(len(body))})
        return httpx.Response(404, text="not found")


def make_client(tmp_path, fake: FakeKiwix, books: list, embedder=None):
    from mimi.db import Database
    from mimi.events import EventBus
    from mimi.kiwix import KiwixClient, KiwixService
    from mimi.libindex import DocIndex
    from mimi.paths import Paths
    from mimi.settings import SettingsStore

    paths = Paths(data_override=tmp_path / "data")
    settings = SettingsStore(Database(paths.db_file))
    svc = KiwixService(paths, settings, EventBus())
    svc.alive = lambda: True
    c = KiwixClient(svc, settings, index=DocIndex(tmp_path / "idx.sqlite"), embedder=embedder)
    c.http = httpx.AsyncClient(transport=httpx.MockTransport(fake.handler), base_url="http://127.0.0.1")
    c.worker_process = False

    async def fetch_books():
        return [book for book in books]

    c._fetch_books = fetch_books
    return c


def book(name: str, title: str, articles: int = 1, tags: str = "", language: str = "eng"):
    from mimi.kiwix import Book, alias_of, collection_of

    return Book(id=f"uuid-{name}", name=name, alias=alias_of(name), title=title, summary="", language=language, category="", tags=tags,
                flavour="", articles=articles, media=0, collection=collection_of(name), icon=None)


def run(coro):
    return asyncio.run(coro)


# --------------------------------------------------------------------- retrieval: terms and intent
def test_light_stemmer_merges_inflections_conservatively():
    from mimi.retrieval import query_terms, stem

    for group in (("bleeding", "bleeds", "bleed"), ("burns", "burned", "burning", "burn"), ("infections", "infected", "infection"),
                  ("bites", "biting", "bite"), ("injuries", "injury"), ("stopping", "stops", "stop"), ("matches", "match")):
        assert len({stem(w) for w in group}) == 1, group
    assert stem("glass") == "glass" and stem("tetanus") == "tetanus" and stem("virus") == "virus"
    assert query_terms("How do I stop the bleeding? Bleeding won't stop") == ["stop", "bleed", "won"]
    assert query_terms("how to treat a burn") == ["treat", "burn"]


def test_intent_detection_and_priors():
    from mimi.retrieval import detect_intent, prior

    assert detect_intent("how do I stop heavy bleeding from a wound").name == "medical"
    assert detect_intent("How do you stop a nosebleed?").name == "medical"  # "bleed" inside a word
    assert detect_intent("replace the battery in my laptop").name == "repair"
    assert detect_intent("how to purify drinking water").name == "survival"
    assert detect_intent("tallest mountain in canada") is None
    med = detect_intent("tooth abscess pain")
    assert prior("medicine", med) > prior("encyclopedia", med) > prior("qa", med)
    assert prior("qa", None) < prior("encyclopedia", None) == 1.0


# --------------------------------------------------------------------- retrieval: fusion
def _c(key, coll="encyclopedia", book="wiki", text=""):
    from mimi.retrieval import Candidate

    return Candidate(key, coll, book, text or str(key))


def test_rrf_fuses_lists_and_rewards_agreement():
    from mimi.retrieval import RankedList, rrf

    a = RankedList("a", [_c("x"), _c("y"), _c("z")])
    b = RankedList("b", [_c("y"), _c("w")])
    out = rrf([a, b])
    assert out[0].key == "y"  # 2nd + 1st beats a lone 1st
    assert [c.key for c in out[1:]] == ["x", "w", "z"]
    assert out[0].sources == ["a", "b"]


def test_rrf_priors_follow_intent():
    from mimi.retrieval import RankedList, detect_intent, rrf, split_by_book

    # One Xapian query over two books: Stack Exchange happens to rank first.
    group = RankedList("xapian", [_c("se1", "qa", "stackexchange"), _c("se2", "qa", "stackexchange"), _c("md1", "medicine", "mdwiki")])
    lists = split_by_book(group)
    assert {l.name for l in lists} == {"xapian:stackexchange", "xapian:mdwiki"}
    neutral = rrf(lists)
    assert neutral[0].key == "md1"  # split per book: each book's best hit starts level, Q&A carries a mild handicap
    med = rrf(lists, detect_intent("how do I treat a snake bite"))
    assert med[0].key == "md1" and med[0].score > 2 * med[1].score * 0.9
    rep = rrf([RankedList("x", [_c("fix", "repair", "ifixit"), _c("enc", "encyclopedia", "wiki")])], detect_intent("replace a cracked phone screen"))
    assert rep[0].key == "fix"


def test_semantic_rerank_and_caps():
    from mimi.retrieval import cap_per_key, semantic_rerank

    cands = [_c("a"), _c("b"), _c("c")]
    for c, s in zip(cands, (0.3, 0.2, 0.1)):
        c.score = s
    vecs = [[0.0, 1.0], [0.1, 0.9], [1.0, 0.0]]  # c is the one that means what the query means
    out = semantic_rerank(cands, [1.0, 0.0], vecs, alpha=0.8)
    assert out[0].key == "c"
    assert [c.key for c in semantic_rerank(cands, [1.0, 0.0], vecs[:2])] == [c.key for c in cands]  # mismatched vectors: no-op
    pages = [_c(("med", "a.pdf", p)) for p in (1, 2, 3)] + [_c(("med", "b.pdf", 1))]
    assert [c.key for c in cap_per_key(pages, lambda c: c.key[:2], 2)] == [("med", "a.pdf", 1), ("med", "a.pdf", 2), ("med", "b.pdf", 1)]


# --------------------------------------------------------------------- retrieval: passages
def test_bm25_prefers_the_rare_term_paragraph():
    from mimi.retrieval import blend_passage_scores, bm25_scores, query_terms

    paras = [
        "A burn is an injury to the skin caused by heat.",
        "Burns are common. Burns hurt. Most burns heal.",
        "Apply a tourniquet above the wound if bleeding from a limb will not stop with pressure.",
    ]
    s = bm25_scores(paras, query_terms("tourniquet for bleeding burns"))
    assert s.index(max(s)) == 2
    damped = bm25_scores(paras, query_terms("burn skin"), weights={"burn": 0.1})
    assert damped.index(max(damped)) == 0  # with "burn" damped (it's the title), "skin" decides
    assert bm25_scores([], ["x"]) == [] and bm25_scores(["a"], []) == [0.0]
    assert blend_passage_scores([1.0, 0.0], None) == [1.0, 0.0]
    b = blend_passage_scores([2.0, 1.0, 0.0], [0.1, 0.9, 0.5], beta=0.9)
    assert b.index(max(b)) == 1


def test_chunk_text_splits_pages_on_sentences():
    from mimi.retrieval import chunk_text

    page = "265\nIf the bleeding contin-\nues, press down. " + "Keep pressing on the belly. " * 30 + "\n\nShort tail sentence here, fine."
    chunks = chunk_text(page, target=200, hard=300)
    assert all(len(c) <= 300 for c in chunks)
    assert "continues" in chunks[0]  # hyphenated line break re-joined
    assert chunks[-1].startswith("Short tail")


# --------------------------------------------------------------------- collections: data files
def test_parse_js_data_handles_nautilus_ted_gutenberg_and_junk():
    from mimi.libindex import parse_js_data

    assert parse_js_data(DATABASE_JS)[0]["aut"] == "David Werner"
    assert parse_js_data(TED_DATA)[0]["slug"] == "the_power_of_vulnerability"
    assert parse_js_data('var json_data = [["Pride and Prejudice", "Austen, Jane", "111", 1342, "PR"]];')[0][3] == 1342
    assert parse_js_data("var x = {'a': true, 'b': null};") == {"a": True, "b": None}
    for junk in ("", "nothing here", "var x = alert(1);", "var x = __import__('os').system('x')", "var x = [1, 2"):
        assert parse_js_data(junk) is None


def test_collection_parsers():
    from mimi.libindex import gutenberg_docs, is_document_path, kind_of_mime, nautilus_docs, parse_js_data, ted_docs, ted_language_codes

    docs = nautilus_docs(DATABASE_JS)
    assert [(d.title, d.path, d.kind, d.author) for d in docs] == [
        ("Where there is no Doctor", "files/First Aid and Medicine (11).pdf", "pdf", "David Werner"),
        ("Field Kit Video", "files/kit.mp4", "video", "Somebody"),
    ]
    multi = nautilus_docs("var DATABASE = [{'_id': '1', 'ti': 'Course', 'fp': ['a.pdf', 'b.mp3']}];")
    assert [d.title for d in multi] == ["Course (1 of 2)", "Course (2 of 2)"] and multi[1].kind == "audio"
    assert ted_language_codes(TED_INDEX) == ["fr", "en"]
    talk = ted_docs(parse_js_data(TED_DATA))[0]
    assert (talk.title, talk.author, talk.path, talk.thumb) == ("The power of vulnerability", "Brené Brown", "the_power_of_vulnerability",
                                                                 "videos/66/thumbnail.webp")
    rows = parse_js_data('var json_data = [["Pride and Prejudice", "Austen, Jane", "111", 1342, "PR"], ["A/B Test", "X", "100", 7, null]];')
    g = gutenberg_docs(rows)
    assert [d.path for d in g] == ["Pride and Prejudice_cover.1342", "A-B Test_cover.7"]
    assert gutenberg_docs(rows, html_suffix=True)[0].path == "Pride and Prejudice_cover.1342.html"
    assert is_document_path("files/x.PDF") and is_document_path("videos/1/video.webm")
    assert not is_document_path("Burn") and not is_document_path("Mount_St._Helens") and not is_document_path("page.html")
    assert kind_of_mime("application/pdf; charset=binary") == "pdf" and kind_of_mime("text/html") == "html"


# --------------------------------------------------------------------- the PDF index
def test_pdf_pages_and_index_roundtrip(tmp_path):
    from mimi.libindex import Doc, DocIndex, fts_query, pdf_pages

    pages = pdf_pages(make_pdf(["Cover", "Bleeding: press firmly on the wound with a clean cloth.", "Fractures need a splint."], labels_from=10))
    assert [(n, label) for n, label, _ in pages] == [(2, "11"), (3, "12")]  # "Cover" is too short to keep
    assert "press firmly" in pages[0][2]
    roman = pdf_pages(make_pdf(["Preface text that is long enough.", "Chapter one text that is long enough."], nums="0 << /S /r >> 1 << /S /D >>"))
    assert [label for _, label, _ in roman] == ["i", "1"]
    # Numbering that restarts (two "1"s) can't identify a page: use physical numbers.
    restart = pdf_pages(make_pdf(["Part one text that is long enough.", "Part two text that is long enough."], nums="0 << /S /D >> 1 << /S /D >>"))
    assert [label for _, label, _ in restart] == ["1", "2"]
    assert pdf_pages(make_pdf(["Part one text that is long enough.", "Part two text that is long enough."], nums="0 << /S /D >> 1 << /S /D /St 7 >>"))[1][1] == "7"

    idx = DocIndex(tmp_path / "i.sqlite")
    doc = Doc(id="1", title="Where There Is No Doctor", path="files/a.pdf", kind="pdf", author="David Werner")
    idx.put_document("med_2024", doc, "sig1", pages)
    idx.put_document("med_2024", Doc(id="2", title="Kit video", path="files/kit.mp4", kind="video", description="packing a first aid kit"), "sig1", [], "meta")
    hits = idx.search(["bleeding", "wound"], ["med_2024"])
    assert hits[0]["page"] == 2 and hits[0]["label"] == "11" and "press" in hits[0]["snippet"]
    assert idx.search(["splints"], ["med_2024"])[0]["page"] == 3  # porter stemming: splints → splint
    assert idx.search(["kit"], ["med_2024"])[0]["path"] == "files/kit.mp4"  # found by its description (page 0)
    assert idx.search(["bleeding", "nonsenseword"], ["med_2024"])[0]["page"] == 2  # AND finds nothing → OR
    assert idx.search(['bleed" OR x:*', "NEAR("], ["med_2024"]) is not None  # hostile input stays a phrase
    assert fts_query(['a"b', "(c)"]) == '"ab" AND "c"'
    assert idx.page_text("med_2024", "files/a.pdf", 3)["text"].startswith("Fractures")
    assert idx.counts("med_2024") == (1, 2)
    assert idx.doc_status("med_2024", "files/a.pdf")["signature"] == "sig1"
    idx.set_zim_info("med_2024", "sig1", "documents", 2, {"main": "home"})
    assert idx.zim_info("med_2024")["info"]["main"] == "home"
    assert idx.forget_except(["other"]) == 1 and idx.search(["bleeding"], ["med_2024"]) == []


# --------------------------------------------------------------------- the client against a fake kiwix-serve
def _nautilus(fake: FakeKiwix, name="zimgit-medicine_en_2024-08"):
    fake.mains[name] = "home"
    fake.add(name, "home", NAUTILUS_HOME)
    fake.add(name, "database.js", DATABASE_JS, "text/javascript")
    fake.add(name, "files/First Aid and Medicine (11).pdf",
             make_pdf(["Where There Is No Doctor, a village health care handbook.", "To stop bleeding, press hard on the wound for ten minutes."], 111),
             "application/pdf")
    fake.add(name, "files/kit.mp4", b"\x00" * 64, "video/mp4")
    return book(name, "Medical Library")


def test_nautilus_book_is_surveyed_indexed_searched_and_cited(tmp_path):
    from mimi.kiwix import book_dict, hit_dict

    fake = FakeKiwix()
    med = _nautilus(fake)
    c = make_client(tmp_path, fake, [med])

    async def go():
        assert c.health_of(med)["status"] == "checking"
        await c._refresh(0)
        b = await c.book("zimgit-medicine_en")
        d = book_dict(b)
        assert (d["kind"], d["items"], d["item_noun"], d["articles"]) == ("documents", 2, "documents", 1)
        h = c.health_of(b)
        assert h["status"] == "ok" and h["readable"] and h["searchable"] and h["pages_indexed"] == 2

        got = await c.collection("zimgit-medicine_en")
        docs = {x.path: x for x in got[1]}
        pdf = docs["files/First Aid and Medicine (11).pdf"]
        assert pdf.indexed and pdf.pages == 2 and pdf.size > 500
        assert docs["files/kit.mp4"].kind == "video"

        hits = await c.search("how to stop bleeding", limit=3)
        top = hits[0]
        assert (top.title, top.page, top.label) == ("Where there is no Doctor, p. 112", 2, "112")
        assert hit_dict(top)["url"] == "/library/read/zimgit-medicine_en/files/First%20Aid%20and%20Medicine%20(11).pdf#page=2"
        assert not any(r.startswith("/search") for r in fake.requests)  # Xapian only knows the home page: not asked

        p = await c.passage(top, "how to stop bleeding", 600)
        assert p.title == "Where there is no Doctor, p. 112" and "press hard on the wound" in p.text
        assert p.url.endswith("(11).pdf#page=2")
        # A citation without a page (e.g. from read_article) finds the best page itself.
        from mimi.kiwix import Hit

        p2 = await c.passage(Hit("Where there is no Doctor", top.path, med.name, med.title, "medicine", ""), "bleeding wound", 600)
        assert p2.url.endswith("#page=2")
        # The page after a cited one joins the passage only when it is relevant, and the citation says so.
        p1 = await c.passage(Hit("x", top.path, med.name, med.title, "medicine", "", page=1, label="111"), "village handbook", 600)
        assert p1.title == "Where there is no Doctor, p. 111" and "bleeding" not in p1.text
        p12 = await c.passage(Hit("x", top.path, med.name, med.title, "medicine", "", page=1, label="111"), "village bleeding", 600)
        assert p12.title == "Where there is no Doctor, pp. 111–112" and p12.url.endswith("#page=1")

        home = await c.reader("zimgit-medicine_en", "home")
        assert home["kind"] == "collection"
        view = await c.reader("zimgit-medicine_en", "files/First Aid and Medicine (11).pdf")
        assert view["kind"] == "pdf" and view["indexed"] and view["title"] == "Where there is no Doctor"
        assert view["src"] == "/kiwix/content/zimgit-medicine_en_2024-08/files/First%20Aid%20and%20Medicine%20(11).pdf"
        assert (await c.reader("zimgit-medicine_en", "files/kit.mp4"))["kind"] == "video"
        assert await c.raw(med.name, "files/kit.mp4") is None  # raw() stays HTML-only

        # Second start: the survey is remembered for the same ZIM file, and nothing is re-indexed.
        c2 = make_client(tmp_path, fake, [book(med.name, med.title)])
        c2.index = c.index
        b2 = (await c2.books())[0]
        assert b2.kind == "documents" and b2.items == 2
        before = c2.index.doc_status(med.name, top.path)["updated_at"]
        await c2._refresh(0)
        assert c2.index.doc_status(med.name, top.path)["updated_at"] == before
        assert c2.index.counts(med.name) == (1, 2)

    run(go())


def test_fusion_mixes_documents_with_xapian_and_follows_intent(tmp_path):
    fake = FakeKiwix()
    med = _nautilus(fake)
    se = book("medicalsciences.stackexchange.com_en_all_2024-08", "Medical Sciences Stack Exchange", articles=50000, tags="_ftindex:yes")
    wiki = book("wikipedia_en_all_maxi_2026-08", "Wikipedia", articles=6_000_000, tags="_ftindex:yes")
    for b in (se, wiki):
        fake.mains[b.name] = "Main_Page"
        fake.add(b.name, "Main_Page", "<h1>Main</h1><p>" + "Welcome to the library. " * 20 + "</p>")
    fake.search_results[se.name] = [("questions/1/bleeding", "Why does bleeding stop?", "bleeding stops because…")]
    fake.search_results[wiki.name] = [("Bleeding", "Bleeding", "Bleeding is blood escaping…"), ("Hemostasis", "Hemostasis", "stops bleeding")]
    c = make_client(tmp_path, fake, [wiki, med, se])

    async def go():
        await c._refresh(0)
        hits = await c.search("how do I stop bleeding from a wound", limit=3)
        books = [h.book for h in hits]
        assert set(books) == {med.name, wiki.name, se.name}
        assert books.index(med.name) < books.index(se.name) and books.index(wiki.name) < books.index(se.name)
        repair = await c.search("bleeding", collections=["qa"], limit=3)
        assert [h.book for h in repair] == [se.name]

    run(go())


def test_books_in_the_users_language_are_searched_in_it(tmp_path):
    """A Spanish book is searched with the Spanish words, English books with the English ones, and
    Spanish medical Wikipedia sits on the Medicine shelf."""
    fake = FakeKiwix()
    wiki = book("wikipedia_en_all_maxi_2026-08", "Wikipedia", articles=6_000_000, tags="_ftindex:yes")
    medes = book("wikipedia_es_medicine_maxi_2026-10", "Wikipedia Médica", articles=40_000, tags="_ftindex:yes", language="spa")
    for b in (wiki, medes):
        fake.mains[b.name] = "Main_Page"
        fake.add(b.name, "Main_Page", "<h1>Main</h1><p>" + "Welcome. " * 50 + "</p>")
    fake.search_results[wiki.name] = [("Burn", "Burn", "A burn is an injury to skin")]
    fake.search_results[medes.name] = [("Quemadura", "Quemadura", "Una quemadura es una lesión de la piel")]
    c = make_client(tmp_path, fake, [wiki, medes])
    assert medes.collection == "medicine" and wiki.collection == "encyclopedia"

    async def go():
        hits = await c.search("burn first aid", limit=3, local=("spa", "quemadura primeros auxilios"))
        assert sorted(fake.searches) == [("burn first aid", [wiki.name]), ("quemadura primeros auxilios", [medes.name])]
        assert {(h.title, h.language) for h in hits} == {("Burn", "eng"), ("Quemadura", "spa")}
        fake.searches.clear()
        await c.search("burn first aid", limit=3)  # no local query: everything gets the English words, as before
        assert sorted(fake.searches) == [("burn first aid", [wiki.name]), ("burn first aid", [medes.name])]

    run(go())


def test_titles_are_found_as_the_question_words_them(tmp_path):
    """The title lookup matches titles the way the question writes them: little words count
    ("Speed of light", not the "Speed light" flash), a title can sit anywhere in the question,
    and a keyword query still finds a title that has little words ("Picadura de abeja")."""
    fake = FakeKiwix()
    wiki = book("wikipedia_en_all_maxi_2026-08", "Wikipedia", articles=6_000_000, tags="_ftindex:yes")
    medes = book("wikipedia_es_medicine_maxi_2026-10", "Wikipedia Médica", articles=40_000, tags="_ftindex:yes", language="spa")
    fake.titles[wiki.name] = [("Speed_light", "Speed light"), ("Speed_of_light", "Speed of light"), ("Since", "Since"),
                              ("Great_Wall_(China)", "Great Wall (China)"), ("Great_Wall_of_China", "Great Wall of China"),
                              ("Capital_of_Australia", "Capital of Australia"), ("Capital", "Capital")]
    fake.titles[medes.name] = [("Picadura_de_abeja", "Picadura de abeja")]
    c = make_client(tmp_path, fake, [wiki, medes])

    async def titles(q, books=(wiki,), language=""):
        return [h.title for h in await c._title_hits(q, list(books), language)]

    async def go():
        assert await titles("What is the speed of light in a vacuum?") == ["Speed of light"]
        assert await titles("speed of light") == ["Speed of light"]
        wall = await titles("Since the Great Wall of China is visible from the Moon, how wide is it?")
        assert wall[0] == "Great Wall of China" and "Great Wall (China)" not in wall  # longest first; search() vets "Since"
        assert (await titles("What is the capital of Australia?"))[0] == "Capital of Australia"
        assert await titles("picadura abeja", (medes,), "spa") == ["Picadura de abeja"]

    run(go())


def test_a_one_word_title_needs_the_full_text_search_to_agree(tmp_path):
    fake = FakeKiwix()
    wiki = book("wikipedia_en_all_maxi_2026-08", "Wikipedia", articles=6_000_000, tags="_ftindex:yes")
    fake.titles[wiki.name] = [("Since", "Since"), ("Hypothermia", "Hypothermia")]
    fake.search_results[wiki.name] = [("Hypothermia", "Hypothermia", "Hypothermia is a body temperature below 35 °C"),
                                      ("Frostbite", "Frostbite", "Frostbite is damage to skin from freezing")]
    c = make_client(tmp_path, fake, [wiki])

    async def go():
        assert [h.title for h in await c._title_hits("Since when is hypothermia dangerous?", [wiki])] == ["Since", "Hypothermia"]
        hits = await c.search("Since when is hypothermia dangerous?", limit=3)
        assert hits[0].title == "Hypothermia" and "Since" not in [h.title for h in hits]

    run(go())


def test_a_generic_title_does_not_hide_the_topics_own(tmp_path):
    """Models add "first aid" to their queries: the "First aid" article must not crowd out "Nosebleed"."""
    fake = FakeKiwix()
    wiki = book("wikipedia_en_all_maxi_2026-08", "Wikipedia", articles=6_000_000, tags="_ftindex:yes")
    fake.titles[wiki.name] = [("First_aid", "First aid"), ("Nosebleed", "Nosebleed")]
    fake.search_results[wiki.name] = [("Nosebleed", "Nosebleed", "A nosebleed is bleeding from the nose"),
                                      ("Epistaxis_care", "Epistaxis care", "Lean forward and pinch the nose")]
    c = make_client(tmp_path, fake, [wiki])

    async def go():
        hits = await c.search("how to stop a nosebleed first aid", limit=3)
        assert hits[0].title == "Nosebleed"

    run(go())


def test_a_one_word_title_from_a_book_on_the_subject_is_kept(tmp_path):
    """med-008 on the F1: for "hypothermia core body temperature threshold" MDWiki's full-text search didn't rank
    "Hypothermia" in its top 8, and the longer "Core body temperature" (→ Human body temperature) took its place."""
    fake = FakeKiwix()
    med = book("mdwiki_en_all_maxi_2025-11", "MDWiki Medical Encyclopedia", articles=363_000, tags="_ftindex:yes")
    fake.titles[med.name] = [("Core_body_temperature", "Core body temperature"), ("Hypothermia", "Hypothermia"),
                             ("Temperature", "Temperature")]
    fake.redirects[(med.name, "Core_body_temperature")] = "Human_body_temperature"
    fake.redirects[(med.name, "Temperature")] = "Thermoregulation"  # a generic word the full text agrees with
    fake.add(med.name, "Thermoregulation", "<h1>Thermoregulation</h1><p>Keeping the body temperature steady.</p>")
    fake.add(med.name, "Human_body_temperature", "<h1>Human body temperature</h1><p>Normal is about 37 °C.</p>")
    fake.add(med.name, "Hypothermia", "<h1>Hypothermia</h1><p>A core temperature below 35.0 °C.</p>")
    fake.search_results[med.name] = [("Human_body_temperature", "Human body temperature", "Normal human body temperature"),
                                      ("Thermoregulation", "Thermoregulation", "Keeping the body temperature steady")]
    c = make_client(tmp_path, fake, [med])
    assert med.collection == "medicine"

    async def go():
        top = [h.title for h in await c.search("hypothermia core body temperature threshold", limit=3)][:3]
        assert "Hypothermia" in top  # among the three articles the model reads

    run(go())


def test_one_title_from_three_books_leaves_room_for_a_four_letter_topic(tmp_path):
    """med-003 on the F1: for "burn first aid" three books' "First aid" took every title slot, and "burn" (four
    letters) was never looked up, so no burn article reached the model."""
    fake = FakeKiwix()
    med = book("mdwiki_en_all_maxi_2025-11", "MDWiki Medical Encyclopedia", articles=363_000, tags="_ftindex:yes")
    wiki = book("wikipedia_en_all_maxi_2026-08", "Wikipedia", articles=6_000_000, tags="_ftindex:yes")
    top = book("wikipedia_en_100_2026-08", "Wikipedia 100", articles=3_000, tags="_ftindex:yes")
    for b in (med, wiki, top):
        fake.titles[b.name] = [("First_aid", "First aid")]
        fake.add(b.name, "First_aid", "<h1>First aid</h1><p>Help given to a sick or injured person.</p>")
        fake.search_results[b.name] = [("First_aid", "First aid", "Help given to an injured person")]
    fake.titles[med.name].append(("Burn", "Burn"))
    fake.add(med.name, "Burn", "<h1>Burn</h1><p>Cool a burn under running water for 20 minutes.</p>")
    c = make_client(tmp_path, fake, [med, wiki, top])

    async def go():
        assert "Burn" in [h.title for h in await c.search("burn first aid", limit=5)]

    run(go())


def test_one_word_titles_from_big_books_leave_room_for_the_topic(tmp_path):
    """med-019: "Rice", "Stand" and "Treating" from the two biggest books filled the title lookup's places
    before MDWiki's "Sprained" (a redirect to Sprain) was reached."""
    fake = FakeKiwix()
    wiki = book("wikipedia_en_all_maxi_2026-08", "Wikipedia", articles=6_000_000, tags="_ftindex:yes")
    top = book("wikipedia_en_top_maxi_2026-08", "Wikipedia's top articles", articles=1_000_000, tags="_ftindex:yes")
    med = book("mdwiki_en_all_maxi_2025-11", "MDWiki Medical Encyclopedia", articles=363_000, tags="_ftindex:yes")
    for b in (wiki, top):
        fake.titles[b.name] = [("Rice", "Rice"), ("Stand", "Stand"), ("Treating", "Treating")]
    fake.titles[med.name] = [("Sprained", "Sprained")]
    fake.redirects[(med.name, "Sprained")] = "Sprain"
    fake.add(med.name, "Sprain", "<h1>Sprain</h1><p>Rest, ice, compression and elevation (RICE).</p>")
    c = make_client(tmp_path, fake, [wiki, top, med])

    async def go():
        hits = await c.search("What does RICE stand for in treating a sprained ankle?", limit=5)
        assert "Sprain" in [h.title for h in hits]

    run(go())


def test_every_books_copy_of_a_title_is_kept(tmp_path):
    """med-017: keeping one copy per title kept Wikipedia's "Myocardial infarction" and dropped MDWiki's."""
    fake = FakeKiwix()
    med = book("mdwiki_en_all_maxi_2025-11", "MDWiki Medical Encyclopedia", articles=363_000, tags="_ftindex:yes")
    wiki = book("wikipedia_en_all_maxi_2026-08", "Wikipedia", articles=6_000_000, tags="_ftindex:yes")
    for b in (med, wiki):
        fake.titles[b.name] = [("Myocardial_infarction", "Myocardial infarction")]
        fake.add(b.name, "Myocardial_infarction", "<h1>Myocardial infarction</h1><p>Chest pain is the most common symptom.</p>")
    c = make_client(tmp_path, fake, [med, wiki])

    async def go():
        hits = await c.search("myocardial infarction symptoms", limit=5)
        assert {h.book for h in hits if h.title == "Myocardial infarction"} == {med.name, wiki.name}

    run(go())


def test_a_title_redirect_becomes_its_article_and_a_small_part_of_the_question_needs_the_full_text(tmp_path):
    fake = FakeKiwix()
    wiki = book("wikipedia_en_all_maxi_2026-08", "Wikipedia", articles=6_000_000, tags="_ftindex:yes")
    fake.titles[wiki.name] = [("Capital_of_Australia", "Capital of Australia"), ("Warm_It_Up", "Warm It Up")]
    fake.redirects[(wiki.name, "Capital_of_Australia")] = "Canberra"
    fake.add(wiki.name, "Canberra", "<h1>Canberra</h1><p>Canberra is the capital city of Australia.</p>")
    fake.add(wiki.name, "Warm_It_Up", "<h1>Warm It Up</h1><p>A song.</p>")
    fake.search_results[wiki.name] = [("Canberra", "Canberra", "Canberra is the capital city of Australia"),
                                      ("Frostbite", "Frostbite", "Do not rub frostbitten skin")]
    c = make_client(tmp_path, fake, [wiki])

    async def go():
        hits = await c.search("What is the capital of Australia?", limit=3)
        assert [(h.title, h.path) for h in hits][:1] == [("Canberra", "Canberra")]
        assert [h.path for h in hits].count("Canberra") == 1  # the redirect merged with the article's full-text hit
        hits = await c.search("Should you rub snow on frostbite to warm it up?", limit=3)
        assert "Warm It Up" not in [h.title for h in hits]

    run(go())


def test_kiwix_serve_starts_with_a_small_search_cache_and_enough_threads(tmp_path, monkeypatch):
    """libkiwix kept ~70 MB per recent full-text search; on the F1 it reached 5 GB and starved the model."""
    import mimi.kiwix as K
    from mimi.db import Database
    from mimi.events import EventBus
    from mimi.paths import Paths
    from mimi.settings import SettingsStore

    paths = Paths(data_override=tmp_path / "data")
    svc = K.KiwixService(paths, SettingsStore(Database(paths.db_file)), EventBus())
    exe = tmp_path / "kiwix-serve.exe"
    exe.write_bytes(b"")
    monkeypatch.setattr(paths, "exe", lambda *a: exe)
    monkeypatch.setattr(svc, "zim_files", lambda: [tmp_path / "wikipedia_en_all_maxi_2026-08.zim"])
    started = {}

    class Proc:
        def __init__(self, name, args, cwd=None, log_path=None, env=None):
            started.update(args=args, env=env)

        def start(self):
            pass

    monkeypatch.setattr(K, "ManagedProcess", Proc)
    ok, real = httpx.MockTransport(lambda r: httpx.Response(200, text="<feed/>")), httpx.AsyncClient
    monkeypatch.setattr(K.httpx, "AsyncClient", lambda *a, **k: real(transport=ok))
    run(svc.start())
    assert started["env"] == {"KIWIX_SEARCH_CACHE_SIZE": "2"}
    assert 4 <= int(started["args"][started["args"].index("--threads") + 1]) <= 8


def test_kiwix_serve_is_restarted_only_when_it_holds_too_much_and_the_library_is_idle(tmp_path, monkeypatch):
    """libkiwix held 4-5 GB within an hour of searches on the F1; a fresh process gives it back."""
    import time

    import mimi.kiwix as K

    fake = FakeKiwix()
    c = make_client(tmp_path, fake, [])
    svc = c.service
    svc.alive = lambda: True
    assert K.KiwixService.memory_limit() >= 1.5 * 2**30  # 12 % of this machine's RAM, at least 1.5 GB
    monkeypatch.setattr(K.KiwixService, "memory_limit", staticmethod(lambda: 2 * 2**30))
    held = {"bytes": 3 * 2**30}
    monkeypatch.setattr(svc, "memory", lambda: held["bytes"])
    run(K.KiwixClient._used(c, None))  # a request just now
    assert not svc.needs_fresh_start()  # never in the middle of a search
    svc.last_used = time.monotonic() - K.IDLE_BEFORE_RESTART - 1
    assert svc.needs_fresh_start()
    held["bytes"] = 1 * 2**30
    assert not svc.needs_fresh_start()  # under the limit: leave it alone


def test_a_full_wikipedia_hides_only_its_own_languages_small_edition(tmp_path, monkeypatch):
    from mimi.db import Database
    from mimi.events import EventBus
    from mimi.kiwix import KiwixService, alias_of
    from mimi.paths import Paths
    from mimi.settings import SettingsStore

    monkeypatch.setenv("MIMI_CONTENT", str(tmp_path / "content"))
    paths = Paths(data_override=tmp_path / "data")
    paths.zim.mkdir(parents=True, exist_ok=True)
    svc = KiwixService(paths, SettingsStore(Database(paths.db_file)), EventBus())
    import mimi.kiwix as K

    monkeypatch.setattr(K, "zim_expected_size", lambda p: p.stat().st_size)  # any file counts as complete here
    for n in ("wikipedia_en_all_nopic_2026-06", "wikipedia_en_top_nopic_2026-09", "wikipedia_es_top_nopic_2026-10"):
        (paths.zim / f"{n}.zim").write_bytes(b"z" * 2048)  # under 1 KB is ignored
    assert [f.stem for f in svc.zim_files()] == ["wikipedia_en_all_nopic_2026-06", "wikipedia_es_top_nopic_2026-10"]
    (paths.zim / "wikipedia_es_all_nopic_2026-10.zim").write_bytes(b"z" * 2048)
    assert [f.stem for f in svc.zim_files()] == ["wikipedia_en_all_nopic_2026-06", "wikipedia_es_all_nopic_2026-10"]
    assert alias_of("wikivoyage_fr_all_maxi_2026-07c") == alias_of("wikivoyage_fr_all_maxi_2026-07") == "wikivoyage_fr_all_maxi"


def test_semantic_rerank_uses_embeddings_and_survives_their_absence(tmp_path):
    fake = FakeKiwix()
    wiki = book("wikipedia_en_all_maxi_2026-08", "Wikipedia", articles=6_000_000, tags="_ftindex:yes")
    fake.mains[wiki.name] = "Main_Page"
    fake.add(wiki.name, "Main_Page", "<h1>Main</h1><p>" + "Welcome. " * 50 + "</p>")
    fake.search_results[wiki.name] = [("Apple_Inc.", "Apple Inc.", "technology company"), ("Banana", "Banana", "fruit"),
                                       ("Apple", "Apple", "the fruit of the apple tree")]
    calls = []

    async def embed(texts):
        calls.append(len(texts))
        return [[1.0, 0.0] if ("fruit" in t or "apple" == t) else [0.0, 1.0] for t in texts]

    c = make_client(tmp_path, fake, [wiki], embedder=embed)

    async def go():
        hits = await c.search("apple", limit=3)
        assert hits[0].path == "Banana" and hits[1].path != "Banana"  # the fruit pages climb past the company
        assert calls == [4]  # the query and three snippets in one call

        async def down(texts):
            raise httpx.ConnectError("refused")

        c2 = make_client(tmp_path, fake, [wiki], embedder=down)
        plain = await c2.search("apple", limit=3)
        assert [h.path for h in plain] == ["Apple_Inc.", "Banana", "Apple"]  # Xapian's order, no error
        assert c2._embed_down_until > 0  # and it isn't retried on every query

        async def slow(texts):
            await asyncio.sleep(5)

        c3 = make_client(tmp_path, fake, [wiki], embedder=slow)
        import mimi.kiwix as K

        old, K.RERANK_TIMEOUT = K.RERANK_TIMEOUT, 0.05
        try:
            assert [h.path for h in await c3.search("apple", limit=3)] == ["Apple_Inc.", "Banana", "Apple"]
        finally:
            K.RERANK_TIMEOUT = old

    run(go())


def test_html_passage_still_works_through_the_client(tmp_path):
    fake = FakeKiwix()
    md = book("mdwiki_en_all_2025-11", "MDWiki", articles=30000, tags="_ftindex:yes")
    fake.mains[md.name] = "Main_Page"
    fake.add(md.name, "Burn", ARTICLE)
    c = make_client(tmp_path, fake, [md])
    from mimi.kiwix import Hit

    p = run(c.passage(Hit("Burn", "Burn", md.name, md.title, "medicine", ""), "how to treat a burn", 800))
    assert p.title == "Burn" and "Cool the burn" in p.text and p.url == "/library/read/mdwiki_en_all/Burn"


def test_health_flags_js_only_and_unsearchable_books(tmp_path):
    fake = FakeKiwix()
    ted = book("ted_mul_health_2025-02", "TED Health", articles=300)
    fake.mains[ted.name] = "index"
    fake.add(ted.name, "index", TED_INDEX)
    fake.add(ted.name, "assets/data_en.js", TED_DATA, "text/javascript")
    fake.search_results[ted.name] = [("the_power_of_vulnerability", "The power of vulnerability", "…")]
    blank = book("gutenberg_en_all_2025-01", "Project Gutenberg", articles=70000)
    fake.mains[blank.name] = "Home"
    fake.add(blank.name, "Home", "<html><body><table id='books_table' class='datatable'></table><script src='js/tools.js'></script></body></html>")
    jsonly = book("something_en_all_2025-01", "Some App ZIM", articles=10)
    fake.mains[jsonly.name] = "index"
    fake.add(jsonly.name, "index", "<html><body><div id='app'></div><script src='app.js'></script></body></html>")
    old_ted = book("ted_en_science_2019-01", "TED Science (old layout)", articles=80)
    fake.mains[old_ted.name] = "index"
    fake.add(old_ted.name, "index", "<html><body><h1>TED Science</h1>" + "".join(f'<p><a href="talk_{i}">Talk number {i}</a></p>' for i in range(12)) + "</body></html>")
    c = make_client(tmp_path, fake, [ted, blank, jsonly, old_ted])

    async def go():
        await c._refresh(0)
        t = c.health_of(ted)
        assert ted.kind == "videos" and ted.items == 1 and t["readable"] and t["searchable"] and t["status"] == "ok"
        got = await c.collection(ted.name)
        assert got[1][0].title == "The power of vulnerability"
        g = c.health_of(blank)
        assert blank.kind == "books" and g["status"] == "unreadable" and "JavaScript" in g["note"]
        j = c.health_of(jsonly)
        assert jsonly.kind == "articles" and j["status"] == "unreadable" and "JavaScript" in j["note"]
        # A TED ZIM whose home page works without JavaScript stays a normal, readable book.
        assert old_ted.kind == "articles" and c.health_of(old_ted)["readable"]
        # Their JS-driven home pages never come back as search hits.
        assert all(h.path != "index" for h in await c.search("vulnerability", collections=["talks"]))

    run(go())


# --------------------------------------------------------------------- reader safety
@pytest.mark.parametrize("href", [
    "javascript:alert(1)", "JaVaScRiPt:alert(1)", " javascript:alert(1)", "java\tscript:alert(1)", "java\nscript:alert(1)",
    "vbscript:msgbox(1)", "data:text/html,<script>alert(1)</script>", "file:///etc/passwd", "blob:http://x/1", "jar:x",
])
def test_reader_neutralizes_dangerous_links(href):
    from mimi.kiwix import render_reader

    html = f'<html><body><h1>T</h1><main><p><a href="{href}" onclick="x()">click</a></p></main></body></html>'
    r = render_reader(html, "b_2025-01", "T", "b", "B")
    assert "script:" not in r["html"].lower() and "data:" not in r["html"] and "file:" not in r["html"]
    assert "onclick" not in r["html"] and ">click</a>" in r["html"]


def test_reader_keeps_good_links_and_drops_active_content():
    from mimi.kiwix import render_reader

    html = """<html><body><h1>T</h1><main>
    <p><a href="https://example.org">web</a> <a href="mailto:a@b.c">mail</a> <a href="Other_page#x">in</a> <a href="#sec">frag</a></p>
    <img src="data:image/png;base64,AAAA" alt="ok"><img src="data:image/svg+xml,&lt;svg onload=alert(1)&gt;" alt="svg">
    <img src="javascript:alert(1)"><video src="data:video/mp4;base64,AAAA" poster="javascript:x"></video><img src="https://tracker/x.png">
    <iframe src="javascript:alert(1)"></iframe><object data="x.swf"></object><embed src="x.swf"><form action="javascript:x"><button>go</button></form>
    <map><area href="javascript:alert(1)"></map><svg><a xlink:href="javascript:alert(1)" href="javascript:alert(2)"><text>s</text></a></svg>
    <math href="javascript:alert(1)"><mi>x</mi></math><base href="https://evil/">
    </main></body></html>"""
    out = render_reader(html, "b_2025-01", "T", "b", "B")["html"]
    assert 'data-external="1"' in out and out.count('href="#"') == 2
    assert 'href="/library/read/b/Other_page#x"' in out and 'href="#sec"' in out
    assert 'src="data:image/png;base64,AAAA"' in out  # inline images are fine
    for bad in ("javascript", "<iframe", "<object", "<embed", "<form", "<base", "data:video", "https://tracker", "evil"):
        assert bad not in out, bad


def test_reader_title_falls_back_to_title_tag():
    from mimi.kiwix import render_reader

    r = render_reader("<html><head><title>The power of vulnerability</title></head><body><p>x</p></body></html>", "ted_x", "the_power_of_vulnerability", "ted", "TED")
    assert r["title"] == "The power of vulnerability"


def test_kiwix_proxy_headers_frame_pdfs_and_sandbox_html():
    from mimi.api import _kiwix_frame_headers

    pdf = _kiwix_frame_headers("application/pdf")
    assert pdf["X-Frame-Options"] == "SAMEORIGIN" and "frame-ancestors 'self'" in pdf["Content-Security-Policy"]
    assert _kiwix_frame_headers("video/webm")["X-Frame-Options"] == "SAMEORIGIN"
    assert _kiwix_frame_headers("image/png") == {}
    for t in ("text/html; charset=utf-8", "image/svg+xml", "application/javascript", "text/xml"):
        assert _kiwix_frame_headers(t)["Content-Security-Policy"].startswith("sandbox")


def test_library_api_without_kiwix(client):
    client.post("/api/auth/setup", json={"name": "Ada"})
    r = client.get("/api/library/books").json()
    assert r["books"] == [] and r["running"] is False and "indexing" in r
    assert client.get("/api/library/collection/nothing").status_code == 404


def test_a_zim_cut_short_is_held_back_and_reported(tmp_path, monkeypatch):
    """A download that stopped early is never handed to kiwix-serve (which would list it, then fail);
    the owner is told which file and how much of it arrived."""
    import struct

    from mimi.db import Database
    from mimi.events import EventBus
    from mimi.kiwix import KiwixService, zim_expected_size
    from mimi.paths import Paths
    from mimi.settings import SettingsStore

    monkeypatch.setenv("MIMI_CONTENT", str(tmp_path / "content"))  # not the repo's own zim/ folder

    def zim(n_body: int) -> bytes:
        head = bytearray(80)
        struct.pack_into("<I", head, 0, 72173914)
        struct.pack_into("<Q", head, 72, 80 + n_body)
        return bytes(head) + b"z" * n_body + b"m" * 16

    paths = Paths(data_override=tmp_path / "data")
    paths.zim.mkdir(parents=True, exist_ok=True)
    (paths.zim / "wikivoyage_en_all_maxi_2026-01.zim").write_bytes(zim(4000))
    (paths.zim / "mdwiki_en_all_maxi_2025-11.zim").write_bytes(zim(4000)[:2500])
    (paths.zim / "notes.zim").write_bytes(b"not a zim file " * 100)
    svc = KiwixService(paths, SettingsStore(Database(paths.db_file)), EventBus())

    assert [f.name for f in svc.zim_files()] == ["wikivoyage_en_all_maxi_2026-01.zim"]
    held = {i["file"]: i for i in svc.incomplete}
    assert held["mdwiki_en_all_maxi_2025-11.zim"] == {"file": "mdwiki_en_all_maxi_2025-11.zim", "size": 2500, "expected": 4096}
    assert held["notes.zim"]["expected"] == 0
    assert zim_expected_size(paths.zim / "wikivoyage_en_all_maxi_2026-01.zim") == 4096


def test_the_librarys_embedding_calls_count_as_use(tmp_path):
    """On the F1 the model manager stopped the embedding server as idle while every search was using it: only its
    own embed() calls counted, so searches went without semantic ranking for most of a 5-hour eval run."""
    c = make_client(tmp_path, FakeKiwix(), [])
    used = []
    c.on_embed = lambda: used.append(1)

    async def post(url, json=None, timeout=None):
        data = [{"index": i, "embedding": [1.0, 0.0]} for i, _ in enumerate(json["input"])]
        return httpx.Response(200, json={"data": data}, request=httpx.Request("POST", url))

    c.http.post = post

    async def go():
        assert await c._http_embed(["a", "b"]) == [[1.0, 0.0], [1.0, 0.0]]

    run(go())
    assert used == [1]


def test_core_tells_the_model_manager_when_search_used_embeddings(client):
    svc = client.app.state.svc
    assert svc.kiwix.on_embed == svc.models.embed_used
    svc.models._embed_last_use = 0.0
    svc.kiwix.on_embed()
    assert svc.models._embed_last_use > 0
