# Changelog

All notable changes to Mimi. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow [Semantic Versioning](https://semver.org/) once 1.0 ships. Tagged releases publish the top section as their notes.

## [0.2.0] — Unreleased

The release that makes Mimi checkable, installable anywhere and accessible.

### Trust: honest library, checked answers, measured quality
- **PDF collections open and are searchable.** The medical and survival guide collections (Kiwix "nautilus" ZIMs) used to be listed as available but opened to a blank page, and chat couldn't search them. They now open as native document lists, PDFs open in the app, and their text is indexed page by page, so answers can cite *"Where There Is No Doctor, p. 105"*. TED and Gutenberg collections list their talks and books too.
- **Every book shows an honest status:** Ready, Indexing…, Browse only, Search only or Can't open, with a plain-English reason and a real item count.
- **A book whose download stopped partway is held back from the shelf** (its ZIM header shows it's incomplete), and the Library says which file and how much arrived, instead of listing a book that fails when opened.
- **Citation checks in chat.** Each cited sentence is checked against the passage the model read: numbers, doses, names and negations included. Unsupported claims get a visible "check this" marker with the reason. Answers are never rewritten.
- **Evaluation harness** (`eval/`): 166 golden questions across medicine, repair, travel, survival, general knowledge, location and adversarial traps. It scores retrieval, key facts, forbidden claims, behaviour, citation faithfulness and latency, and runs A/B model comparisons with a significance test.
- **Better retrieval:**
  - reciprocal-rank fusion across books;
  - intent-aware collection priors (medical questions favour WikiMed and the medical guides);
  - an optional bge-m3 semantic rerank on a strict latency budget;
  - BM25 passage selection.

### Speed you can feel
- **Sources first.** Source cards and a verbatim "From the source" quote appear as soon as retrieval returns, while the model is still reading.
- **An honest progress narrative.** Search → Read → Write, naming what it's reading, with elapsed time and an estimate only when this device's speed has been measured.
- **Streaming renders block by block,** so long answers stay smooth and text stays selectable while it streams.
- **Recovery:** Try again on failed answers, Stop keeps the partial answer, a "Jump to latest" button, and Undo for deleted chats.

### Runs anywhere
- **One-line install** on Linux and macOS (`scripts/install.sh`) and a **Docker** image with content in a volume. Windows' `setup.ps1` gains `-Tier` and `-Region`.
- **A Lite tier of about 16–24 GB** next to the ~210 GB standard tier, nine named map regions or any bounding box, and a content manager (`python -m mimi content list | add | remove | verify`) with disk-space checks.
- **Verified downloads:**
  - every runtime and model is pinned to a fixed revision with SHA-256, and books are checked against Kiwix's own hashes;
  - downloads resume from `.part` files and are verified before use;
  - files left cut short by the old downloader are detected and finished.
- **Engines and helper processes stop with Core:**
  - on Linux and macOS through process groups;
  - on Windows, Core puts itself in its kill-on-close job, so plugin and PDF workers can't outlive it either.
- **A portable Mimi keeps each computer's phone certificate.** On Windows the key is sealed to one PC, so moving the drive parks that certificate, and it comes back when the drive does.
- **Windows on ARM uses the x64 engines** under emulation.

### Design system and accessibility
- **Token scales** for type, space, radius, elevation, layers and motion, documented in `docs/DESIGN_SYSTEM.md` with a living style guide at `/dev/design`.
- **Every theme passes WCAG AA contrast**, checked on every build. The light theme's status colours went from 1.6–2.2:1 to at least 4.9:1, and high contrast now works in light mode.
- **Screen readers:** chat is announced as a log, with status changes and the final answer read once rather than every token. Dialogs trap and restore focus, the command palette and slash menu are proper comboboxes, and all forms are labelled.
- **Controls:**
  - focus rings follow each control's shape;
  - reduced motion reaches every transition and scroll;
  - touch targets are 44 px;
  - controller hints show only when a controller is in use.
- **Settings regrouped from 13 sections to 9**; old links redirect.
- **Density and Well style settings now work.**
- **Deleting:** Undo for single deletes, and a controller-friendly confirm dialog for bulk ones.

### Security
- **The local certificate authority is name-constrained** to `.local` names and private addresses, valid for two years, and its key is protected at rest. Older CAs rotate automatically, and Settings explains how to update phones. Portable drives never carry the key.
- **Sign-in:**
  - phones and laptops need a PIN of at least 6 digits;
  - lockouts survive restarts, and a flood of wrong guesses can't lock out phones and laptops that have signed in before (they keep their own limit);
  - sessions expire after 30 idle days.
- **Prompt-injection defences.** Library passages, attached files and plugin output reach the model as delimited, untrusted data. Once a turn has read outside content, `remember` only suggests a memory, and side-effecting tools need the user's own request.
- **ZIM content is sandboxed.** The reader strips `javascript:` and similar links, frames and forms.
- **Plugins:**
  - a versioned API, with manifests read without running code;
  - argument validation;
  - each call runs in a worker process that is killed on timeout;
  - a test harness: `python -m mimi plugin check | test`.
- **`SECURITY.md` and a threat model.**

### Ecosystem
- **A live demo in the browser** at https://andrewkenady.github.io/mimi/demo/: the real Mimi interface, built with a recorded Core.
  - It replays answers captured from the real API at the handheld's speed, with a "Skip the wait" switch, a guided tour and an honest reply to questions it has no recording of.
  - It includes a small offline map of Yellowstone with a recorded route.
  - Demo code is compiled out of the normal build.
- **MCP server:** `python -m mimi mcp` exposes the offline library, places, directions and location to Claude Desktop and other MCP clients.
- **CI:**
  - Core tests and lint on Linux, Windows and macOS;
  - UI type checks and the contrast audit;
  - 30 end-to-end tests, axe scans and visual snapshots;
  - the eval scoreboard on fixtures;
  - a Windows shell build.
- **Releases** ship SHA-256 sums and signed build-provenance attestations.
- **Contributor guide, code of conduct, issue forms** (including one for wrong answers, which feed the eval set), and Dependabot.

### Fixed
- Setup could unpack Windows' kiwix-tools into an empty folder, and still call it installed. Archives are now only flattened when every file shares one top folder, and an engine counts as installed only when its program is present.
- Removing content or upgrading an engine while Mimi is running says to close Mimi first, instead of crashing halfway.
- A fresh install crashed or failed 25 tests: selectolax 1.0 removed a module Core imports.
- The library showed "21,673,012 articles· 118.7 GB" (missing space).
- The chat list on phones covered the conversation and never closed.
- Saving a PIN always reported success.
- The sign-in request's "Deny" never received focus.
- Light-theme users saw a dark flash on every load.

## [0.1.0] — 2026-09-27

First public version: offline chat grounded in Kiwix libraries with citations, Lens, voice, Scribe, memory, offline maps with directions and address search, sharing with phones, and the native Windows shell.
