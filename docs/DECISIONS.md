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
