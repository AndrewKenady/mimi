# Changelog

All notable changes to Mimi. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow [Semantic Versioning](https://semver.org/) once 1.0 ships. Tagged releases publish the top section as their notes.

## [0.2.0] — Unreleased

The release that makes Mimi checkable, installable anywhere and accessible.

### Trust: honest library, checked answers, measured quality
- **PDF collections open and are searchable.** The medical and survival guide collections (Kiwix "nautilus" ZIMs) used to be listed as available but opened to a blank page, and chat couldn't search them. They now open as native document lists, PDFs open in the app, and their text is indexed page by page, so answers can cite *"Where There Is No Doctor, p. 105"*. TED and Gutenberg collections list their talks and books too.
- **Every book shows an honest status:** Ready, Indexing…, Browse only, Search only or Can't open, with a plain-English reason and a real item count.
- **A book whose download stopped partway is held back from the shelf** (its ZIM header shows it's incomplete), and the Library says which file and how much arrived, instead of listing a book that fails when opened.
- **Citation checks in chat.** Each cited sentence is checked against the passage the model read: numbers, doses, names and negations included. Unsupported claims get a visible "check this" marker with the reason. Answers are never rewritten.
- **Evaluation harness** (`eval/`): 166 golden questions across medicine, repair, travel, survival, general knowledge, location and adversarial traps. It scores retrieval, key facts, forbidden claims, behavior, citation faithfulness and latency, and runs A/B model comparisons with a significance test.
- **Better retrieval:**
  - reciprocal-rank fusion across books;
  - intent-aware collection priors (medical questions favor WikiMed and the medical guides);
  - an optional bge-m3 semantic rerank on a strict latency budget;
  - BM25 passage selection.

### Spanish and French
- **The whole interface speaks Spanish and French.** Settings → Appearance → Language is per person: Automatic follows the browser, and onboarding asks first. About 1,100 messages per language live in typed catalogs, so a missing translation fails the build. Numbers, dates, plurals and lists follow each language, and `<html lang>` switches with it so screen readers change voice.
- **Answers stay grounded in any of the three.** A question in Spanish or French used to skip the forced library search unless it ended in "?". Now the factual-question check knows both languages. Mimi answers in your language and searches the English library in English.
- **Citation checks across languages.** A Spanish or French answer can't be compared word for word with an English passage, so it gets a numbers-only check: a dose, a temperature or a date must be in the cited source, read either way ("37,5" or "37.5").
- **Core's own words follow you.** Status lines, tool activity, citation reasons, book notes, error messages and turn-by-turn directions arrive in the interface language.
- **Voice:** Kokoro's Spanish and French voices are listed, and a reply is read by a voice of its own language. Checked end to end with the real models: Whisper transcribes the spoken Spanish and French back and detects both languages.
- The library and the eval set are still English; [docs/I18N.md](docs/I18N.md) has the conventions, a glossary and how to add a language.

### Speed you can feel
- **Sources first.** Source cards and a verbatim "From the source" quote appear as soon as retrieval returns, while the model is still reading.
- **An honest progress narrative.** Search → Read → Write, naming what it's reading, with elapsed time and an estimate only when this device's speed has been measured.
- **Streaming renders block by block,** so long answers stay smooth and text stays selectable while it streams.
- **Recovery:** Try again on failed answers, Stop keeps the partial answer, a "Jump to latest" button, and Undo for deleted chats.

### Runs anywhere
- **One-line install** on Linux and macOS (`scripts/install.sh`) and a **Docker** image with content in a volume. Windows' `setup.ps1` gains `-Tier` and `-Region`.
- **A Lite tier of about 16–24 GB** next to the ~210 GB standard tier, nine named map regions or any bounding box, and a content manager (`python -m mimi content list | add | remove | verify`) with disk-space checks.
- **Plus and Max tiers** for bigger machines: Gemma 4 26B A4B with 32 GB of RAM or a 16 GB GPU, Qwen3.6 35B A3B with 48 GB+ or a 24 GB GPU (Qwen3.8 27B as an option for big GPUs). Mimi already picked these profiles on such hardware, but nothing could download their models, so it quietly ran the Standard ones. When a profile's model is missing, Settings now says so and names the pack to add. These tiers are untested on real hardware.
- **Verified downloads:**
  - every runtime and model is pinned to a fixed revision with SHA-256, and books are checked against Kiwix's own hashes;
  - downloads resume from `.part` files and are verified before use;
  - files left cut short by the old downloader are detected and finished.
- **Engines and helper processes stop with Core:**
  - on Linux and macOS through process groups;
  - on Windows, Core puts itself in its kill-on-close job, so plugin and PDF workers can't outlive it either.
- **A portable Mimi keeps each computer's phone certificate.** On Windows the key is sealed to one PC, so moving the drive parks that certificate, and it comes back when the drive does.
- **Windows on ARM uses the x64 engines** under emulation.

### Maps: near me and addresses
- **The nearest gas station, hospital, clinic, pharmacy or ambulance station.** "Near me" and the chat tool now list them nearest first from OpenStreetMap, with opening hours, phone, brand or operator, the address, and for hospitals whether they have an emergency department. If none is close, the search widens up to 250 km rather than saying there's nothing. They are built from the extract the driving-directions pack already downloads (`maps/pois.sqlite`, a few MB for most regions). Lite, which has no extract, says so and falls back on GeoNames' hospitals. Installs that already have directions get the table with `content add routing`. On the map they have their own filters (Fuel, Hospitals, Pharmacies), and a place's card shows its emergency department, address, hours and a tap-to-call phone number, in English, Spanish or French.
- **Street-address search in the UK, Germany, France, Australia and New Zealand,** from OpenStreetMap's address points. Search reads the local forms ("Hauptstraße 5, 10115 Berlin", "Calle Mayor, 12", "10 Downing Street, London SW1A 2AA"), the spellings people type ("Hauptstrasse", "Hauptstr.", "Muellerstrasse", "C/ Mayor"), and town names the gazetteer spells differently ("München"). Results are written the way the country writes them. Tested on real OpenStreetMap data for small areas (central Vaduz, Monaco, Andorra, San Marino, Jersey, Appenzell Innerrhoden, central Heidelberg), not yet on a whole country. US and Canadian search is unchanged, and existing address indexes keep working without a rebuild.
- **One OpenStreetMap download per region.** Directions, the fuel and hospital table and (outside North America) addresses are built from a single Geofabrik extract, checked against its published MD5, and deleted once every build that reads it is done.

### Design system and accessibility
- **Token scales** for type, space, radius, elevation, layers and motion, documented in `docs/DESIGN_SYSTEM.md` with a living style guide at `/dev/design`.
- **Every theme passes WCAG AA contrast**, checked on every build. The light theme's status colors went from 1.6–2.2:1 to at least 4.9:1, and high contrast now works in light mode.
- **Screen readers:** chat is announced as a log, with status changes and the final answer read once rather than every token. Dialogs trap and restore focus, the command palette and slash menu are proper comboboxes, and all forms are labeled.
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
- **Prompt-injection defenses.** Library passages, attached files and plugin output reach the model as delimited, untrusted data. Once a turn has read outside content, `remember` only suggests a memory, and side-effecting tools need the user's own request.
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
- **An answer-quality [scoreboard](https://andrewkenady.github.io/mimi/scoreboard.html)** on the site: pass rate with its 95% interval, forbidden claims, citation faithfulness, behavior and speed, by subject and model against model, from the reports committed to `eval/reports/`. Until the first full run lands it says so, and offers a clearly labeled preview built from the synthetic fixtures. Every run records the device it ran on.
- **MCP server:** `python -m mimi mcp` exposes the offline library, places, directions and location to Claude Desktop and other MCP clients.
- **CI:**
  - Core tests and lint on Linux, Windows and macOS;
  - UI type checks and the contrast audit;
  - 32 end-to-end tests (one switches the whole app to Spanish and French and back), axe scans and visual snapshots;
  - the eval scoreboard on fixtures;
  - a Windows shell build.
- **Releases** ship SHA-256 sums and signed build-provenance attestations.
- **Contributor guide, code of conduct, issue forms** (including one for wrong answers, which feed the eval set), and Dependabot.

### Fixed
- Setup could unpack Windows' kiwix-tools into an empty folder, and still call it installed. Archives are now only flattened when every file shares one top folder, and an engine counts as installed only when its program is present.
- Removing content or upgrading an engine while Mimi is running says to close Mimi first, instead of crashing halfway.
- A fresh install crashed or failed 25 tests: selectolax 1.0 removed a module Core imports.
- The library showed "21,673,012 articles· 118.7 GB" (missing space), and nine other places dropped the space before "·" the same way; an error with a partial answer read "…memory.The answer above is incomplete."
- Voice input crashed on fresh installs: PyAV 19 removed an argument faster-whisper passes. PyAV is held below 19.
- On phones the map's bottom sheet cut off the place list and the route card, the reader's top bar pushed "Ask Mimi" off screen, the pairing code ran past its panel, and a long spoken answer ran under the voice controls.
- Points of interest on the map trailed behind it while panning or zooming, and never grew on hover.
- The chat list on phones covered the conversation and never closed.
- Saving a PIN always reported success.
- The sign-in request's "Deny" never received focus.
- Light-theme users saw a dark flash on every load.

## [0.1.0] — 2026-09-27

First public version: offline chat grounded in Kiwix libraries with citations, Lens, voice, Scribe, memory, offline maps with directions and address search, sharing with phones, and the native Windows shell.
