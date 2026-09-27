# Licensing

Mimi's own code (everything in this repository) is under the [MIT License](../LICENSE).

The repository contains no models, engines, maps or library content. `scripts/setup.ps1` and
`scripts/fetch.py` download them from their original publishers (pinned in
[`manifests/standard.json`](../manifests/standard.json) and [`config/models.json`](../config/models.json)),
and each keeps its own licence. The licences below are as published upstream when these
versions were pinned; check the upstream project for current terms before redistributing.

**Mimi is non-commercial.** The code is MIT, but some content Mimi downloads (the TED
collections and iFixit) is licensed for non-commercial use only, so a Mimi drive or disk image that
includes it may not be sold. Leave that content out (see `scripts/make_drive.py`) if you
need a commercially redistributable build.

## Models

| Component | Licence |
|---|---|
| Gemma 4 12B / 26B-A4B (Google) | Apache-2.0 |
| Qwen3.5 4B / 9B, Qwen3.6 35B-A3B, Qwen3.8 27B | Apache-2.0 |
| bge-m3 (embeddings) | MIT |
| Whisper models via faster-whisper (Systran conversions) | MIT |
| Kokoro-82M (text to speech) | Apache-2.0 |

## Engines and tools

| Component | Licence | Note |
|---|---|---|
| llama.cpp | MIT | |
| kiwix-tools (kiwix-serve) | GPL-3.0 | Used as unmodified binaries; source at github.com/kiwix/kiwix-tools |
| aria2 | GPL-2.0-or-later | Unmodified binary, used for downloads |
| go-pmtiles | BSD-3-Clause | |
| Valhalla (pyvalhalla) | MIT | |
| pyosmium / libosmium | BSD-2-Clause / BSL-1.0 | |
| faster-whisper | MIT | |
| kokoro-onnx | MIT | |
| RapidOCR | Apache-2.0 | |
| Python, uv, Node.js | PSF, MIT/Apache-2.0, MIT | Portable copies inside the Mimi folder |
| FastAPI, SvelteKit, MapLibre GL JS, Tailwind | MIT / BSD-3-Clause | npm and pip dependencies keep their own notices |
| Microsoft WebView2 SDK | Microsoft Software License | Redistributable components, used by `MIMI.exe` |
| Inter, Source Serif 4, JetBrains Mono, Noto (map labels) | SIL OFL 1.1 | |
| Lucide icons | ISC | |

## Library content (Kiwix ZIM files)

| Collection | Licence |
|---|---|
| Wikipedia, Wikivoyage, Wiktionary, WikiMed (mdwiki) | CC BY-SA |
| Stack Exchange sites | CC BY-SA |
| iFixit | CC BY-NC-SA |
| TED talks | CC BY-NC-ND (shipped unmodified) |
| Project Gutenberg shelves | Public domain in the US; Gutenberg's trademark terms apply |
| zimgit collections (post-disaster, medicine, water, food, knots) | Per document; see each ZIM's metadata |

## Map and place data

| Data | Licence | Attribution shown |
|---|---|---|
| OpenStreetMap (map tiles, routing graph, street names) | ODbL 1.0 | "© OpenStreetMap contributors" on the map |
| Protomaps basemap (tiles build, style) | Data ODbL; style BSD-3-Clause | "Protomaps" on the map |
| GeoNames | CC BY 4.0 | In the app's attributions |
| Wikipedia coordinates (geotags) | CC BY-SA 4.0 | |
| US Census TIGER/Line address ranges | Public domain | |
| US ZIP centroids (Nominatim, from Census data) | Public domain | |
| Statistics Canada National Address Register | Statistics Canada Open Licence | |
