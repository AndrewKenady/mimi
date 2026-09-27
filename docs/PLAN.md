# Mimi: Machine Intelligence, Minus the Internet

*An open-source, non-commercial, fully offline AI field station, with the polish of a frontier AI app. The name is a nod to **Mímir**, the Norse oracle whose preserved head Odin carried and consulted for wisdom.*

**Network name:** `Mimi` · **Address:** `https://mimi.local`
**Reference device:** ONEXPLAYER F1 (Ryzen 7 7840U, Radeon 780M iGPU, 16 GB LPDDR5X, 512 GB NVMe, Wi-Fi 6E, Windows 11 Home)
**Plan date:** 2026-09-26

**What Mimi is:** a pocket AI that works with **zero internet**. It combines a capable multimodal LLM, offline Wikipedia (with images) and reference libraries, offline maps with a "what's near me" feature, note-taking, OCR, spoken conversation and personal memory. All of it lives in a **beautiful full-screen native app** that can launch at startup. Phones nearby join over Wi-Fi ("Connect to Mimi") and get the same app in their browser. The whole package also runs from a USB drive on any Windows PC.

---

## 1. Is it really offline?

**Yes, after setup.** You need internet exactly once, to download the software, models and data (best done at home on a fast connection). After that, every component runs locally:

| Component | Runs locally | Needs to be turned off to stay truly offline |
|---|---|---|
| LLM engine (llama.cpp + llama-swap) | Yes | Nothing (no telemetry, no auto-update) |
| Mimi Core + Mimi App (our own code) | Yes | Nothing. Offline-first by design: no CDNs, fonts and icons bundled, `HF_HUB_OFFLINE=1` |
| Kiwix (Wikipedia etc.) | Yes | Nothing |
| Maps (PMTiles) | Yes | Nothing (tiles are served from the device) |
| Whisper / Tesseract / Kokoro TTS | Yes | Nothing |
| Windows | Mostly | Pause Windows Update while in the field |

**Acceptance test:** Wi-Fi client mode off, hotspot or router only, cold boot, then exercise every feature from the device and from a phone (Phase 10).

### On `mimi.local` vs `mimi.ai`
Use **`mimi.local`**. It's the reserved suffix for local-network names, and devices resolve it over mDNS with no internet or DNS server. **Don't use `mimi.ai`** (or any real public domain): someone else owns it, a browser can't get a valid certificate for it offline, and online requests would go to the real site. Mimi advertises `mimi.local` itself (a zeroconf responder), so it works on any PC without renaming it. The QR card also encodes the raw IP address as a fallback.

---

## 2. Storage budget (reference device: D: 209.5 GB free, verified 2026-09-26)

Everything lives in **`D:\Mimi\`**, which is the same folder layout as the portable USB edition (section 11). C: keeps its free space for Windows.

| Category | Contents | Size |
|---|---|---|
| **Wikipedia** | `wikipedia_en_all_maxi` (full English, all ~6.9M articles **with images**) | ~110 GB |
| **Extra reference (Kiwix)** | Wikivoyage (with images), WikiMed (with images), iFixit, Wiktionary, Stack Exchange (DIY, Mechanics, Outdoors, Cooking) | ~10 GB |
| **Models** | Main: **Gemma 4 12B** (Q4_K_M + vision/audio projector) ~8.5 GB · Reader/alt: **Qwen3.5-9B** ~6.5 GB · Quick/voice: **Qwen3.5-4B** ~3 GB · embedding ~0.5 GB · Whisper large-v3-turbo + small ~2 GB · Kokoro/Piper TTS + wake word ~1 GB (section 13) | ~21.5 GB |
| **Runtimes** | llama.cpp + llama-swap, portable Python + Mimi Core, Mimi App (Tauri, ~15 MB), kiwix-tools, whisper.cpp, Tesseract, Caddy (**no Docker/WSL, no Open WebUI**) | ~5 GB |
| **Maps** | OpenStreetMap vector tiles for **the US + Canada** (PMTiles, z0–14) + an SQLite database of places and points of interest + a geotagged-Wikipedia index | ~22 GB |
| **Personal data** | `data\`: chats, memories, library, notes, recordings (Opus audio ~30 MB/hour), search indexes | ~5 GB to start |
| **Extras, tier 1** | Survival & preparedness ~2 GB · more Stack Exchange (Electronics, Ham Radio, Gardening, Physics, Super User) ~6 GB · Project Gutenberg curated subset ~5 GB | ~13 GB |
| **Subtotal on D:** | | **~186 GB** |
| **Headroom on D:** | Updates, growth, temp build files (staged one at a time, ≤ ~15 GB at once) | ~23 GB |

If the Phase 1 stretch test keeps **Gemma 4 26B-A4B (IQ3)** on the device (~10 GB), headroom drops to ~13 GB.

**Khan Academy + TED are included** (Mimi is non-commercial, which their CC BY-NC licenses allow). They're stored as **tier 2** (low-res, ~15–20 GB) in `C:\Mimi-extra\`, **after** you clear `C:\$WINDOWS.~BT` (Settings → System → Storage → Temporary files → "Previous Windows installation(s)"; this removes the option to roll back that upgrade). That takes C: from 35 → ~61 GB free, and after the extras it keeps ~40 GB free for Windows.
**Tier 3 (needs a 1 TB USB-C SSD):** the full Gutenberg (~70 GB+), full-resolution Khan/TED, planet-wide maps (~120 GB).

---

## 3. Memory budget (the real constraint)

16 GB total: ~12.7 GB is visible to Windows, and 3 GB is carved out as iGPU memory. With Vulkan offload, **the model fills the 3 GB carve-out first**, then spills into shared (GTT) system memory.

| Resident all the time | Windows-visible RAM |
|---|---|
| Windows + background | ~4 GB |
| Mimi App (WebView2) + Mimi Core + kiwix-serve + Caddy + mDNS/GPS | ~1.5 GB |
| Gemma 4 12B Q4_K_M + projector + 8k context (~9 GB total: 3 GB in the carve-out, ~6 GB shared) | ~6 GB |
| **Total** | **~11.5 of 12.7 GB** |

Rules that follow from this:
- **One LLM in memory at a time.** llama-swap loads models on demand and unloads idle ones (after ~10 min).
- **The main model is multimodal** (Gemma 4 12B: text + image + audio), so reading photos doesn't force a model swap.
- Quantize the KV cache (`-ctk q8_0 -ctv q8_0`) for 8–16k context.
- **Scribe batch jobs** don't run alongside a long chat. Voice mode uses Qwen3.5-4B plus small Whisper.
- **The UI has a performance budget** (section 5.8): it must stay smooth while the iGPU is busy generating text.

---

## 4. Architecture

```
                    ┌──────────────── Reference device / any PC ────────────────┐
                    │                                                           │
  Handheld screen ◄─┤  Mimi App  (MIMI.exe: Tauri 2 native shell, full-screen)  │
  gamepad · touch   │    ├─ supervises all services (start/stop/health/restart) │
  mic · speakers    │    ├─ tray, autostart, global hotkeys, gamepad bridge     │
                    │    └─ renders the Mimi UI (SvelteKit build, WebView2)     │
                    │                         │                                 │
                    │                         ▼                                 │
  Phones ──Wi-Fi────┼──► Caddy :443 (https://mimi.local, local CA) ─► same UI   │
  "Mimi"            │    (PWA, installable)   │                                 │
                    │                         ▼                                 │
                    │  Mimi Core :7600 (Python / FastAPI)                       │
                    │    ├─ chat orchestration + tool loop (SSE streaming)      │
                    │    ├─ memory · chats · users/roles · settings (SQLite)    │
                    │    ├─ RAG: sqlite-vec + FTS5 over library & notes         │
                    │    ├─ voice: VAD → Whisper → LLM → Kokoro (WebSocket)     │
                    │    ├─ Scribe jobs · Lens (OCR) · maps/GPS endpoints       │
                    │    └─ OpenAI-compatible /v1 endpoint (for dev + tinkerers)│
                    │        │            │              │                      │
                    │        ▼            ▼              ▼                      │
                    │   llama-swap    kiwix-serve    PMTiles + places.sqlite    │
                    │   :11434        :8081          geowiki.sqlite, GPS dongle │
                    │   (llama.cpp: Vulkan / CUDA / CPU build chosen at launch) │
                    │     ├─ Mimi: Gemma 4 12B   ├─ Quick: Qwen3.5-4B           │
                    │     ├─ Reader: Qwen3.5-9B  └─ embeddings                  │
                    └───────────────────────────────────────────────────────────┘
```

**Why our own app instead of Open WebUI:** a frontier-grade experience needs full control over design, motion, gamepad/handheld ergonomics, voice, memory and settings. Open WebUI's UI is generic, hard to deeply restyle, and its license requires keeping its branding. Replacing it with **Mimi App + Mimi Core** gives complete design freedom, drops ~3 GB of Python dependencies and a license constraint, and yields one codebase that serves the handheld, phones and desktops. During early phases, any OpenAI-compatible client (including Open WebUI, **as a dev tool only, never shipped**) can talk to Core's `/v1` endpoint for testing.

**Engine: llama.cpp + llama-swap (not Ollama).** These are single portable executables that run GGUF files from any folder. The Vulkan build accelerates AMD, NVIDIA and Intel GPUs. A Radeon 780M benchmark this year measured llama.cpp Vulkan at **~5–6× Ollama's generation speed** on the same model.

**Why HTTPS:** phone browsers only allow mic and camera on secure pages. Caddy serves a local certificate, and phones install the Mimi root certificate once from `/cert` (or tap through the warning; confirm this still enables the mic on iOS and Android). The native app on the device doesn't need this.

**Why Mimi searches Kiwix instead of an AI search index over Wikipedia:** embedding 6.9M articles would take days and 20–40 GB. `kiwix_search` uses Kiwix's full-text search, reads the top 3–5 articles, and answers **with citations**. The AI search index is only for your personal library, notes and memories.

### 4a. How images work
| Image source | Mimi reads it? | How |
|---|---|---|
| **Your photos** (documents, signs, receipts, plants, parts, handwriting) | **Yes, always** | **Lens** (camera or upload), handled by the main model or the Reader model |
| **Reference images, viewed by people** | n/a | Mimi's Library reader shows full articles with images |
| **Reference images, given to the model** | **Yes, on demand** | `kiwix_image(article)` passes an article's lead image to the model beside your photo |

Article images aren't sent automatically (each costs ~300–1,500 tokens and several seconds on the 780M). **Limit:** an 8B–12B vision model is a second opinion, **not a reliable identifier**. For mushrooms, plants, medications or anything safety-critical, Mimi shows the reference side by side and says its match is unverified.

### 4b. Persona
**Mimi**: calm, dry and quietly witty, never cutesy. It knows the Mímir story. Its rules are to cite sources from tool results, say "I don't know" without sources, flag safety-critical topics, and respect memory settings. The personality is adjustable in Settings (5.5), but the core rules aren't.

---

## 5. Mimi App: UI/UX design

**Bar:** it should feel like a frontier AI app (the calm confidence of Claude or ChatGPT, with the craft of a first-party OS app), designed around a **handheld** first, then phones and desktops. It should never feel like a dev tool.

### 5.1 Design principles
1. **Calm, fast, legible.** Typography does the work. Generous spacing, restrained color, no clutter. The answer is the hero.
2. **Show the thinking, not the plumbing.** Tool use appears as a quiet, elegant activity trail ("Searching Wikipedia · Reading 3 articles · Checking the map"), never as raw JSON.
3. **Trust through sources.** Every factual answer carries citation chips that open the source in-app. Mimi shows how it knows, not just what it knows.
4. **Offline is a feature, not an error.** Status is shown proudly ("Offline · All systems local"), and no feature pretends to need the internet.
5. **Three inputs, all first-class:** voice, gamepad and touch. Keyboard and mouse on desktop.
6. **Every pixel is local.** Bundled fonts, icons and imagery. Zero network requests to the outside world.

### 5.2 Visual identity
- **Motif: "the Well."** Mímir's well of wisdom becomes Mimi's living centerpiece: a softly luminous orb/pool that breathes when idle, ripples when listening (reacting to mic level), swirls when thinking, and pulses with the voice when speaking. It appears on Home, in Voice mode and as a small presence indicator in chat. It's rendered with WebGL/Canvas with a CSS fallback and respects reduced motion.
- **Palette:** dark-first ("deep water": ink blues and near-black, with a single luminous accent), plus a crisp light theme and a true-black OLED option. User-selectable accent colors.
- **Type:** a bundled variable sans for UI (e.g. Inter), a refined serif for long-form reading in the Library (e.g. Source Serif), and a mono for code. Fluid type scale tuned for an 8.8" screen at arm's length.
- **Iconography:** one consistent open-source icon set (e.g. Lucide/Phosphor), bundled.
- **Motion:** purposeful, 150–300 ms, spring-based, 60 fps. Streaming text fades in smoothly with no jank. Everything respects `prefers-reduced-motion`.
- **Design tokens** (color, type, spacing, radius, elevation, motion) are defined once, in Figma and in code (CSS variables), and drive every theme.

### 5.3 Surfaces
| Surface | What it does | Signature details |
|---|---|---|
| **Home** | Big "Ask Mimi" prompt around the Well, plus quick actions and widgets | Status strip: offline badge, battery, GPS fix, model/profile, guests connected. Customizable widgets: *Nearby*, *Recent notes*, *On this day* (from Wikipedia), *Continue reading* |
| **Chat** | The core conversation | Streaming markdown, citation chips with article thumbnails, inline images, tool-activity trail, stop/regenerate/edit-and-branch, per-message "memories used" and "sources" drawers, model switcher, attach photo/file |
| **Voice** | Full-screen spoken conversation | The Well fills the screen and reacts to your voice and Mimi's. Live captions for both sides. Push-to-talk hint mapped to a trigger. Tap to interrupt. Transcripts are saved to the chat |
| **Library** | Browse all offline knowledge in a Mimi-styled reader (not raw Kiwix pages) | Collections grid (Wikipedia, WikiMed, iFixit, Khan, TED, Gutenberg…), search with instant results, a beautiful reading mode (serif, adjustable size, dark sepia), "Ask Mimi about this article", video player for Khan/TED |
| **Map** | Full-bleed offline map | Live GPS dot, "Nearby" cards with Wikipedia summaries, tap anywhere to ask "what's here?", trip history (optional, privacy-controlled) |
| **Scribe** | Record, transcribe, summarize | Live waveform, speaker-friendly transcript with timestamps, auto summary/action items, notes list with search. Notes feed Mimi's knowledge |
| **Lens** | Camera or photo in, understanding out | Live camera (device or phone), OCR text overlay with copy, "Explain", "Translate", "Compare with reference" (side-by-side with a Wikipedia image) |
| **Memory** | Everything Mimi remembers about you (5.6) | Search, edit, pin, delete, "where it came from" |
| **Settings** | Robust, searchable settings (5.5) | Instant apply, per-section reset, import/export |

Global elements:
- **Command palette** (Ctrl/Cmd+K) to jump anywhere, run actions and search chats, notes and settings.
- **Quick Menu** (gamepad Guide/≡ button): a radial/overlay for mode switch, voice, volume, brightness, performance profile, share QR code, "Exit to desktop".
- **Notifications/toasts** for long jobs (a transcript is ready, reindex finished).

### 5.4 Input and form factors
- **Handheld (reference device):** landscape full-screen. **Full gamepad navigation** (spatial D-pad/stick focus with a clear, beautiful focus ring; A = select, B = back, X = voice, Y = Lens, LB/RB = switch surfaces, LT hold = push-to-talk, Start = Quick Menu). Touch targets ≥ 44 px. The Windows touch keyboard pops up automatically for text fields, and voice dictation is available in every text field.
- **Phones (PWA over the hotspot):** responsive mobile layout with bottom navigation, installable to the home screen, camera for Lens, mic for Voice and Scribe.
- **Desktop/laptop (portable edition):** windowed or full-screen, sidebar layout, full keyboard shortcuts.
- **One codebase, three layouts:** container-query-driven responsive design, tested at 375 px, 768 px, 1280×800 and 1920×1080.

### 5.5 Settings (robust, searchable, instant)
Device-level settings are admin-only (PIN). Personal settings are per user.

| Section | Settings |
|---|---|
| **General** | Launch at startup · open full-screen · "kiosk feel" (hide the desktop, exit only via the Quick Menu + PIN) · language · units (imperial/metric) · time format |
| **Appearance** | Theme (dark / light / OLED / auto) · accent color · wallpaper/Well style · font size and density · reading font · reduced motion · high contrast |
| **Assistant** | Personality sliders (concise ↔ detailed, formal ↔ casual, dry wit on/off) · custom instructions · response length · citation strictness · safety-topic behavior (always show sources) · default mode |
| **Modes** | Create and edit **Modes**: bundles of model + tools + knowledge collections + instructions (built-in: *Everyday*, *Road Trip*, *Field Medic*, *Fix-It*, *Study*, *Storyteller*) |
| **Models** | Profile (Auto / Lite / Standard / Plus / Max) · per-role model picker · context length · creativity (temperature) · "Run benchmark" · model storage view |
| **Voice** | Voice picker with preview · speed · wake word on/off and sensitivity · push-to-talk binding · interruptions (barge-in) · mic/speaker selection · read answers aloud automatically |
| **Knowledge** | Enable/disable collections · add folders to the personal library · reindex · per-collection priority · ZIM manager (add/remove packs) |
| **Maps & Location** | GPS device · map region packs · location history on/off/retention · home location (optional) |
| **Network & Sharing** | Share on/off · hotspot or router mode · SSID/password · show QR · connected devices · **guest permissions** (which surfaces guests get, rate limits, max concurrent) · certificate install page |
| **Accounts & Privacy** | Users and roles (admin / user / guest) · admin PIN · guest mode · **encrypt data at rest** (passphrase) · "leave no trace" mode (portable) · chat history retention · wipe or export my data |
| **Controls** | Gamepad mapping · keyboard shortcuts · haptics (if supported) |
| **Power** | Performance profile (Quiet / Balanced / Max, with a TDP hint) · battery saver (auto-switch to the Quick model and dim the Well below X%) · screen timeout |
| **Storage & Updates** | Disk usage by component · update from USB drive or online (manifest-verified) · backup and restore `data\` |
| **About & Diagnostics** | Health dashboard for every service · logs · version · licenses and attributions (Wikipedia, OSM, Khan, TED…) |

**How settings work under the hood:** one typed schema (Pydantic ↔ generated TypeScript types), stored in `data\mimi.db`, versioned with migrations, validated on write, applied live over a WebSocket (no restarts except where noted), **searchable** from the Settings page and the command palette, each section resettable, and the whole config importable/exportable as JSON.

### 5.6 User memory and history management
Modeled on the best frontier apps, but fully local and transparent.

- **What Mimi remembers:** facts, preferences and ongoing projects about each user (e.g. "drives a 2014 Tacoma", "prefers metric", "vegetarian").
- **How memories are made:**
  - **Explicit:** "remember that…", which is saved instantly.
  - **Suggested:** Mimi proposes a memory with an inline chip ("Remember this?" ✓/✗). The default setting is **ask before saving**, with *auto-save* or *off* as alternatives.
- **How they're used:** relevant memories (embedding + recency ranking, ~500-token budget) are added to Mimi's context. Every answer that used memory shows a subtle **"Memory used"** chip listing which ones, with a one-tap "forget this".
- **Memory page:** search, filter by category, edit inline, pin (always include), delete, see **"where it came from"** (link to the source chat), bulk select, **pause memory**, export (JSON/Markdown), **wipe all** (with confirmation).
- **Temporary chats:** incognito mode with no history and no memory reads or writes. It's the default for guests.
- **Chat history:** projects/folders, full-text search across all chats, pin, rename, archive, delete, export. Branching conversations when editing a past message.
- **Isolation:** memories and chats are per user. Guests get nothing persistent unless the admin allows it.
- **Security:** everything lives in `data\mimi.db`. Optional **encryption at rest** (SQLCipher, passphrase at launch) protects a lost USB drive.

### 5.7 Customization and extensibility
- Themes, accents, wallpapers and Well styles. Home widgets can be rearranged. Quick actions can be pinned.
- **Modes** (5.5), plus **prompt templates / slash commands** (`/summarize`, `/explain-like-5`, `/translate`).
- **Community tool API (open source):** tools are Python modules with a small manifest (name, description, JSON schema, permissions). Drop them in `tools\` and they appear in Settings → Tools, where they can be toggled per mode. Theme packs are JSON token files.
- **Startup behavior:** "Launch Mimi at startup" toggle (per-user `Run` registry entry on the reference device; it asks first in portable mode, because it writes outside the drive). "Open full-screen" and "kiosk feel" toggles. **Exit to desktop** is always available from the Quick Menu, protected by a PIN if set. (Windows 11 Home lacks Assigned Access kiosk mode, so this is an app-level full-screen experience rather than a locked OS shell.)

### 5.8 Quality bars
| Area | Target |
|---|---|
| Cold start (app visible) | < 2 s to an interactive Home (models warm in the background, with a progress shimmer on the Well) |
| Interaction latency | < 100 ms for any tap or press, 60 fps scrolling and animation **while the LLM is generating** |
| Bundle | Initial JS < 300 KB gzipped, with lazy-loaded surfaces (Map, Library reader, Well WebGL) |
| Accessibility | WCAG 2.2 AA: full keyboard/gamepad/screen-reader support, captions in Voice, scalable text, high contrast |
| Consistency | 100% token-driven styling. Visual regression tests (Playwright screenshots) on every surface × theme × layout |
| Offline purity | Automated test: the app makes **zero** non-local network requests |
| Resilience | If a service crashes, Mimi App restarts it and shows a graceful inline state, never a blank screen or stack trace |

### 5.9 Tech stack
- **Shell:** **Tauri 2** (Rust). A ~15 MB `MIMI.exe` using Windows' built-in WebView2, with native full-screen, tray, autostart plugin, global shortcuts, single-instance lock, and sidecar process supervision (it launches and monitors llama-swap, Core, kiwix-serve and Caddy). The WebView2 data folder is pinned inside `Mimi\data\` for portability.
- **UI:** **SvelteKit** (static build) + TypeScript + Tailwind with design tokens + an accessible headless component library (Bits UI / Melt UI) + Motion for animation + MapLibre GL + a custom WebGL "Well". Svelte keeps bundles small and fast on the handheld's shared GPU and on phones.
- **Gamepad:** the Web Gamepad API in the UI plus a spatial-navigation focus manager, with Tauri as a fallback for global hotkeys.
- **Core:** **Python 3.11 + FastAPI** (SSE for chat streaming, WebSockets for voice and live settings), SQLite (WAL) + **sqlite-vec** + FTS5, faster-whisper, Kokoro via ONNX Runtime, Tesseract, zeroconf.
- **Contracts:** an OpenAPI spec generates the TypeScript client, so UI and Core can't drift apart.

---

## 6. Hardware to buy

| Item | Why | Approx. cost |
|---|---|---|
| **USB-powered travel router** (GL.iNet Opal/Beryl class) | Field network. This Wi-Fi card reports `Hosted network supported: No`, and Windows Mobile Hotspot is unreliable without upstream internet. SSID `Mimi`, WPA2. | $30–60 |
| **USB GPS dongle** (u-blox 7/8) | No GPS hardware was detected on the device | ~$15 |
| **65 W+ USB-C PD car charger** + short cable | Expect 1.5–2 h of battery under AI load | ~$25 |
| USB-C hub with Ethernet (optional) | Wired link to the router | ~$25 |
| **500 GB–1 TB USB-C SSD** | The Mimi Full portable edition, and tier 3 content | $50–90 |

---

## 7. Build phases

Each phase ends with a check that must pass. **The handheld install *is* a Mimi Portable tree** at `D:\Mimi\`, with every path relative to that folder:

```
Mimi\
  MIMI.exe              native app + launcher + service supervisor (Tauri)
  Mimi.cmd              headless fallback launcher → scripts\launch.ps1 (servers/debugging)
  README.txt  LICENSES\  manifest.json (pinned versions + SHA-256 of every artifact)
  bin\win-x64\          llama-server (vulkan|cuda|cpu), llama-swap, kiwix-serve, whisper.cpp,
                        tesseract, caddy, pmtiles
  python\               portable CPython with Mimi Core + dependencies installed directly
  core\                 Mimi Core source (FastAPI) + tools\ (built-in and community tools)
  ui\                   built Mimi UI (static SvelteKit output; also served to phones)
  models\llm\  models\whisper\  models\tts\
  zim\                  *.zim
  maps\                 tiles.pmtiles, places.sqlite, geowiki.sqlite, style/fonts/sprites
  config\               templates (llama-swap.yaml, Caddyfile), profiles\ (lite|standard|plus|max)
  data\                 mimi.db (users, chats, memories, settings), library\, notes\, webview\
  scripts\              launch, stop, health, update, build-drive
  logs\
```

**Parallel track:** Phase 8 (design system in Figma) can start on day one alongside Phases 0–7.

### Phase 0: Prep (online, ~30 min)
- Create `D:\Mimi\`. Power: on AC, never sleep. Wi-Fi power saving off. Battery charge limit (~80%) if available. Set the computer name to `Mimi`.
- Fetch a portable CPython 3.11 into `Mimi\python\`. Install Rust + Node (dev machine only, for building the app).
- **Check:** `Mimi\python\python.exe --version` works from a different drive letter too.

### Phase 1: LLM engine + model selection (online, ~2 h)
- llama.cpp release builds (Vulkan, CPU, CUDA) + llama-swap into `bin\win-x64\`. Confirm Vulkan sees the **780M**.
- Performance profile **25–30 W on AC** (OneXConsole/RyzenAdj).
- Benchmark the section 13 line-up with a fixed Mimi prompt set: Q&A over provided context, a 3–5-step chained tool task, a summary, image reading.
  - **Main:** Gemma 4 12B (default) vs Qwen3.5-9B. Pick Gemma unless it misses the speed bar.
  - **Stretch:** Gemma 4 26B-A4B at IQ3 (~10 GB). Keep it only if memory stays < 90% committed through a 30-minute mixed session. **Expect it to fail on 16 GB.**
  - **Quick/voice:** Qwen3.5-4B vs Gemma 4 E4B (test E4B's native audio input).
  - **Embedding:** bge-m3 or nomic-embed-text.
- **Pass criteria:** main ≥ 8 tok/s, first token < 3 s at 4k, valid tool JSON in 9 of 10 runs, 5-step chains complete in 8 of 10, no paging.
- **Check:** results recorded in `docs\BENCHMARKS.md` and `config\profiles\standard.json`.

### Phase 2: Mimi Core foundation (~3–4 days)
- FastAPI app: chat with SSE streaming and a server-side tool loop, **OpenAI-compatible `/v1`** (for testing with any client), users/roles/sessions (admin PIN, user, guest), the typed **settings schema** with migrations and a live-update WebSocket, chats/projects/branches, and the **memory store** (explicit + suggested, retrieval, "memory used" metadata), all in `data\mimi.db`.
- RAG over `data\library\` (sqlite-vec + FTS5 hybrid search, embeddings via llama-server).
- Persona + Modes system prompts. The "Mimi" (main + tools), "Quick" and "Reader" model roles.
- **Check:** a test client can chat with streaming, remember and recall a memory, answer from a library PDF with a citation, and settings changes apply live. API tests pass.

### Phase 3: Offline knowledge (online for downloads, ~3–5 h + ~1 day of code)
- Download ZIMs (checksums recorded in `manifest.json`): Wikipedia `maxi`, Wikivoyage, WikiMed, iFixit, Wiktionary, Stack Exchange sets, survival pack, Gutenberg subset. **Khan Academy + TED** go to `C:\Mimi-extra\zim\`.
- `kiwix-serve --port 8081 zim\*.zim C:\Mimi-extra\zim\*.zim` (localhost only; Core proxies it for the Library reader).
- Core tools: **`kiwix_search`** (clean text + titles + links) and **`kiwix_image`** (lead image ≤ 768 px + caption). Library API: collections, search, article HTML sanitized for Mimi's reader.
- **Check:** "How do I treat a second-degree burn?" is answered citing WikiMed. The leaf-vs-red-maple comparison works. Text questions never call `kiwix_image`.

### Phase 4: Maps + location (online for downloads, ~2 h + ~1 day of code)
- US + Canada PMTiles + local fonts, sprites and style. Build `places.sqlite` (osmium) and `geowiki.sqlite` (Wikipedia geotags), then delete the source extracts.
- GPS service (NMEA → Core `/location`). Tools: **`where_am_i()`**, **`nearby_places(radius, kind?)`**. Optional trip history (privacy settings).
- Routing is out of scope (the build needs more than 16 GB of RAM). Use Organic Maps on a phone.
- **Check:** "What's interesting within 10 miles?" returns real places with summaries, with no internet.

### Phase 5: Networking: "Connect to Mimi" (~1–2 h)
- **Hotspot path first** (loopback adapter + Mobile Hotspot), then the **travel router** for the field. SSID `Mimi`, WPA2.
- zeroconf advertises `mimi.local`. Caddy :443 `tls internal` → the Mimi UI + Core API. `/cert` serves the root certificate. Firewall allows 443/80 only on the private profile. llama-swap, kiwix and TTS stay on localhost.
- The **QR card** is generated in-app (Settings → Network & Sharing → Show QR): join `Mimi`, open `https://mimi.local`, IP fallback.
- **Check:** an iPhone and an Android phone join via QR code on both paths. The UI loads. Mic works over HTTPS.

### Phase 6: Scribe + Lens (~2 days)
- whisper.cpp (Vulkan) `large-v3-turbo`/`small`. Scribe jobs: transcribe with timestamps, then summary/action items, then saved to `data\notes\` and indexed.
- Lens: Tesseract (fast) + Reader model (hard cases). `ocr_image` tool. Explain, Translate and Compare-with-reference actions.
- **Check:** a 10-minute recording is transcribed in ≤ 5 min and searchable. A printed page OCRs at ≥ 95% accuracy.

### Phase 7: Voice pipeline (~2–3 days)
- Core voice WebSocket: VAD (Silero) → STT (faster-whisper small/turbo) → Quick model streaming → **Kokoro-82M** (ONNX, CPU) sentence-by-sentence TTS. Piper as the light fallback.
- Push-to-talk (primary), optional wake word ("Mimi", custom openWakeWord model), barge-in (headset recommended), spoken filler during tool calls, one signature Kokoro voice for Mimi (user-changeable).
- **Latency target:** ~1.5–3 s to the first spoken word. Lookups add ~3–8 s, covered by the filler line.
- **Check:** 10 spoken turns in airplane mode, median ≤ 3 s to first word.

### Phase 8: Design system (parallel track, ~1–2 weeks)
- In **Figma**: brand (logo/wordmark, the Well), tokens (color, type, spacing, radius, elevation, motion) for dark/light/OLED, component library (buttons, inputs, chips, cards, sheets, toasts, focus rings for gamepad), and high-fidelity mockups of every surface in handheld, phone and desktop layouts, plus key flows: first-run onboarding, ask → cite → read, voice conversation, Lens compare, memory review, share via QR.
- Export tokens to code (CSS variables + a TypeScript theme). Prototype the Well animation.
- **Check:** a design review with a clickable prototype on the actual handheld screen, including a gamepad-only walkthrough of every flow.

### Phase 9: Mimi App v1 (~3–5 weeks)
- **Shell (Tauri 2):** full-screen/kiosk feel, tray, single instance, autostart toggle, global hotkeys, **service supervisor** (start order, health checks, auto-restart, logs), WebView2 data dir in `data\webview\`.
- **UI (SvelteKit):** every surface in 5.3, with command palette, Quick Menu, gamepad spatial navigation, responsive layouts, PWA manifest + service worker for phones, and theming from tokens.
- **First-run onboarding:** welcome with the Well → pick a voice → theme/accent → admin PIN → memory preference → "Share Mimi?" → a 30-second guided tour (gamepad-aware).
- Settings (5.5) and Memory (5.6) completed end to end, with import/export.
- **Quality gates (5.8):** Playwright visual regression across surfaces × themes × layouts, an accessibility audit (axe + manual screen reader), performance budgets in CI, and the zero-external-requests test.
- **Check:** a usability session with 3 people who've never seen Mimi (one on the handheld with gamepad, one on a phone, one on a laptop). Each completes 8 core tasks unaided, and the issues found get fixed.

### Phase 10: Hardening + field test (~2 days, then a real drive)
- "Launch at startup" on for the reference device (Windows auto-login to a local account). Mimi opens full-screen straight into Home.
- `health` dashboard in-app (+ `scripts\health.ps1`). `update` flow in-app (manifest-verified, only when online or from a USB update pack).
- Pause Windows Update for trips. Turn off Game Bar/overlays and Steam auto-start.
- **Offline acceptance test:** Wi-Fi client off, cold boot on battery, and **within 60 s of the desktop appearing, Mimi is on screen**. Within 3 min a phone can chat with citations, open a Wikipedia article in the Library, see its location on the Map, use Scribe and use Lens. On the handheld, Voice holds a conversation and gamepad-only navigation reaches every surface.
- **Real-world test:** a 1-hour drive through a known dead zone, logging failures, battery drain and UX friction.

### Phase 11: Package Mimi Portable (~2–3 days)
See section 11. Build Lite/Standard/Full drives, code-sign `MIMI.exe`, and test on at least three other PCs (an NVIDIA desktop, an Intel-graphics laptop, an old/CPU-only machine).

---

## 8. Downloads and time estimate

| Item | Size |
|---|---|
| Kiwix ZIMs (core + tier 1 extras) | ~133 GB |
| Khan Academy + TED (low-res, on C:) | ~15–20 GB |
| Map tiles (US + Canada) + OSM extracts (deleted after building indexes) | ~22 GB kept, ~12 GB temporary |
| Models + TTS (benchmark losers deleted) | ~21.5 GB kept, ~15 GB temporary |
| Software (engines, Python deps, app build) | ~5 GB |
| **Total transfer** | **~225 GB** (about 5–6 h at 100 Mbps, mostly unattended) |

**Build effort (realistic, for a polished v1):**
| Milestone | Scope | Effort |
|---|---|---|
| **v0.1 "It works"** | Phases 0–7 (engine, Core, knowledge, maps, network, Scribe/Lens, voice), tested with a dev client | ~1.5–2 weeks |
| **v0.5 "It's Mimi"** | Phase 8 design system + Phase 9 app with all surfaces functional | +3–4 weeks |
| **v1.0 "World-class"** | Polish, usability fixes, accessibility, performance, Phases 10–11 | +1–2 weeks |
| **Total** | | **~6–8 weeks** of focused work (longer part-time). Claude can do much of the implementation, and the design reviews and field tests need you. |

---

## 9. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Vulkan acceleration on the 780M underperforms | Test ROCm/HIP llama.cpp builds. The CPU fallback still gives ~5–8 tok/s on 9B |
| UI stutters while the iGPU is busy generating | Performance budget + testing *during* generation. The Well drops to a lightweight 2D mode under load. No heavy blur |
| Scope creep in the custom app | Milestones (v0.1 → v0.5 → v1.0). Any OpenAI client works against Core, so the app never blocks backend progress |
| Windows hotspot won't start offline | Loopback-adapter workaround, then the travel router |
| Phone mic/camera blocked on plain HTTP | Caddy HTTPS + Mimi root certificate via `/cert` |
| `.local` doesn't resolve on some phones | IP printed on the QR card |
| Model makes things up | Citations required from tool results. Sources are always visible. Safety topics always show the source |
| RAM pressure | One model at a time, Scribe as batch jobs, no Docker, memory shown in the health dashboard |
| Heat/throttling in a hot car | Keep it out of the sun. Performance profile control in the Quick Menu |
| Battery swelling | 80% charge limit, run from the car charger |
| Unwanted users | WPA2 + QR card, guest permissions and rate limits, admin PIN, engine not exposed, firewall allows 443 only |
| Lost USB drive exposes personal data | Optional encryption at rest (SQLCipher) + "leave no trace" mode |
| Recording people | Consent prompt on first Scribe use. Laws vary by state |
| SmartScreen/antivirus flags the portable app | Code-sign releases (free OSS signing via SignPath Foundation), publish checksums |

---

## 10. Decisions (made 2026-09-26)
1. **Name:** **Mimi: Machine Intelligence, Minus the Internet** (Mímir nod). SSID `Mimi`, `https://mimi.local`.
2. **Map region:** US + Canada.
3. **Network:** both. The Windows hotspot is built and tested first, and the travel router is added for field use.
4. **Access:** WPA2 password via QR card. Visitors self-register or use guest mode, and admin stays yours.
5. **Extras:** everything that reasonably fits, **including Khan Academy + TED**.
6. **Distribution:** open source, **non-commercial**, with a portable USB edition.
7. **Models:** Gemma 4 12B on the reference device, and stronger weights for bigger hosts (section 13).
8. **UI/UX:** a custom **Mimi App** (Tauri + SvelteKit) and **Mimi Core** (FastAPI) with frontier-app polish: full-screen, optional launch at startup, robust settings, user memory management, deep customization. **Open WebUI is dropped** from the shipped product.

---

## 11. Mimi Portable: run from a USB drive on any PC

**Goal:** plug a drive into any Windows 10/11 x64 PC, double-click **`MIMI.exe`**, and the full Mimi experience opens. **No install, no admin rights** for local use, **nothing written outside the drive**, and no trace left behind.

### 11.1 How it stays portable
- **Everything relative:** MIMI.exe resolves its own folder and passes drive-relative paths to every service. Configs are generated from templates at launch. No registry writes (except the opt-in "launch at startup").
- **Self-contained runtimes:** single-file native binaries + a relocatable CPython (packages installed directly, launched via `python -m`). WebView2 ships with Windows 10/11, and its data folder is pinned to `data\webview\`.
- **User data on the drive:** `data\mimi.db` + library + notes. Optional encryption at rest. **"Leave no trace" mode** uses a temporary data dir that's wiped on exit.
- **Filesystem:** exFAT or NTFS required (FAT32's 4 GB limit breaks Wikipedia and models). The build script checks this.

### 11.2 Launch flow (MIMI.exe)
1. The splash screen shows the Well, while Mimi **detects hardware**: RAM, GPU vendor/VRAM, CPU features, drive speed, free ports.
2. **Backend:** CUDA build for NVIDIA, Vulkan for AMD/Intel, CPU otherwise.
3. **Profile:**

   | Host | Profile | Main model |
   |---|---|---|
   | ≤ 8 GB RAM | **Lite** | Qwen3.5-4B (multimodal), Whisper small |
   | 16 GB RAM / 8–12 GB VRAM | **Standard** (reference device) | Gemma 4 12B + Qwen3.5-9B Reader + Qwen3.5-4B Quick |
   | 32 GB RAM or 16–20 GB VRAM | **Plus** | **Gemma 4 26B-A4B** Q4_K_M (MoE; ~25 tok/s even on a 780M with 32 GB) |
   | 24 GB+ VRAM, or 48 GB+ RAM/unified | **Max** | **Qwen3.8-27B** on GPUs/Apple Silicon · **Qwen3.6-35B-A3B** (MoE) on big-RAM machines without a strong GPU |

4. **Start services** in order with health checks, then Home appears (models warm in the background).
5. **Share** (optional, needs admin, asked explicitly): firewall rule, mDNS, Caddy, hotspot, with the QR code shown on screen.
6. **Clean exit:** stops all processes and removes any firewall rules it added.

`MIMI.exe --install-to <folder>` copies the tree to an internal SSD for faster loads. `Mimi.cmd` remains as a headless/server launcher.

### 11.3 Drive editions
| Edition | Drive | Contents | Approx. size |
|---|---|---|---|
| **Mimi Lite** | 64 GB thumb drive OK | Qwen3.5-4B + 9B, Wikipedia top articles (no images), iFixit + WikiMed + survival, one state/province of maps, Whisper small, Piper | ~45 GB |
| **Mimi Standard** | 128 GB (USB SSD recommended) | Standard-profile models, full Wikipedia text-only, core references, US + Canada maps, Whisper turbo, Kokoro | ~105 GB |
| **Mimi Full** | **500 GB minimum** (USB SSD) | Everything on the reference device (Wikipedia with images, all extras **including Khan Academy + TED**) **plus the Plus and Max weights** (Gemma 4 26B-A4B ~16 GB, Qwen3.8-27B ~19 GB, Qwen3.6-35B-A3B ~21 GB) | ~265 GB |

### 11.4 The open-source repo
```
mimi/
  app/             Tauri shell (Rust): window, tray, autostart, supervisor, gamepad bridge
  ui/              SvelteKit app: surfaces, components, tokens, themes, i18n
  core/            FastAPI: chat/tool loop, memory, settings, RAG, voice, scribe, lens, maps
  tools/           built-in tools (kiwix_search, kiwix_image, nearby_places, where_am_i, ocr_image)
                   + tool manifest spec for community tools
  design/          Figma links, exported tokens, brand assets, the Well prototype
  config/          templates (Caddyfile, llama-swap.yaml), persona + Modes prompts, profiles
  manifests/       lite.json, standard.json, full.json: pinned URLs, versions, SHA-256, licenses
  build/           build-drive.ps1: download → verify → assemble → format check → write drive
  tests/           API tests, Playwright visual/e2e, accessibility, offline-purity, perf budgets
  docs/            setup guide, QR card template, BENCHMARKS.md, hardware compatibility list
  LICENSE          MIT or Apache-2.0 for Mimi's own code
```
- The repo ships **code and manifests, not the content**. `build-drive.ps1 -Edition full -Target E:\` pulls every artifact from upstream (Kiwix mirrors, Hugging Face, Protomaps, GitHub releases), verifies checksums and assembles an identical Mimi drive.
- Releases: a signed `MIMI.exe` + UI bundle + manifests on GitHub Releases. Optional pre-built drive images via torrent later.

### 11.5 Later: other platforms
- **Linux:** Tauri + `bin/linux-x64/`, straightforward.
- **macOS (Apple Silicon):** Tauri + llama.cpp Metal. Unified memory makes Macs excellent Mimi hosts.
- **Bootable "Mimi OS" USB:** a live Linux image that boots straight into Mimi App full-screen on any x86 PC with zero footprint. It's the ultimate kiosk, as a stretch goal.

---

## 12. Licensing checklist (open-source, non-commercial distribution)

| Component | License (verify current) | Obligation |
|---|---|---|
| llama.cpp, whisper.cpp, llama-swap, Caddy, Tauri, SvelteKit, FastAPI | MIT / Apache-2.0 | Include notices |
| Kiwix tools | GPL-3.0 | Ship unmodified binaries with notice and source links |
| Open WebUI | n/a | **Not shipped** (optional dev tool only) |
| Wikipedia & Wikimedia ZIMs | CC BY-SA | Attribution in About + article footers; share-alike |
| OpenStreetMap data | ODbL | "© OpenStreetMap contributors" on the map; share-alike for places.sqlite |
| Stack Exchange | CC BY-SA | Attribution |
| Project Gutenberg | Public domain (US) + trademark terms | Follow Gutenberg's redistribution rules |
| Khan Academy / TED | CC BY-NC-SA / CC BY-NC-ND | **Included** (Mimi is non-commercial). Ship ZIMs unmodified (ND). The README states Mimi drives may not be sold |
| Default models (Gemma 4 12B / 26B-A4B, Qwen3.5-4B / 9B, Qwen3.6-35B-A3B, Qwen3.8-27B) | Apache-2.0 (verify each model card) | Include license + notice |
| Whisper, faster-whisper, Kokoro, sqlite-vec, SQLCipher (community) | MIT / Apache-2.0 / BSD | Include notices |
| Piper | Check the current repo (its license has changed across versions) | Verify before bundling; voices have individual licenses |
| Fonts & icons (Inter, Source Serif, Lucide/Phosphor) | OFL / ISC / MIT | Include notices |

---

## 13. Model line-up (researched 2026-09-26)

**Goal:** the most capable open weights that run *reliably* on the reference device, plus stronger weights the portable edition uses on bigger hosts. All the defaults are **Apache-2.0**.

### Why a 12B dense model and not something bigger on the handheld
The 780M's limit is **memory bandwidth** (~120 GB/s shared):
- **MoE models** are ideal for this chip. Gemma 4 26B-A4B has been measured at **~23–30 tok/s on a 780M**, but its Q4_K_M file is ~16 GB and it needs a **32 GB** machine.
- On **16 GB**, the model budget is ~9 GB, which fits the **best dense ~9–12B models** at Q4. A 26B MoE at 3-bit (~10 GB) is a stretch test, not the plan.
- Gemma 4 12B and Qwen3.5-9B **tie on overall intelligence** (Artificial Analysis Intelligence Index). **Gemma 4 12B** is better at long chained tool calls and handles text, images and audio in one model. **Qwen3.5-9B** is leaner, faster and strong on vision.

### Reference device (Standard profile, 16 GB)
| Role | Model | Quant / size | Expected speed* | Why |
|---|---|---|---|---|
| **Mimi (main)** | **Gemma 4 12B** (Jun 2026) | Q4_K_M + projector, ~8.5 GB | ~8–11 tok/s | Most capable model that fits reliably. Text + image + audio, strong chained tool use, 128K context |
| **Reader / fallback main** | **Qwen3.5-9B** (Feb 2026) | Q4_K_M + projector, ~6.5 GB | ~11–14 tok/s | Top sub-10B model, natively multimodal (MMMU-Pro 69.2) |
| **Quick / voice** | **Qwen3.5-4B** (or Gemma 4 E4B if it wins Phase 1) | Q4_K_M, ~3 GB | ~20–30 tok/s | Snappy voice mode. E4B's native audio input is worth testing |
| **Stretch** | Gemma 4 26B-A4B | IQ3, ~10 GB | ~20+ tok/s *if it fits* | Kept only if it passes the no-paging test |
| Embedding | bge-m3 / nomic-embed-text | ~0.5 GB | n/a | Library, notes and memory retrieval |

*These are estimates from bandwidth math and published 780M results. Phase 1 measures the real numbers.

### Bigger hosts (portable edition)
| Profile | Model | Size (Q4_K_M) | Notes |
|---|---|---|---|
| **Plus** (32 GB RAM or 16–20 GB VRAM) | **Gemma 4 26B-A4B** | ~16 GB | MoE (~4B active), 256K context, vision. Fast even on iGPUs |
| **Max: GPU/Apple** (24 GB+ VRAM or 48 GB+ unified) | **Qwen3.8-27B** (Aug 2026) | ~18 GB + projector | Newest Qwen generation, dense, text + image + video |
| **Max: big RAM, no strong GPU** (48–64 GB+) | **Qwen3.6-35B-A3B** | ~21 GB | MoE with ~3B active, fast on CPUs/iGPUs |

Qwen3.8's smallest model is 27B, so the 16 GB tier stays on Gemma 4 / Qwen3.5. `manifest.json` pins each GGUF and its SHA-256. The in-app updater can swap in newer releases after they pass the Phase 1 benchmark.

### Sources
- Gemma 4 family, including the 12B released 2026-06-03 (Apache-2.0): https://en.wikipedia.org/wiki/Gemma_(language_model)
- Qwen3.5 small models (0.8B–9B, natively multimodal, Apache-2.0): https://artificialanalysis.ai/articles/qwen3-5-small-models
- Gemma 4 12B vs Qwen3.5-9B: https://artificialanalysis.ai/models/releases/comparisons/gemma-4-12b-vs-qwen3-5-9b · https://www.betterclaw.io/blog/gemma-4-12b-vs-qwen-3-5-9b
- Qwen3.8 line-up (no sub-27B variants): https://codersera.com/blog/qwen-3-8-model-lineup-2026/
- Gemma 4 26B-A4B on a Radeon 780M with llama.cpp Vulkan (~23–30 tok/s; 5–6× Ollama): https://github.com/ggml-org/llama.cpp/discussions/24222
