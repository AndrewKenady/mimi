# Mimi architecture

Mimi is three pieces that live in one portable folder:

```
 ┌──────────────── MIMI.exe (shell/) ─────────────────┐   phones on the Mimi Wi-Fi
 │ WinForms + WebView2 window: full screen, tray,     │   ───────────────┐
 │ splash, hotkeys; starts Core if it isn't running   │                  │ https://mimi.local
 └──────────────────────┬─────────────────────────────┘                  ▼
                        │ http://127.0.0.1:7600          ┌──── share server (:443, local CA) ────┐
                        ▼                                 │  same FastAPI app, guests & users     │
 ┌──────────────── Mimi Core (core/mimi) ─────────────────┴───────────────────────────────────────┐
 │ FastAPI · SQLite (WAL) · event bus → WebSocket /api/events · SSE chat streams                  │
 │                                                                                                 │
 │ chat.py ── tool loop ──► tools.py: search_library · read_article · show_reference_image         │
 │    │                              search_my_files · remember · where_am_i · nearby_places       │
 │    │                              get_directions · calculate · community tools (tools/*.py)     │
 │    ▼                                                                                            │
 │ llm.py  ModelManager ──► llama-server (Vulkan/CUDA/CPU, --fit) :7610   one chat model resident  │
 │                      └─► llama-server --embedding (CPU build)   :7611   bge-m3, idles out        │
 │ kiwix.py KiwixService ──► kiwix-serve :7620 over zim/*.zim  → passages + reader HTML             │
 │ memory.py · mydocs.py (FTS5 + vectors) · scribe.py (faster-whisper) · voice.py (Kokoro)         │
 │ lens.py (RapidOCR) · location.py (GPS/NMEA, geodata.py) · routing.py (Valhalla) · share.py       │
 └─────────────────────────────────────────────────────────────────────────────────────────────────┘
                        ▲ static files (ui/build)
 ┌──────────────── Mimi app (ui/) ────────────────────┐
 │ SvelteKit SPA · Svelte 5 runes · Tailwind 4        │
 │ Home · Chat · Library · Map · Scribe · Lens ·       │
 │ Memory · Settings · Voice · onboarding · gamepad    │
 └────────────────────────────────────────────────────┘
```

## A chat turn

1. `POST /api/chats/{id}/messages` returns Server-Sent Events. The turn runs in its own task, so it finishes and is saved even if the client disconnects.
2. Relevant memories are retrieved (all of them when there are 8 or fewer; otherwise embedding similarity plus pinned ones).
3. The prompt is **cache-friendly**. A stable system prompt (persona, rules, mode) is followed by the history, which is replayed exactly as the model saw it. The per-turn facts (time, location, memories) go in a bracketed note on the *latest* message only, so llama.cpp reuses its KV cache for everything before it.
4. Questions that look factual force a tool call on the first step (`tool_choice: required`), so the answer is grounded in the library rather than the model's memory.
5. Tools return numbered sources. After generation, `sanitize_citations` removes any `[n]` that doesn't match a real source, and any reference list the model wrote itself.
6. The assistant message is stored with its sources, tool trail, memories used, model and timings. The UI then refetches the canonical thread, including answer versions. A memory counts as "used" (and gets a chip) only when the answer draws on it, meaning one of its distinctive words appears in the reply.

## Streaming protocol

A grounded answer takes 36–68 s on the reference handheld (see [BENCHMARKS.md](BENCHMARKS.md)), and most of that is the model reading the retrieved passages and then writing. The stream is shaped so the reader has something true to look at long before the first word: the sources as soon as the library search returns (a few seconds in, once the model has chosen its search), a verbatim excerpt alongside them, and a narrative of what is happening.

`POST /api/chats/{id|new}/messages` answers with Server-Sent Events, each `event: <name>` plus one JSON `data:` line. Clients must ignore events and fields they don't know; new ones are only ever added.

| Event | Data | When |
|---|---|---|
| `meta` | `chat_id`, `user_message`, `assistant_message_id`, `model`, `model_name`, `mode`, `title` | first, once the question is stored |
| `status` | `state`, `label`, `elapsed_ms`; optionally `tool`, `prompt_tokens`, `eta_ms`, `sources` | at each stage (below) |
| `tool` | `id`, `name`, `state: "start"` with `args`, `label`; then `state: "end"` with `label`, `summary`, `ok`, `ms`, `data` | around each tool call |
| `sources` | `sources`: every numbered source so far (`n`, `type`, `title`, `book_title`, `collection`, `url`, `image`, `snippet`) | as soon as a tool returns sources |
| `preview` | `n`, `type`, `title`, `book_title`, `collection`, `url`, `image`, `section`, `text` | once per turn, right after the first sources |
| `delta` | `text` | answer tokens |
| `reasoning` | `text` | thinking tokens (Think harder) |
| `memory` | `used` / `suggested` / `saved` | memory activity |
| `error` | `message`, `message_id` | the turn failed; `done` still follows if an answer was stored |
| `done` | `message` (the stored assistant message, with `meta`), `chat` | last |

`status.state` moves through `queued` → `loading` → `thinking` → `searching` (or `tool`) → `reading` → `writing`, repeating the middle steps if the model calls tools again. Labels are specific ("Searching Wikipedia and WikiMed for “hypothermia”…", "Reading “Hypothermia” (WikiMed) and 2 more…"). The `reading` status carries `prompt_tokens`, an estimate of what the model must now process, and `eta_ms` only when this device's prompt speed has been measured (from earlier answers' llama.cpp timings, prompts of 150+ tokens). Without a measurement no estimate is sent: a made-up number is worse than none.

`preview` is purely extractive: the paragraph of the top source's retrieved passage that best matches the question, cut at sentence boundaries (≤ 420 characters). The UI shows it as "From the source", marked as a quote and not Mimi's answer, and folds it away once the generated answer starts. It is also stored as `meta.preview`.

`regenerate` accepts an assistant message id (a new version of that answer) or a user message id (answer that question again, used by Try again when a turn failed before an answer was stored). `POST /api/chats/{id}/stop` cancels the running turn; whatever was generated is kept and stored with `meta.cancelled`.

In the browser, deltas are batched per animation frame and the markdown is rendered per top-level block (`renderBlocks` in `ui/src/lib/markdown.ts`): finished blocks are parsed and sanitized once and keep their DOM, so a long answer doesn't re-render from the top on every token and a reader's text selection survives. The thread is an ARIA log that is `aria-busy` while streaming; status changes go to a separate polite status region, so screen readers hear the stages and then the answer once, not every token.

## Tools and extensions

- Built-in tools live in `core/mimi/tools.py`. Each has a JSON schema, an availability check (for example, `get_directions` only appears once routing tiles exist) and a label for the activity trail. The owner can switch any of them off in Settings → Tools.
- **Community tools** are Python files in `tools/` (see [tools/README.md](../tools/README.md)). `plugins.py` reads each file's manifest (`NAME`, `DESCRIPTION`, `PARAMETERS`, `MIMI_API`, `SIDE_EFFECTS`, `USES`) statically with `ast`, so listing the folder never runs plugin code, and a file that can't be read is reported rather than crashing Core. A plugin reaches the model only after the owner enables it. Each call is checked against the declared parameter schema, then runs in a separate worker process that is killed at its timeout (45 s by default) and gets a small read-only context (user name, units, location, time, a private data folder, and an offline place lookup). Plugins that declare side effects are held back when a turn has read outside content unless the user's own message asks for them (see the security model below). `python -m mimi plugin check|test` is the author's harness.
- **Slash commands** (`ui/src/lib/commands.ts`) are prompt templates expanded in the browser, so history and the model only ever see plain text.

## The library

`kiwix.py` runs `kiwix-serve` over `zim/*.zim` (loopback only) and reads everything through its HTTP API: the OPDS catalog, `/content`, `/search` (Xapian) and `/suggest`.

- **Survey.** In the background after each start, and whenever the ZIM set changes, every book is classified as articles, documents (nautilus PDF/media collections), videos (TED) or books (Gutenberg). The last three have JavaScript-built home pages, so Core parses their data files (`database.js`, `assets/data_<lang>.js`, `full_by_popularity.js`) and the UI lists the items natively at `/library/book/<book>`. A health check records whether each book is readable and searchable, gives an honest item count and a short note, and `GET /api/library/books` returns these. See [D13](DECISIONS.md#d13--an-honest-library-survey-every-book-list-what-javascript-would-have-listed).
- **Document text.** `libindex.py` extracts PDF text page by page (pypdf, in a low-priority worker process) into `data/library-index.sqlite`, an FTS5 cache keyed by ZIM, path and page, with printed page labels. A document is read once per ZIM build. See D15.
- **Search.** `KiwixClient.search()` queries Xapian per language group, tries an exact-title lookup and searches the PDF pages, all in parallel. `retrieval.py` then fuses the lists by reciprocal rank with intent priors (medical questions favor Medicine, repairs favor iFixit). When the bge-m3 embedding server is already up, it also reranks the top 20 semantically, with a 1.2 s cap. See D14.
- **Passages and citations.** `passage()` picks paragraphs by BM25 (plus embedding similarity when available). A PDF hit is cited by page ("Where there is no Doctor, p. 265") and links to `/library/read/<book>/<file>.pdf#page=312`, which opens the browser's PDF viewer at that page.
- **Reader.** HTML articles are cleaned server-side (`render_reader`): scripts, frames and forms are dropped, and only http(s)/mailto and relative links survive. PDFs, video and audio are served by the `/kiwix` proxy, where only PDFs and media may be framed (by Mimi itself) and ZIM HTML/SVG is CSP-sandboxed. See D16.

## Memory and models

The reference device has 16 GB of RAM; about 3 GB of that is carved out for the iGPU, which the model can also use.

- **One chat model resident.** Switching roles (main → reader) swaps llama-server processes, and the UI shows "Waking up…".
- **Auto-fit.** `--fit on` lets llama.cpp choose how many layers go to the GPU, so a model still loads when other apps hold memory.
- **Voice, OCR and embeddings run on the CPU.** Whisper and Kokoro unload after 8 idle minutes, and the embedding server after 15.

## Data layout

| Path | What | Committed |
|---|---|---|
| `core/ ui/ shell/ config/ scripts/ manifests/ docs/` | source | yes |
| `bin/win-x64/` | llama.cpp builds, kiwix-tools, aria2, pmtiles | no |
| `python/` | portable CPython 3.12 + packages | no |
| `models/` | GGUF models, Whisper, Kokoro | no |
| `zim/` | offline library (Kiwix ZIM files) | no |
| `maps/` | `tiles.pmtiles`, fonts/sprites, `places.sqlite`, `geowiki.sqlite`, `routing/` | no |
| `data/` | `mimi.db` (users, chats, memories, settings), uploads, library, notes, certs, WebView2 profile; `library-index.sqlite` (PDF text from the ZIMs, a rebuildable cache) | no (personal) |
| `logs/` | component logs | no |

## Security model

The full threat model, with assets, attackers and residual risks, is in [THREAT_MODEL.md](THREAT_MODEL.md). For reporting, see [SECURITY.md](../SECURITY.md).

- **Two front doors.** Core listens on **127.0.0.1:7600**. There, the device owner is signed in automatically, unless "Require PIN" is on, and only when `is_local()` sees a loopback peer, a loopback `Host` (which blocks DNS rebinding) and no foreign `Origin`. The **share server** (0.0.0.0:443) serves the same app to the local network, where every request needs a session: an account, approve-on-device, or a guest. Setup, shutdown, the lock screen and approving sign-ins work only on the device.
- **Sign-in.** PINs and passwords are hashed with scrypt. Phones sign in with a password, a PIN of **6 or more digits** (a 4–5 digit PIN only unlocks the device's own screen), or **approve-on-device**: the owner taps Allow on the device, and the phone claims a one-time session with a random poll token. Wrong guesses are locked out per address and per account (browsers that signed in before are exempt from the account-wide budget, so a guess flood can't lock the owner's phones out), and the counters are stored in SQLite so a restart doesn't reset them. Sessions end on the server after 30 idle days or 180 days in total.
- **TLS.** A local CA, created on first use, signs the share server's certificate. The CA is **name-constrained** to `.local`/`localhost` and private addresses, so phones that install it can't be fooled into trusting it for real websites. It lasts 2 years, and its key is sealed with DPAPI on Windows (0600 elsewhere). An older unconstrained or unreadable CA is replaced at startup, and the share status shows a notice to re-install the certificate on phones.
- **Untrusted content.** Library passages (including user-written Stack Exchange answers), files and attachments reach the model inside `BEGIN/END UNTRUSTED` markers, with forged markers and chat-template tokens neutralized. A fixed system-prompt rule says that text is data, not instructions. After the model has read such content in a turn, `remember` becomes a suggestion the user approves, and side-effecting tools and directions run only if the user's own message asks for them.
- **Community tools** are discovered by reading their manifests, not by importing them. They're off until the owner enables them. Arguments are validated against the tool's schema, and each tool runs in its own worker process, which is killed when it overruns its timeout. Tools declare `SIDE_EFFECTS` and `USES` (`MIMI_API = 1`). This is isolation for robustness, not a sandbox.
- **Guests** get temporary chats, no memory, only the features the owner allows, and a per-hour message limit.
- **Engines** (llama-server, kiwix-serve) bind to loopback and are never exposed to the network. Child processes run inside a Windows Job Object and die with Core.
- **MCP.** `python -m mimi mcp` gives MCP clients on the device read-only access to search, articles, location and directions, through Core's loopback API ([MCP.md](MCP.md)).
