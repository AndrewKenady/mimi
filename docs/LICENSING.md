# Licensing

Mimi's own code (everything in this repository) is under the [MIT License](../LICENSE).

The repository contains no models, engines, maps or library content. The installers
(`scripts/install.py`, `scripts/setup.ps1`) and the content manager (`scripts/content.py`) download them
from their original publishers, pinned with checksums in [`manifests/`](../manifests/) (`runtimes.json`,
`packs.json`, the `lite.json` and `standard.json` tiers) and [`config/models.json`](../config/models.json),
and each keeps its own license. The licenses below are as published upstream when these
versions were pinned; check the upstream project for current terms before redistributing.

**Mimi is non-commercial.** The code is MIT, but some content Mimi downloads (the TED
collections and iFixit) is licensed for non-commercial use only, so a Mimi drive or disk image that
includes it may not be sold. Leave that content out (see `scripts/make_drive.py`) if you
need a commercially redistributable build.

## Models

| Component | License |
|---|---|
| Gemma 4 12B / 26B-A4B (Google) | Apache-2.0 |
| Qwen3.5 4B / 9B, Qwen3.6 35B-A3B, Qwen3.8 27B | Apache-2.0 |
| bge-m3 (embeddings) | MIT |
| Whisper models via faster-whisper (Systran conversions) | MIT |
| Kokoro-82M (text to speech) | Apache-2.0 |

## Engines and tools

| Component | License | Note |
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

| Collection | License |
|---|---|
| Wikipedia, Wikivoyage, Wiktionary, WikiMed (mdwiki) | CC BY-SA |
| Stack Exchange sites | CC BY-SA |
| iFixit | CC BY-NC-SA |
| TED talks | CC BY-NC-ND (shipped unmodified) |
| Project Gutenberg shelves | Public domain in the US; Gutenberg's trademark terms apply |
| zimgit collections (post-disaster, medicine, water, food, knots) | Per document; see each ZIM's metadata |

## Map and place data

| Data | License | Attribution shown |
|---|---|---|
| OpenStreetMap (map tiles, routing graph, street names) | ODbL 1.0 | "© OpenStreetMap contributors" on the map |
| Protomaps basemap (tiles build, style) | Data ODbL; style BSD-3-Clause | "Protomaps" on the map |
| GeoNames | CC BY 4.0 | In the app's attributions |
| Wikipedia coordinates (geotags) | CC BY-SA 4.0 | |
| US Census TIGER/Line address ranges | Public domain | |
| US ZIP centroids (Nominatim, from Census data) | Public domain | |
| Statistics Canada National Address Register | Statistics Canada Open Licence | |

## Bootable USB image

The USB image (`scripts/image/build.sh`, see [INSTALL.md](INSTALL.md#bootable-usb)) is a
Debian 13 system with Mimi installed. Besides Mimi and the engines above, it contains
Debian packages, each under its own license; every package's copyright file is kept in
the image at `/usr/share/doc/<package>/copyright`, and each build writes the exact list of
packages and versions next to the image (`<name>.packages.txt`).

| Component | License | Note |
|---|---|---|
| Debian packages from `main` (Linux kernel, GRUB, systemd, NetworkManager, PipeWire, ...) | DFSG-free licenses (GPL-2.0, LGPL, MIT, BSD and others) | Debian publishes the source of every version at [snapshot.debian.org](https://snapshot.debian.org) |
| Chromium | BSD-3-Clause and the licenses of its bundled components | Debian's build |
| cage | MIT | |
| Mesa (OpenGL, Vulkan drivers) | MIT | |
| Noto fonts | SIL OFL 1.1 | |
| shim, signed GRUB and kernel | GPL-2.0+ / BSD-2-Clause (shim) | Signed by Debian; shim also by Microsoft, so Secure Boot accepts it |
| **Firmware and CPU microcode** (Debian's `non-free-firmware`: AMD, Intel and NVIDIA graphics; Intel, Realtek, Atheros, Broadcom and MediaTek Wi-Fi; Intel/SOF laptop audio; Intel and AMD microcode) | **Not open source.** Each vendor's own license, which permits redistribution in unmodified form | Binary blobs loaded into the hardware, not code that runs on the CPU. The terms are in `/usr/share/doc/firmware-*/copyright` and `/usr/share/doc/*-microcode/copyright` in the image |

What this means if you pass the image on:

- The image as published (no content) contains nothing non-commercial; the firmware may be
  redistributed unmodified, as Debian does.
- Several packages are GPL. Sharing the image means sharing their binaries, so the GPL's
  source terms apply to you: keep the matching Debian sources available (the package list
  names every version, and snapshot.debian.org has them).
- An image built with `--tier` includes that tier's content and its licenses. The Lite tier
  includes iFixit (CC BY-NC-SA), so such an image may not be sold; see the top of this page.
