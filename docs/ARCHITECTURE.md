# MIMI architecture

MIMI is three pieces that live in one portable folder:

```
 ┌──────────────── MIMI.exe (shell/) ─────────────────┐   phones on the MIMI Wi-Fi
 │ WinForms + WebView2 window: full screen, tray,     │   ───────────────┐
 │ splash, hotkeys; starts Core if it isn't running   │                  │ https://mimi.local
 └──────────────────────┬─────────────────────────────┘                  ▼
                        │ http://127.0.0.1:7600          ┌──── share server (:443, local CA) ────┐
                        ▼                                 │  same FastAPI app, guests & users     │
 ┌──────────────── MIMI Core (core/mimi) ─────────────────┴───────────────────────────────────────┐
 │ FastAPI · SQLite (WAL) · event bus → WebSocket /api/events · SSE chat streams                  │
 │                                                                                                 │
 │ chat.py ── tool loop ──► tools.py: search_library · read_article · show_reference_image         │
 │    │                              search_my_files · remember · where_am_i · nearby_places       │
 │    │                              get_directions · calculate                                    │
 │    ▼                                                                                            │
 │ llm.py  ModelManager ──► llama-server (Vulkan/CUDA/CPU, --fit) :7610   one chat model resident  │
 │                      └─► llama-server --embedding (CPU build)   :7611   bge-m3, idles out        │
 │ kiwix.py KiwixService ──► kiwix-serve :7620 over zim/*.zim  → passages + reader HTML             │
 │ memory.py · mydocs.py (FTS5 + vectors) · scribe.py (faster-whisper) · voice.py (Kokoro)         │
 │ lens.py (RapidOCR) · location.py (GPS/NMEA, geodata.py) · routing.py (Valhalla) · share.py       │
 └─────────────────────────────────────────────────────────────────────────────────────────────────┘
                        ▲ static files (ui/build)
 ┌──────────────── MIMI app (ui/) ────────────────────┐
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
6. The assistant message is stored with its sources, tool trail, memories used, model and timings. The UI then refetches the canonical thread, including answer versions.

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
| `data/` | `mimi.db` (users, chats, memories, settings), uploads, library, notes, certs, WebView2 profile | no (personal) |
| `logs/` | component logs | no |

## Security model

- Core listens on **127.0.0.1:7600** only. On that port the device owner is signed in automatically, unless "Require PIN" is on.
- The **share server** (0.0.0.0:443) serves the same app to the local network. There, every request needs a session: an account (name plus password or PIN) or a guest.
- Guests get temporary chats, no memory, only the features the owner allows, and a per-hour message limit.
- The engines (llama-server, kiwix-serve) bind to loopback and are never exposed to the network.
- Child processes run inside a Windows Job Object and die with Core.
