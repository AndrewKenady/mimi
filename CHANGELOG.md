# Changelog

All notable changes to Mimi. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow [Semantic Versioning](https://semver.org/) once 1.0 ships. Tagged releases publish the top section as their notes.

## [Unreleased]

### Changed
- **Answers start sooner on a 16 GB handheld.** Gemma 4 12B loaded its vision projector every time it started, and on the F1 that graphics memory pushed it down to the fallback rung with a 4096-token context and a q8_0 V cache, where each request starts about 3 s later. The projector now loads only for a turn with a photo: the model restarts with it, leaving 1 GB more graphics memory free on each rung for the image, and the next photo starts on the rung that worked. Text turns go back to the model without it unless vision got the full settings. On the F1 a photo answer took 90–105 s with its restarts, and a model sitting on a lower rung after a photo no longer slows the text turns that follow (97 s to the first word before). Without it the model starts at the full 8192-token context: on 30 golden-set questions the first word came after 15.7 s at the median instead of 23.9 s, and 20.6 s instead of 47.4 s for the slowest tenth; the whole answer after 35.6 s instead of 47.8 s.
- **Core reads HTML with selectolax's Lexbor backend** and accepts selectolax 1.x, which removed the Modest backend Core used. Lexbor follows the HTML5 parsing rules browsers use, and gets fixes Modest no longer does. With selectolax 1.x installed, `eval/run.py` had fallen back to stripping tags with a regex, so a script's text could reach the scored sources; it now uses Lexbor too.
- **Library pictures only with a photo.** Mimi can look at an article's main picture only in a turn where you attached a photo, so it still compares your photo of a mushroom or plant with the library's, but a text-only question like "what does a death cap look like?" is answered from the article's text.

### Fixed
- **The CPU-only fallback stays on the CPU.** When a model runs out of graphics memory at every other setting, Core tries it on the CPU alone. If the CPU build of llama.cpp was missing (an interrupted download, say), a GPU build stood in for it without being told to keep the layers off the GPU, so the last attempt could run out of graphics memory the same way. It now always runs with `-ngl 0`.

## [0.2.1] — 2026-10-22

The release from the first full eval on the reference handheld: long sessions no longer run out of memory, the bleach answer is safe, and library search finds the article that is the topic, measured on the device ([docs/BENCHMARKS.md](docs/BENCHMARKS.md#answer-quality-eval-harness)).

### Fixed
- **Mimi no longer runs out of memory after an hour of questions.** Two caches grew until a turn failed to allocate memory and the model crashed, 20–80 minutes into a session on a 16 GB handheld. llama.cpp kept earlier prompts in system memory, up to 8 GB by default; that cache is now sized to the device (512 MB up to 16 GB, 2 GB up to 32 GB, 8 GB above). And kiwix-serve held on to memory as it searched, reaching 4–5 GB in an hour; it now keeps only two recent searches, and Mimi restarts it with the same books when it holds more than 12 % of RAM (at least 1.5 GB) while the library is idle, so no search is cut short.
- **A model short of graphics memory steps down without losing half its speed.** On the F1, a 16 GB handheld whose GPU gets 3 GB of the RAM, Gemma 4 12B at an 8192-token context can run out of graphics memory, and the fallback ladder then went from a 4096-token context straight to leaving 3 GB free, which keeps layers on the CPU and generates at half speed. A rung in between now uses a q8_0 V cache, which needs less memory and generates nearly as fast (7.8 instead of 8.4 tokens/s). It isn't the default: on the F1 it made every request about 3 s slower to start, and an answer's first word came after 24 s at the median instead of 16 s.
- **A model that runs out of graphics memory while it is up no longer answers with nothing.** When other programs (the lock screen, a browser) took graphics memory after the model had loaded, llama-server stayed up but failed every request, and each turn ended with an empty answer and no error. That failure is now recognized as running out of memory: the model restarts one step down, as after a crash, and the question is asked again. The same goes for the prompt-cache warm-up right after the model loads: when it ran out of memory, the model stayed up with a broken cache, and the first question failed with "Invalid input batch".
- **The bleach dose for drinking water is read from the right paragraph.** Mimi picked an article's paragraphs with the model's few search words alone, so "disinfect water with bleach ratio" chose the surface-cleaning dilution on the same page and the answer said a tablespoon per gallon. Paragraphs are now picked with your own question too, so the model reads the FEMA dose on that page: 16 drops (1/8 teaspoon) per gallon.
- **The library finds the article that is the topic.** The title lookup ignored little words on one side only, so titles like "Speed of light" or "Great Wall of China" never matched while "Since", "Capital" and "Speed light" did. Titles now match as the question words them, anywhere in it; a title that is a small part of the question needs the full-text search to agree; redirects lead to the article itself; a generic title like "First aid" no longer hides "Nosebleed", even when three books have it; a four-letter topic like "burn" is looked up too; and a short title from a book on the question's subject counts ("Hypothermia" in MDWiki for a medical question, which a longer "Core body temperature" match had pushed out; "nosebleed" now reads as a medical question). On the F1 retrieval check, the right article comes first for 38.0 % of questions instead of 11.7 % (in the top 10: 49.6 % instead of 29.2 %; for medicine, 80.0 %). kiwix-serve now uses up to 8 threads, so the extra lookups don't queue.
- **Library search keeps its semantic ranking.** Search uses the embedding server only when it is already running, and those calls didn't count as use, so it was stopped as idle 15 minutes after it started, even while every search used it. In the F1 eval it was up for about 45 minutes of 5 hours. Search's calls now count, so once the server runs it stays while the library is in use. On the F1 itself the semantic steps still don't run: on its CPU, with the chat model loaded, a rerank takes about 2.2 s and passage scoring about 4 s, over their 1.2 s and 0.8 s budgets, so search there ranks without them.
- **Answers fit a small context.** When graphics memory is short, the model runs with a 4096-token context, and a question that took a few searches could build a longer prompt and fail ("exceeds the available context size"). Each step now fits: only when the prompt would leave less than 512 tokens for the answer are the longest search results shortened (each passage inside its own markers), then no more tools offered; the answer gets the rest of the context.
- **An answer is never silently empty.** When the model read its search results and then wrote nothing, the turn ended with an empty answer and no error. Mimi now asks it once more, without tools, to write the answer.
- **Crisis lines for suicide and self-harm.** Mimi's instructions now include 988, Samaritans 116 123, 024 (Spain), 3114 (France) and Lifeline 13 11 14; the model had offered 111 for the UK, which is the NHS non-emergency number.
- **Eval scoring.** Every change below was prompted by a correct answer from the F1 runs that was scored wrong:
  - Refusals in the words models use now count ("I cannot fulfill this request", "no puedo cumplir"), and so do crisis-line replies and "there is no safe ratio". A hedge item also accepts a refusal that states every key fact.
  - A forbidden claim that the rest of its sentence debunks ("…was based on a fraudulent paper that has been debunked") is reported, not made.
  - Five items no longer flag a correct answer: rubbing frostbite; someone else's solo ascent of Everest; a fuse box that "contains higher-amperage fuses"; a bleach-to-water dilution in the bleach-and-ammonia question; and the kitchen dose of bleach given next to the drinking-water one.
  - Three items accept correct wordings: "35.0 °C", "Facial drooping" and RICE's "Icing".
  - A resumed run counts each question once, and pass rates are rounded once.
  - Reports can name each run (`score.py --label`, `--label-b`), so an A/B of one model against an earlier release says which side is which, on the scoreboard too.
- **A model that runs out of graphics memory on its first prompt no longer crash-loops.** On a 16 GB handheld, Gemma 4 12B could load fine and then crash reading the prompt; Core restarted it with the same settings, and it crashed again on every message. Now it restarts with a smaller context and more graphics memory left free (CPU only as the last resort), and the question is asked again once instead of ending in "Something went wrong".

## [0.2.0] — 2026-10-18

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
- **Spanish and French books.** `content add library-es` adds Wikipedia Médica, Wikiviajes, iFixit en español and the most-read Spanish Wikipedia articles (5.5 GB), and `library-fr` the French equivalents (6.2 GB); `wikipedia-es-nopic` and `wikipedia-fr-nopic` add all of Spanish or French Wikipedia as text (about 13 GB each). When you write in Spanish or French, those books are searched with words in your language and the English books with English words, so a Spanish question finds *Quemadura* as well as *Burn*. Tried on the real Spanish medical Wikipedia with five first-aid questions: the right Spanish article came first or second every time, where an English-only search had it in its top four for two of them. [docs/I18N.md](docs/I18N.md) has the conventions, a glossary and how to add a language.
- **The eval set in Spanish and French.** All 166 golden questions, translated by an AI model and not yet reviewed by a native speaker, with key facts and forbidden claims rewritten for each language and article titles taken from Wikipedia's language links. `eval/run.py --lang es` (or `fr`) asks them with the matching `x-mimi-locale`. Refusals, hedges and negations are recognized in each language, reports and the scoreboard say which language they're in, and A/B comparisons across languages are refused.

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
- **A bootable USB image.** Write it to a stick with Rufus, balenaEtcher or `dd`, and any x86-64 PC (UEFI with Secure Boot on, or legacy BIOS) starts straight into Mimi, full screen, with nothing to set up.
  - It's a minimal Debian 13 built by one script (`scripts/image/build.sh`): Mimi is installed as `install.sh --tier none` would, runs as its own user under systemd, and shows on screen through cage and Chromium in kiosk mode. There is no SSH, no account has a password, and sharing stays off until the owner turns it on.
  - The published image has no content. On first boot it downloads the Lite tier in the background once it's online, over a cable, USB tethering, or Wi-Fi written into a `wifi.txt` that the stick shows on any computer. `--tier lite` builds a stick with the content included, locally.
  - The "USB image" workflow builds it on demand, for tags and for pull requests that change it, boots it in QEMU until Mimi Core answers (about 30 s on GitHub's runners), and attaches it to the release when it's under 2 GB. It has been booted in QEMU, not yet on real hardware.

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
  - 35 end-to-end tests (one switches the whole app to Spanish and French and back), axe scans and visual snapshots;
  - the eval scoreboard on fixtures;
  - a Windows shell build.
- **Releases** ship SHA-256 sums and signed build-provenance attestations.
- **Contributor guide, code of conduct, issue forms** (including one for wrong answers, which feed the eval set), and Dependabot.

### Fixed
- French Wikivoyage, and any book Kiwix re-publishes with a letter after its date (`…_2026-07c.zim`), couldn't be downloaded: the catalog lookup didn't recognize the name.
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
