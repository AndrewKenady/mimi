# MIMI — Machine Intelligence, Minus the Internet

*An open-source, fully offline AI field station. The name nods to **Mímir**, the Norse keeper of wisdom whose counsel Odin carried.*

MIMI turns a small PC (the reference device is a handheld ONEXPLAYER F1) into an AI assistant that works with **zero internet**:

- **Ask anything**, answered by a local open-weights model (Gemma 4 12B by default) with **citations** from an offline library: all of English Wikipedia (with images), WikiMed, iFixit, Wikivoyage, Stack Exchange, a dictionary, survival guides, classic books and TED talks.
- **Remembers you**, transparently: every memory can be reviewed, edited, paused or wiped.
- **Voice conversation**, Whisper speech-to-text plus Kokoro text-to-speech, all on-device.
- **Scribe** records and transcribes meetings, then writes a summary, key points and action items.
- **Lens** reads text in photos and lets you ask about what the camera sees.
- **Maps and "what's near me"** use offline OpenStreetMap tiles, GeoNames and geotagged Wikipedia.
- **"Connect to MIMI"**: phones nearby join over Wi-Fi and use it at `https://mimi.local`.
- **Portable**: the same folder runs from a USB drive on any Windows PC.

> Status: early development (v0.1). See [docs/PLAN.md](docs/PLAN.md) for the full design.

## Layout

This folder is both the git repository and the portable install. Large content is git-ignored and fetched by scripts.

```
core/      MIMI Core: Python/FastAPI backend (models, library, memory, voice, maps, sharing)
ui/        The MIMI app UI (SvelteKit)
shell/     MIMI.exe, a thin native Windows window (WebView2)
config/    Model catalog, modes
scripts/   Setup, downloads, data builds
docs/      Plan, architecture, decisions, benchmarks
bin/ python/ models/ zim/ maps/ data/ logs/   (git-ignored runtime and content)
```

## Running (development)

```powershell
# backend (serves the UI too) on http://127.0.0.1:7600
cd core; ..\python\python.exe -m mimi serve
```

## License

MIT for MIMI's own code. Bundled models and content have their own licenses (see [docs/PLAN.md](docs/PLAN.md#12-licensing-checklist-open-source-non-commercial-distribution)). MIMI is **non-commercial**: some bundled content (e.g. TED talks) forbids commercial use, so MIMI drives and images may not be sold.
