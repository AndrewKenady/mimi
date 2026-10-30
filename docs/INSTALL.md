# Installing Mimi

Mimi runs on your own machine and needs the internet only while it downloads. Pick a
**tier** (how much to download) and a **map region**, install, and add more content any
time later.

| | Command |
|---|---|
| **Linux, macOS** | `curl -fsSL https://raw.githubusercontent.com/AndrewKenady/mimi/main/scripts/install.sh \| sh` |
| **Windows 10/11** | `git clone https://github.com/AndrewKenady/mimi` then `powershell -ExecutionPolicy Bypass -File mimi\scripts\setup.ps1 -Tier lite` |
| **Docker** | `docker compose up -d` in a checkout, then `docker compose run --rm mimi content add lite` |
| **Any PC, nothing to install** | Write the [bootable USB image](#bootable-usb) to a stick and start the PC from it |

Then open **http://localhost:7600** (the USB stick opens Mimi by itself).

- [What's tested](#whats-tested)
- [Tiers](#tiers) · [Regions](#regions)
- [Linux and macOS](#linux-and-macos) · [Windows](#windows) · [Docker](#docker) · [Steam Deck](#steam-deck) · [Bootable USB](#bootable-usb)
- [Adding and removing content](#adding-and-removing-content) · [Content on another drive](#content-on-another-drive)
- [Portable drive](#portable-drive) · [Updating](#updating) · [Uninstalling](#uninstalling)
- [How downloads are verified](#how-downloads-are-verified) · [Troubleshooting](#troubleshooting)

## What's tested

Be clear-eyed about this list: Mimi is developed on one Windows handheld, and everything
else is newer.

| Platform | Status |
|---|---|
| Windows 11 x64 (reference device: 16 GB RAM, Radeon 780M, Vulkan) | **Daily use** by the maintainer. `setup.ps1 -NoContent` has run end to end on Windows 11 from a fresh clone (Python, engines, app UI and MIMI.exe; Core then serves the app). A full tier's content download through `setup.ps1` hasn't been re-run since. |
| Linux x64 (Debian 12, Ubuntu 24.04), CPU | **Tested**: `install.sh` from a bare Debian container (uv, Python, engines, Node, UI), the engines, Core startup with and without content, a real book download, a map extract, the places and routing builds. No GPU was available in testing. |
| Docker (Linux x64) | **Tested**: both image targets build; compose, owner sign-in, content in the volume, clean shutdown. GPU passthrough is untested. |
| Linux arm64 (Raspberry Pi 5, Ampere, Jetson…) | **Untested.** The engines are official upstream builds with pinned hashes. |
| macOS on Apple silicon | **Untested.** Engines are pinned; chat uses llama.cpp's Metal (GPU) build, falling back to the CPU build. |
| Steam Deck (SteamOS 3, desktop mode) | **Untested**; see [Steam Deck](#steam-deck). |
| [Bootable USB image](#bootable-usb) (x86-64 PCs) | **Boots in QEMU; not yet tried on real hardware.** Built here and booted from an emulated USB stick with UEFI and Secure Boot enforced, plain UEFI and legacy BIOS (software emulation, no GPU): Mimi Core answers about 70 s after power-on, the kiosk browser shows Mimi's first-run screen, the stick grows to fill a bigger disk, nothing listens on the network, and the first-boot download waits for a connection. The "USB image" workflow runs the same test on every image it builds; on GitHub's runners (with KVM) Mimi Core answers about 30 s after power-on, with Secure Boot and with BIOS. Untested: real PCs, Wi-Fi, graphics and Vulkan drivers, sound, cameras, and the first-boot download over a real connection. |
| Plus and Max tiers (32 GB+ RAM or a 16 GB+ GPU) | **Untested** on real hardware. The downloads are pinned and hashed, and the model settings follow the upstream recommendations, but no one has run these models in Mimi yet. |
| Addresses outside the US and Canada; fuel stations and hospitals | **Tested** on small real OpenStreetMap areas (central Vaduz, Monaco, Andorra, San Marino, Jersey, Appenzell Innerrhoden, central Heidelberg); not yet on a whole country of the regions below. See [Regions](#regions). |
| Intel Macs, 32-bit, Windows on ARM | Not supported. |

Tried it somewhere new? Open an issue with what worked and what didn't. It helps others.

## Tiers

| Tier | Download | What you get | Needs |
|---|---|---|---|
| **lite** (default) | **≈ 16–24 GB**, depending on the map region (UK 17 GB, US 20 GB, US + Canada 24 GB) | Qwen3.5 4B (chat, tools, reads photos), BGE-M3 search, Whisper small + Kokoro voice · WikiMed, iFixit, survival guides (post-disaster, first aid, water, food, knots), Wikivoyage, the most-read Wikipedia articles (text) · world map to country/city level, your region down to streets, places database | 8 GB RAM, any 64-bit CPU from about 2015 |
| **standard** | **≈ 210–245 GB**, plus a few hours of local builds | lite + Gemma 4 12B and Qwen3.5 9B, Whisper turbo · all of Wikipedia with pictures, Wiktionary, Stack Exchange (DIY, mechanics, outdoors, cooking, gardening, ham radio, electronics, physics, Super User), TED talks, Gutenberg · the world at town level, your region with every street, Wikipedia on the map, offline driving directions with the nearest fuel stations, hospitals, clinics and pharmacies, street-address search | 16 GB RAM (the reference device); a GPU helps |
| **plus** | standard **+ 15 GB** | standard + Gemma 4 26B A4B (a mixture of experts with about 4B active parameters, so it stays quick on integrated graphics) | 32 GB RAM, or a GPU with 16 GB+ |
| **max** | standard **+ 22 GB** | standard + Qwen3.6 35B A3B (about 3B active parameters) | 48 GB+ RAM, or a GPU with 24 GB+ |
| **none** | ≈ 100 MB | Code and engines only; add packs one by one | |

Every tier is just a list of **packs** (`manifests/lite.json`, `manifests/standard.json`,
packs in `manifests/packs.json`). See them all with `content list`.

**Books in Spanish or French** come on top of any tier: `content add library-es` (Wikipedia
Médica, Wikiviajes, iFixit en español and the most-read Spanish Wikipedia articles, 5.5 GB)
or `library-fr` (the French equivalents, 6.2 GB), and `wikipedia-es-nopic` or
`wikipedia-fr-nopic` for all of that language's Wikipedia as text (about 13 GB each). When
you write in Spanish or French, Mimi searches those books in your language and the English
ones in English.

**Plus and Max** add one bigger model to Standard. Mimi detects the hardware and picks the
Plus or Max profile by itself (Settings → Intelligence shows which), and it uses the Standard
models until the bigger one is installed; Settings then names the pack to add, for example
`content add llm-plus`. With a GPU that has 24 GB+ or Apple silicon with 48 GB+, the
`llm-max-dense` pack (Qwen3.8 27B, which also reads photos) is an alternative for Max; Mimi
prefers it when it is installed. Without such a GPU it is several times slower than the
35B A3B.

## Regions

The map, the places database and driving directions cover one region. The world map
and everything else (models, books) are the same everywhere.

| Region | Map, lite (zoom 13) | Map, standard (zoom 14) | Directions (built) | Street addresses |
|---|---|---|---|---|
| `us` (lower 48, default for lite) | 4.2 GB | 8.8 GB | ~14 GB | yes (TIGER) |
| `canada` | 5.3 GB | 10 GB | ~4 GB | yes (NAR) |
| `us-canada` (default for standard) | 7.8 GB | 15.6 GB | ~18 GB | yes (TIGER, NAR) |
| `uk` (with Ireland) | 0.8 GB | 1.5 GB | ~2 GB | OpenStreetMap |
| `germany` | 1.8 GB | 3.5 GB | ~3.5 GB | OpenStreetMap |
| `france` | 2.3 GB | 4.5 GB | ~3.8 GB | OpenStreetMap |
| `australia` | 0.5 GB | 1.0 GB | ~0.9 GB | OpenStreetMap |
| `new-zealand` | 0.2 GB | 0.3 GB | ~0.3 GB | OpenStreetMap |
| `japan` | 0.9 GB | 1.7 GB | ~2 GB | no |
| any area: `--bbox W,S,E,N` | measured before download | | no | no |

Map sizes were measured on the August 2026 map build; direction sizes are estimates.
Maps work anywhere on Earth (Protomaps is global). Driving directions are built on your
machine from OpenStreetMap extracts (Geofabrik) for named regions.

**Near me.** Towns, parks, peaks and landmarks come from GeoNames and Wikipedia (the
`places` and `geowiki` packs). The nearest **fuel stations, hospitals (with whether they
have an emergency department), clinics, pharmacies and ambulance stations** come from the
same OpenStreetMap extract as driving directions, so they arrive with the `routing` pack
(`maps/pois.sqlite`, a few MB for most regions); nothing extra is downloaded. Without it
(Lite), Mimi says it has no fuel data and can only offer GeoNames' list of hospitals. If
you installed directions before this version, `content add routing` builds just the new
table, which downloads the extract once more.

**Street addresses.** In the US and Canada they come from US Census TIGER and the
Statistics Canada address register, as before. In the UK, Germany, France, Australia and
New Zealand they come from OpenStreetMap's address points in the region's extract (the
one directions use: with the standard tier it is downloaded once for both). Search
understands the local forms: "Hauptstraße 5, 10115 Berlin", "Hauptstr. 5" or
"Hauptstrasse 5", "10 rue de la Paix, 75002 Paris", "Calle Mayor 12, Madrid", "Via Roma 1,
Milano", "10 Downing Street, London SW1A 2AA", "Sydney NSW 2000". Coverage is whatever
OpenStreetMap has mapped: close to complete in Germany, patchy in parts of the UK. This
was tested end to end on real OpenStreetMap data for Liechtenstein (Vaduz), Switzerland
(Appenzell Innerrhoden), Monaco, Andorra, San Marino, Jersey and central Heidelberg, not
yet on a whole country of the five regions. Japan has no address search: its addresses
are numbered blocks rather than house numbers on named streets. Everywhere, you can still
search places, towns, landmarks and coordinates.

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
| `--no-routing`, `--no-addresses` | skip the long standard-tier builds (no routing also means no fuel/hospital table) |
| `--desktop` | add Mimi to the app menu (Linux) |
| `--dry-run` | show the plan and the disk-space check, change nothing |

Start Mimi with `~/mimi/python/bin/mimi serve` and open http://localhost:7600 (or use
the app-menu entry from `--desktop`). The first visit creates the owner account.

Requirements: `curl` or `wget`, `tar`, and for the UI build either Node 22.17+ or nothing
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

## Bootable USB

A ready-made disk image that starts an ordinary 64-bit PC straight into Mimi, full
screen, with nothing to set up. It is a minimal Debian 13 ("trixie") with Mimi installed
the same way `install.sh --tier none` installs it, and it never touches the computer's
own disk. Take the stick out and the computer is as it was.

**You need** a USB stick of at least 8 GB (32 GB or more if it should download the Lite
tier onto itself; 64 GB is comfortable), and a PC with an x86-64 processor and 8 GB of
RAM. UEFI and older BIOS PCs are both supported, and Secure Boot can stay on. The model
can run on AMD and Intel graphics through Mesa's Vulkan drivers; NVIDIA cards get Mesa's
open NVK driver, which may work but hasn't been tried. Otherwise it runs on the processor.

### Writing it to a stick

Download `mimi-<version>-usb-x86_64.img.xz` and its `.sha256` from the
[latest release](https://github.com/AndrewKenady/mimi/releases/latest) (the first is
[0.2.0](https://github.com/AndrewKenady/mimi/releases/tag/v0.2.0), 918 MiB), or from the
artifacts of a "USB image" workflow run, or [build it yourself](#building-your-own).
Writing it erases everything on the stick.

- **balenaEtcher** (Windows, macOS, Linux): *Flash from file*, pick the `.img.xz`, pick
  the stick, *Flash*. It unpacks the file as it writes.
- **Rufus** (Windows): pick the stick under *Device*, *SELECT* the `.img.xz`, *START*.
  Rufus writes disk images as they are (DD mode).
- **dd** (Linux, macOS): check the download, find the stick (`lsblk` on Linux,
  `diskutil list` on macOS) and write it to the whole device, not a partition:

  ```sh
  sha256sum -c mimi-<version>-usb-x86_64.img.xz.sha256      # macOS: shasum -a 256 -c
  xz -dc mimi-<version>-usb-x86_64.img.xz | sudo dd of=/dev/sdX bs=4M conv=fsync status=progress
  # macOS: diskutil unmountDisk /dev/diskN, then ... | sudo dd of=/dev/rdiskN bs=4m
  ```

### First boot

1. Plug the stick into the PC while it's off, turn it on, and choose the stick in the
   boot menu (usually F12, F11, F10, F9 or Esc right after power-on; some PCs call it
   "UEFI: <stick name>").
2. On the first start the stick grows its main partition to fill itself, which takes a
   few seconds. There is no menu or login: Mimi opens full screen. The first visit creates
   the owner account, as on any install.
3. The screen counts as "the device", so whoever sits at it is signed in as the owner. If
   other people can reach the PC, turn on Settings → Require PIN.

Secure Boot: the stick boots through Debian's shim, which is signed by Microsoft's
third-party UEFI certificate. Most PCs trust it; some Windows 11 "Secured-core" laptops
don't by default. If the PC refuses the stick, allow "Microsoft 3rd-party UEFI CA" in the
firmware settings, or turn Secure Boot off.

### Content

The image has no books, maps or models: they are 16 to 245 GB, and GitHub release files
are limited to 2 GB. Instead, a stick built without content downloads the **Lite tier**
(US map region) by itself, in the background, as soon as it's online, using the same
content manager as `mimi content add lite`. Mimi runs meanwhile and shows its usual empty
and indexing states; when the download is complete, Mimi Core restarts once to load
everything. Settings → Logs → `content-download.log` shows the progress. Without a
connection it checks again every 15 minutes, and a download cut short by a reboot resumes.

- **Getting online**: a network cable, or an Android phone sharing its connection over
  USB (USB tethering), works with no setup. For **Wi-Fi**, plug the stick into any
  computer before starting from it: it shows a small drive called **MIMI**. Open
  `wifi.txt` there, fill in the network name and password, and save. At the next start
  Mimi saves the network and puts the blank form back, so the password doesn't stay on
  the stick.
- **Space**: Lite needs about 16 to 24 GB on top of the system, so the download only
  starts on a stick of 32 GB or more. On a smaller one it says there isn't room and stops
  trying; Mimi still runs, without content.
- **More content** can't be added from the stick's screen yet (there is no shell). Build
  your own stick with the content included, below.

### Building your own

The image is built by one script from this repository, on Debian 12+ or Ubuntu 22.04+
(about 15 GB of free disk, root for loop devices and mounts):

```sh
sudo apt-get install mmdebstrap debian-archive-keyring dosfstools mtools e2fsprogs fdisk xz-utils zstd
sudo scripts/image/build.sh                             # the published image, no content
sudo scripts/image/build.sh --tier lite --region uk     # Lite included: a stick that never needs the internet
scripts/image/build.sh --help
```

`--tier` bakes a tier's content into the image (for Lite about 25 GB, so it needs a
32 GB stick and about 60 GB free while building); those images are built locally, never
in CI. `--first-boot none` makes a stick that never downloads by itself. Every Debian
package comes from `scripts/image/packages.txt`; the files the image adds to Debian
(services, kiosk, browser policy) are in `scripts/image/rootfs/`, and the steps run inside
the image are in `scripts/image/configure.sh`. Each build also writes a list of the Debian
and Python packages it contains.

`scripts/image/boot-test.sh <image>` boots the result in QEMU, as CI does: it waits for
`GET /api/ping`, then checks that the built app is served, the kiosk opened the browser,
nothing listens on the network, the root partition grew, root's password is locked and no
service failed. It needs `qemu-system-x86 qemu-utils ovmf`, and uses KVM when it can.

### What's on the stick, and what isn't

- **Debian 13** with its kernel, CPU microcode and the firmware Debian's own live images
  ship for PCs (AMD, Intel and NVIDIA graphics; Intel, Realtek, Atheros, Broadcom and
  MediaTek Wi-Fi; laptop sound). See [LICENSING.md](LICENSING.md#bootable-usb-image).
- **Mimi Core** runs as its own unprivileged user (`mimi`) under systemd, on
  `127.0.0.1:7600` only. Sharing with phones (Settings → Share) stays off until the owner
  turns it on.
- **The screen** is [cage](https://github.com/cage-kiosk/cage) (a Wayland compositor that
  shows one app) running Chromium in kiosk mode, as a second unprivileged user (`kiosk`)
  that is signed in automatically and has no shell. Chromium may use the microphone and
  camera for Mimi only.
- **No SSH, no root password, no other login.** No account has a password, and no login
  prompt appears on the other consoles.
- **Not encrypted.** Anyone holding the stick can read what's on it, accounts and chats
  included (see [THREAT_MODEL.md](THREAT_MODEL.md)).
- **No automatic updates.** To update, write a newer image; that erases the stick,
  including accounts and downloaded content.
- **Known gaps**: the clock shows UTC, the keyboard layout is US, USB drives aren't opened
  automatically (so files can't be picked from one), and there is no on-screen way to
  change the Wi-Fi or shut down other than the power button.

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
