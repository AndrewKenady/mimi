# Installing Mimi

Mimi runs on your own machine and needs the internet only while it downloads. Pick a
**tier** (how much to download) and a **map region**, install, and add more content any
time later.

| | Command |
|---|---|
| **Linux, macOS** | `curl -fsSL https://raw.githubusercontent.com/AndrewKenady/mimi/main/scripts/install.sh \| sh` |
| **Windows 10/11** | `git clone https://github.com/AndrewKenady/mimi` then `powershell -ExecutionPolicy Bypass -File mimi\scripts\setup.ps1 -Tier lite` |
| **Docker** | `docker compose up -d` in a checkout, then `docker compose run --rm mimi content add lite` |

Then open **http://localhost:7600**.

- [What's tested](#whats-tested)
- [Tiers](#tiers) · [Regions](#regions)
- [Linux and macOS](#linux-and-macos) · [Windows](#windows) · [Docker](#docker) · [Steam Deck](#steam-deck)
- [Adding and removing content](#adding-and-removing-content) · [Content on another drive](#content-on-another-drive)
- [Portable drive](#portable-drive) · [Updating](#updating) · [Uninstalling](#uninstalling)
- [How downloads are verified](#how-downloads-are-verified) · [Troubleshooting](#troubleshooting)

## What's tested

Be clear-eyed about this list: Mimi is developed on one Windows handheld, and everything
else is newer.

| Platform | Status |
|---|---|
| Windows 11 x64 (reference device: 16 GB RAM, Radeon 780M, Vulkan) | **Daily use** by the maintainer. `setup.ps1` (the version in this repo) has been reviewed and parsed, not yet re-run end to end on Windows. |
| Linux x64 (Debian 12, Ubuntu 24.04), CPU | **Tested**: `install.sh` from a bare Debian container (uv, Python, engines, Node, UI), the engines, Core startup with and without content, a real book download, a map extract, the places and routing builds. No GPU was available in testing. |
| Docker (Linux x64) | **Tested**: both image targets build; compose, owner sign-in, content in the volume, clean shutdown. GPU passthrough is untested. |
| Linux arm64 (Raspberry Pi 5, Ampere, Jetson…) | **Untested.** The engines are official upstream builds with pinned hashes. |
| macOS on Apple silicon | **Untested.** Engines are pinned. Mimi uses llama.cpp's Metal build only once Core learns the `metal` backend; until then chat runs on the CPU (slower, but works). |
| Steam Deck (SteamOS 3, desktop mode) | **Untested**; see [Steam Deck](#steam-deck). |
| Intel Macs, 32-bit, Windows on ARM | Not supported. |

Tried it somewhere new? Open an issue with what worked and what didn't. It helps others.

## Tiers

| Tier | Download | What you get | Needs |
|---|---|---|---|
| **lite** (default) | **≈ 16–24 GB**, depending on the map region (UK 17 GB, US 20 GB, US + Canada 24 GB) | Qwen3.5 4B (chat, tools, reads photos), BGE-M3 search, Whisper small + Kokoro voice · WikiMed, iFixit, survival guides (post-disaster, first aid, water, food, knots), Wikivoyage, the most-read Wikipedia articles (text) · world map to country/city level, your region down to streets, places database | 8 GB RAM, any 64-bit CPU from about 2015 |
| **standard** | **≈ 210–245 GB**, plus a few hours of local builds | lite + Gemma 4 12B and Qwen3.5 9B, Whisper turbo · all of Wikipedia with pictures, Wiktionary, Stack Exchange (DIY, mechanics, outdoors, cooking, gardening, ham radio, electronics, physics, Super User), TED talks, Gutenberg · the world at town level, your region with every street, Wikipedia on the map, offline driving directions, street-address search (US/Canada) | 16 GB RAM (the reference device); a GPU helps |
| **none** | ≈ 100 MB | Code and engines only; add packs one by one | |

Every tier is just a list of **packs** (`manifests/lite.json`, `manifests/standard.json`,
packs in `manifests/packs.json`). See them all with `content list`.

## Regions

The map, the places database and driving directions cover one region. The world map
and everything else (models, books) are the same everywhere.

| Region | Map, lite (zoom 13) | Map, standard (zoom 14) | Directions (built) | Street addresses |
|---|---|---|---|---|
| `us` (lower 48, default for lite) | 4.2 GB | 8.8 GB | ~14 GB | yes |
| `canada` | 5.3 GB | 10 GB | ~4 GB | yes |
| `us-canada` (default for standard) | 7.8 GB | 15.6 GB | ~18 GB | yes |
| `uk` (with Ireland) | 0.8 GB | 1.5 GB | ~2 GB | no |
| `germany` | 1.8 GB | 3.5 GB | ~3.5 GB | no |
| `france` | 2.3 GB | 4.5 GB | ~3.8 GB | no |
| `australia` | 0.5 GB | 1.0 GB | ~0.9 GB | no |
| `new-zealand` | 0.2 GB | 0.3 GB | ~0.3 GB | no |
| `japan` | 0.9 GB | 1.7 GB | ~2 GB | no |
| any area: `--bbox W,S,E,N` | measured before download | | no | no |

Map sizes were measured on the August 2026 map build; direction sizes are estimates.
Maps work anywhere on Earth (Protomaps is global). Driving directions are built on your
machine from OpenStreetMap extracts (Geofabrik) for named regions. **Street-address search
exists only for the US and Canada**, because it is built from US Census TIGER and the
Statistics Canada address register; elsewhere you can still search places, towns,
landmarks and coordinates.

## Linux and macOS

```sh
curl -fsSL https://raw.githubusercontent.com/AndrewKenady/mimi/main/scripts/install.sh | sh
# options go after `sh -s --`:
curl -fsSL https://raw.githubusercontent.com/AndrewKenady/mimi/main/scripts/install.sh | sh -s -- --tier lite --region uk
```

This installs into `~/mimi` (set `MIMI_DIR` to change that) without sudo and without
touching the rest of the system: uv (a Python manager, pinned and checksummed) and
Python 3.12 live in `~/mimi/.tools`, Mimi's packages in `~/mimi/python`. From a checkout,
run `sh scripts/install.sh` or, with your own Python 3.11+, `python3 scripts/install.py`.

Useful options (`python3 scripts/install.py --help` lists them all):

| Option | |
|---|---|
| `--tier lite\|standard\|none` | how much content (default lite) |
| `--region NAME` / `--bbox W,S,E,N` | map region |
| `--no-routing`, `--no-addresses` | skip the long standard-tier builds |
| `--desktop` | add Mimi to the app menu (Linux) |
| `--dry-run` | show the plan and the disk-space check, change nothing |

Start Mimi with `~/mimi/python/bin/mimi serve` and open http://localhost:7600 (or use
the app-menu entry from `--desktop`). The first visit creates the owner account.

Requirements: `curl` or `wget`, `tar`, and for the UI build either Node 20+ or nothing
(a pinned Node is fetched). Linux needs glibc 2.35+ (Ubuntu 22.04, Debian 12, Fedora 36,
SteamOS 3 or newer). For a GPU on Linux, install your distribution's Vulkan driver
(`mesa-vulkan-drivers` for AMD/Intel, the NVIDIA driver's Vulkan ICD for NVIDIA);
`mimi doctor` shows whether Mimi sees it.

## Windows

```powershell
git clone https://github.com/AndrewKenady/mimi
powershell -ExecutionPolicy Bypass -File mimi\scripts\setup.ps1 -Tier lite -Region us
```

`setup.ps1` without `-Tier` installs the standard tier as before. Other switches:
`-NoContent`, `-NoRouting`, `-NoAddresses`. It builds `MIMI.exe`, the native app: double-click
it. No administrator rights are needed. Add content later with
`python\python.exe scripts\content.py add <pack>`.

## Docker

```sh
git clone https://github.com/AndrewKenady/mimi && cd mimi
docker compose up -d                                   # build and start; open http://localhost:7600
docker compose run --rm mimi content add lite          # or: add lite --region uk
docker compose restart mimi                            # load the new content
```

The image (~2 GB) holds Core, the UI and the engines; everything you download, plus
accounts, chats and logs, lives in the `mimi-data` volume at `/data`, so upgrades are a
rebuild (`git pull && docker compose up -d --build`) and nothing is lost. To keep content
on a particular disk, replace the volume with a host folder in `docker-compose.yml`
(writable by uid 1000).

**GPU.** Use `target: vulkan` and pass the GPU in (`devices: [/dev/dri]`, plus the
`render` group); commented examples for AMD/Intel and NVIDIA are in `docker-compose.yml`.
This is untested so far; without a GPU Mimi runs on the CPU.

**Sign-in and security: read this before changing ports.** Mimi treats requests from
the machine it runs on as "the device itself": the owner is signed in automatically,
first-run setup is allowed, and that screen approves phones. Everyone else must sign in.
Inside a container no browser is ever on loopback: your browser's requests arrive from
the Docker network's gateway. The compose file therefore:

1. publishes port 7600 on **127.0.0.1 only**, so only this machine can reach it, and
2. sets `MIMI_LOCAL_PEERS=172.31.76.1`, the gateway of the fixed network it creates, so
   this machine's browser counts as the device. The Host header must still be
   `localhost`/`127.0.0.1` and no foreign Origin is accepted; other containers on the
   network are not trusted (tested).

Don't publish 7600 on all interfaces while `MIMI_LOCAL_PEERS` is set: with rootless
Docker or some proxy settings, connections from other machines can also arrive from the
gateway address and would be signed in as the owner. To reach Mimi from other devices,
use Mimi's sharing listener (Settings → Share, HTTPS on 8443, everyone signs in) by
publishing `8443:8443`; mDNS (`mimi.local`) does not cross Docker's network, so use the
host's IP address. On a headless server, reach the device screen through an SSH tunnel:
`ssh -L 7600:127.0.0.1:7600 server` and open http://localhost:7600 on your laptop. If the
fixed subnet `172.31.76.0/24` clashes with one of your networks, change it and
`MIMI_LOCAL_PEERS` together. If setup says "Set up Mimi on the device itself", the gateway
doesn't match: check `docker network inspect mimi_mimi`.

## Steam Deck

Untested so far, but nothing here needs root, so it should work in **desktop mode**:

1. Hold the power button → Switch to Desktop, open Konsole.
2. Run the Linux one-liner with `--desktop` added, e.g.
   `curl -fsSL https://raw.githubusercontent.com/AndrewKenady/mimi/main/scripts/install.sh | sh -s -- --tier lite --desktop`
   SteamOS's read-only system isn't touched: everything goes to `~/mimi` (SteamOS
   updates don't wipe your home folder).
3. Start **Mimi** from the app menu (it starts Core and opens the browser). To use it in
   Game Mode, add `~/mimi/python/bin/mimi-desktop` as a non-Steam game.

The Deck's GPU should be used through Vulkan (RADV ships with SteamOS); with 16 GB of
shared memory the lite models fit comfortably. To keep content on the microSD card, set
`MIMI_CONTENT` (below), ideally on an ext4-formatted card (exFAT works; FAT32 can't hold
files over 4 GB). If something in SteamOS gets in the way, the same installer works inside
a distrobox container (`distrobox create -i debian:12`).

## Adding and removing content

```sh
mimi content list                     # every pack, its size, whether you have it
mimi content status                   # what's installed, disk use, free space
mimi content regions                  # map regions and their sizes
mimi content add wikipedia-full       # add a pack (or a whole tier: add standard)
mimi content add map-region-detail --region germany
mimi content add map-region --bbox -111.1,40.9,-104.0,45.1
mimi content remove ted               # delete a pack's files
mimi content verify                   # re-check installed files against their hashes
```

`mimi` is `~/mimi/python/bin/mimi` on Linux/macOS; elsewhere use
`python scripts/content.py` (Windows: `python\python.exe scripts\content.py`; Docker:
`docker compose run --rm mimi content ...`). Before downloading, `add` totals what's
missing, compares it with the free space on the content drive and stops if it won't fit
(with 2 GB to spare). Choosing a different region replaces the current detailed map
after asking. Interrupted downloads resume when you run the same command again. Restart
Mimi (Settings → Restart services) to load new books and maps.

## Content on another drive

Set `MIMI_CONTENT` to a folder for `models/`, `zim/` and `maps/`, both when installing
and when running Mimi. The Linux/macOS installer remembers it in the `mimi` launcher.

```sh
MIMI_CONTENT=/mnt/bigdisk/mimi python3 scripts/install.py --tier standard
```

## Portable drive

`python scripts/make_drive.py E:\ --edition lite` copies a working install to a USB drive
or SSD (see `--help`: lite/standard/full, `--map-bbox`, `--max-gb`). Drives made on
Windows run on any Windows 10/11 PC via `MIMI.exe`. On Linux/macOS the copy works too, but
the Python environment isn't relocatable: on the target machine run
`scripts/install.sh --tier none` from the drive once (it recreates `python/`; no content
is downloaded). Format the drive exFAT or NTFS/ext4, not FAT32.

## Updating

- Linux/macOS: run the one-liner again (or `sh scripts/install.sh`): `git pull`, then
  only what changed (new engine versions, packages, UI) is redone.
- Windows: `git pull`, then `setup.ps1` again.
- Docker: `git pull && docker compose up -d --build`.

Books (ZIM files) aren't updated automatically yet: `content remove <pack>` then
`content add <pack>` fetches the newest release.

## Uninstalling

- Linux/macOS: stop Mimi, `rm -rf ~/mimi` (and your `MIMI_CONTENT` folder if you set one),
  and `rm ~/.local/share/applications/mimi.desktop` if you used `--desktop`.
- Windows: turn off Settings → General → Launch at startup (removes the sign-in task),
  close Mimi, delete the folder.
- Docker: `docker compose down -v` (`-v` deletes the volume with all content and
  accounts) and `docker image rm mimi:local`.

Your accounts, chats and memories are in `data/` (Docker: `/data/user`); keep a copy if
you want them back later.

## How downloads are verified

- **Engines and models** are pinned to exact releases (llama.cpp `b11205`, kiwix-tools
  3.8.1, pmtiles 1.31.2; Hugging Face files by commit revision, never `main`) and checked
  against the sha256 recorded in `manifests/` (`runtimes.json`, `packs.json`). uv and
  Node.js are pinned with their sha256 in the installers.
- **Books** resolve to the newest release in the Kiwix catalog and are checked against
  the sha-256 in Kiwix's metalink; Kiwix's mirrors are used as fallbacks.
- **Maps** are cut from a pinned Protomaps build and must pass `pmtiles verify`. OSM
  extracts for directions are checked against Geofabrik's `.md5`.
- Known gaps: the map fonts/icons archive is pinned to a git commit but GitHub generates
  the zip, so it has no published hash; the Statistics Canada address file has no hash
  yet (its server wasn't reachable when the manifest was pinned).

Every file downloads to `name.part`, resumes with an HTTP range request, is verified, and
only then gets its real name. A file that fails its check is deleted, never used.

## Troubleshooting

- **`mimi doctor`** prints what Core sees: hardware, GPU backend, models, books, maps.
  Logs are in `logs/` (Docker: `/data/logs`; `docker compose logs mimi`).
- **"Not enough space"**: `content status` shows what's using the drive; remove packs,
  pick a smaller region, or move content with `MIMI_CONTENT`.
- **Downloads fail behind a corporate proxy** that inspects TLS: point `SSL_CERT_FILE` at
  its CA bundle (and `HTTPS_PROXY` at the proxy) before running the installer. For Docker
  builds, pass the CA with `docker build --secret id=ca,src=ca.pem`.
- **The GPU isn't used** (`"backend": "cpu"` in `mimi doctor`): on Linux check that
  `vulkaninfo` lists your GPU (install the Vulkan driver/loader); then delete
  `data/hardware.json` and restart Mimi.
- **Port 7600 is taken**: `MIMI_PORT=7700 mimi serve`.
- **Docker: "Set up Mimi on the device itself"**: see the [Docker](#docker) notes
  (`MIMI_LOCAL_PEERS` must be the network's gateway, and use `localhost` in the browser).
- **Docker: permission denied on /data** with a host folder: `sudo chown -R 1000:1000 <folder>`.
- **The page says the UI hasn't been built**: run the installer again with `--rebuild-ui`.
- **An older Windows install** left half-finished downloads: just run `setup.ps1` (or
  `content add`) again. Files cut short by the old downloader are detected by size and
  finished, not trusted.
