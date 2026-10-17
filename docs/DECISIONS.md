# Decisions (and where we deviated from the plan)

Each entry: what we chose, why, and what it replaced in [PLAN.md](PLAN.md).

### D1 · Native shell: WinForms + WebView2 via the in-box C# compiler, not Tauri
Tauri needs Rust, and on Windows that means the Visual Studio Build Tools, an admin install of about 6 GB. `C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe` ships with every Windows 10/11 machine and can host the same WebView2 runtime, so `shell/build.ps1` builds `MIMI.exe` in seconds with no toolchain. The trade-off is that the shell is Windows-only; the web UI and Core are cross-platform.

### D2 · Core manages llama-server directly, not llama-swap
Core already supervises every other process. Doing model swaps itself gives the UI precise status ("Waking up Gemma 4 12B…") and one less binary to ship.

### D3 · Core terminates TLS itself, not Caddy
The share server is a second uvicorn listener with a certificate issued by a local CA that Mimi generates (`share.py`, using the `cryptography` package). mDNS (`mimi.local`) comes from `zeroconf`. That's one process fewer and no Go binary.

### D4 · OCR with RapidOCR (PP-OCRv6, ONNX), not Tesseract
It installs from pip with its models bundled, needs no admin rights, and is more accurate on photos. It reads a sign in about 0.5 s on the CPU.

### D5 · Places from GeoNames, not an OSM POI extraction
GeoNames for the US and Canada is small (a few hundred MB), and it has clean feature codes (parks, historic sites, lakes, summits) and populations. Geotagged Wikipedia adds the notable landmarks. OSM-derived fuel stations and hospitals are future work.

### D6 · Default model on the 16 GB reference device: Gemma 4 12B (QAT Q4_0)
We measured both finalists inside the real app (Chrome, the Claude app and Steam open):

| | Generation | Prompt | Grounded answer (2 turns) | Quality |
|---|---|---|---|---|
| Gemma 4 12B | 7.3–9.6 tok/s | ~110 tok/s | 36–39 s | Correct, well cited, clean |
| Qwen3.5-9B | 11–12.8 tok/s | ~110–150 tok/s | 42–49 s* | **Invented a 1975 first ascent and fake citations; leaked `<tool_code>` text** |

\*Qwen made extra, malformed tool calls. Gemma misses the plan's 8 tok/s bar by a little under memory pressure, but it was the only model that stayed accurate. For an offline reference device, accuracy beats speed. Qwen3.5-9B remains the Reader/alternative, Qwen3.5-4B powers voice and battery saver, and all three can be switched in Settings → Models.

### D7 · Forced grounding and a citation sanitizer
Small models skip the search and answer from memory, sometimes with invented citations. For questions that look factual, the first step now requires a tool call. Afterwards any citation that doesn't point to a real source is removed.

### D8 · Offline routing with Valhalla
The plan left routing out because OSRM needs more than 16 GB of RAM to build North America. Valhalla's Windows wheel (`pyvalhalla`) includes `valhalla_build_tiles.exe`. Its temporary disk use is about 5× the input, so `scripts/build_routing.py` first filters the OSM extracts down to drivable roads, ferries and turn restrictions with pyosmium. That cut the input to a third in testing. Routes compute in about 0.1 s.

### D9 · A library that isn't all of Khan Academy
Kiwix only publishes the full Khan Academy edition (about 180 GB), which doesn't fit next to Wikipedia with images, so it's an external-SSD item. Five TED topics (about 11 GB) and two Gutenberg shelves (about 3.8 GB) are included instead of the 16 GB English-literature shelf, to keep disk headroom.

### D10 · Title boost in library search
Xapian full-text ranking sometimes buries the article whose title *is* the topic ("Bee sting"). Search now first tries the query's leading words as a title prefix in the largest collections.

### D11 · Launch at startup is a Task Scheduler task, not a Run key entry
The plan used the per-user `Run` registry key. On the reference device, Explorer ran every other entry in that key at sign-in but silently skipped Mimi's (its Shell-Core log lists each command it starts; Mimi's never appeared, and nothing marked it disabled). The setting now registers a per-user task with a logon trigger (`schtasks`, no admin rights), set to run on battery, with no time limit and normal priority. Core re-syncs it at every start, which also moves an old Run entry over and re-points the task when a portable drive comes back under a new letter.

### D12 · Model and retrieval changes are backed by an eval run
D6 picked the default model from a few conversations, and the D7 sanitizer can't tell a real citation from a misattributed one. Changes to the default model, the system prompt, the tool loop or library search now come with a run of the golden set (`eval/run.py`, 166 questions across medicine, repair, travel, survival, general knowledge, location and adversarial prompts) and a scoreboard from `eval/score.py`. The scoreboard covers key-fact accuracy, forbidden claims, answer/hedge/refuse behavior, citation faithfulness (`mimi.grounding`, which checks each `[n]` against its source and flags invented numbers, swapped names and contradictions), Recall@k/MRR and latency. Model comparisons are A/B runs on the same device in the same session, with a McNemar test on per-item flips, and safety metrics are read first (see [EVALUATION.md](EVALUATION.md)). D6 stands until the first such run confirms or overturns it. The plan had no evaluation step.

### D13 · An honest library: survey every book, list what JavaScript would have listed
A user opened the Medical Library and got a blank page. The `zimgit-*` ZIMs (medicine, water, knots, food, post-disaster) are built by nautilus: the home page is an empty `<ul id="doc-list">` that JavaScript fills from `database.js`, and the content is PDFs under `files/` (12 in medicine, 7 in water). Mimi's reader strips scripts, as it must, so it showed "Loading… No result for this search request". The Kiwix catalog says "1 article", and Xapian only indexed the home page (a search for "bleeding" found nothing), so chat could never cite these books either.

Core now surveys each book in the background (`KiwixClient.survey`): it fetches the main page and recognizes nautilus (`doc-list`/`nautilus.js`), TED (`video-items`; talks in `assets/data_<lang>.js`, or `assets/data.js` in older ZIMs) and Gutenberg (`full_by_popularity.js` rows of `[title, author, formats, id, shelf]`; cover pages at `<title>_cover.<id>`, with `.html` before gutenberg2zim 3). The data files are parsed as literals, never run. The library then lists their items natively, opens PDFs in the browser's own viewer and plays media with `<video>`/`<audio>`.

The same pass is a health check. A book is *readable* if its main page has real content (200+ characters or 8+ links once cleaned) or its item list isn't empty. It is *searchable* if it carries `_ftindex:yes`, or a probe search finds something other than its home page, or (for document collections) its PDFs are in our text index. Cards show this as Ready, Indexing…, Browse only, Search only or Can't open, with a plain-English note. Item counts are honest ("12 documents", not "1 article"). The findings are stored with the ZIM's UUID, so the next start shows them at once.

### D14 · Library ranking: rank fusion, intent priors, optional semantic rerank
Xapian scores aren't comparable across books, our PDF index has its own BM25 scores, and the old search simply concatenated per-language groups, so Stack Exchange's many short posts often crowded out WikiMed. `retrieval.py` (pure functions, unit-tested with fakes) now does the ranking:

- **Reciprocal-rank fusion** over the title lookup (weight 2), the PDF-page index and each Xapian group. A multi-book Xapian result is split per book first, so each book's best hit starts level. K = 10 rather than the textbook 60, because our lists are short (≤ 20) and K = 60 flattens them until only the priors matter.
- **Intent priors**: a cue-word classifier (medical, repair, survival, travel, tech, define) multiplies scores per collection, within about ×0.45–×1.5. "How do I stop bleeding" lifts Medicine (WikiMed, the medical PDFs) above Q&A, and "replace a cracked screen" lifts iFixit. With no intent, Q&A starts at ×0.85.
- **Semantic rerank (optional)**: when the bge-m3 embedding server is *already running*, the top 20 candidates' title + snippet are embedded with the query in one call and blended 50/50 (min-max normalized) with the fused score. Search never starts the server (that costs RAM and seconds); a failed or slow call falls back to the fused order and isn't retried for 20 s.
- **Passages**: paragraphs are scored with BM25 over lightly stemmed query terms (IDF from the article's own paragraphs, title words damped), plus credit for a matching section heading or intent synonym ("treat" → Management). When embeddings are up, the best 8 are blended 60/40 with embedding similarity. A PDF passage is drawn from the cited page, plus the next page only where it is relevant, and the citation says "pp. 111–112" when it uses both.

Latency budget, per library search: Xapian groups and the title lookup run in parallel (typically 50–300 ms on the reference library); the FTS5 page query takes under 10 ms (measured 1–10 ms on 3,400 indexed pages); fusion takes under 1 ms. The optional rerank is capped at 1.2 s and each passage's embedding at 0.8 s. With the embedding server down, ranking adds about 10 ms; the worst case adds about 2 s.

### D15 · PDF text lives in a separate, rebuildable SQLite cache, extracted out of process
Extracted text is a cache of the ZIMs, not personal data, so it goes in `data/library-index.sqlite` rather than a `mimi.db` migration. It can be deleted at any time, it stays out of backups of personal data, and bulk inserts never hold the chat database's lock. The FTS5 table uses the Porter tokenizer; rows are keyed by ZIM name, path and page, and keep the PDF's printed page label ("Where There Is No Doctor" physical page 312 is printed page 265; physical page 50 is page 3 after the w1–w32 front section). A label table with repeats can't identify a page, so then physical numbers are used. Page 0 of each document holds its title, author and description, so videos and scans are still found by title. A document is re-read only when its ZIM's UUID changes.

pypdf is pure Python, so extraction runs one document at a time in a below-normal-priority worker process (spawned, as on Windows) instead of a thread that would hold Core's GIL. The two sample libraries (19 PDFs, 3,444 pages) took about 75 s on the first start and 12.5 MB of index; nothing is redone on later starts. PDFs over 200 MB and pages beyond 3,000 are skipped.

### D16 · ZIM content is untrusted: sandbox it, and only frame PDFs
`render_reader` output is rendered with `{@html}`, so it keeps only http(s)/mailto links (made inert), relative links and in-ZIM media. Every other URL scheme is removed: `javascript:`, `vbscript:`, `data:` (except `data:image/` in `<img>`), `file:` and the rest, including disguised forms like `java\tscript:`. It also drops `iframe`, `object`, `embed`, `form` and `base`, and removes duplicate namespaced attributes (an SVG `<a>` with both `href` and `xlink:href`). The `/kiwix` proxy serves ZIM HTML, SVG and scripts with `Content-Security-Policy: sandbox`, so a ZIM page opened directly can't act with Mimi's origin and cookies. PDFs and media get `frame-ancestors 'self'` so the reader can show them in an iframe; nothing else can be framed.
