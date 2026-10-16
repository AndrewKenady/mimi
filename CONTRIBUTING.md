# Contributing to Mimi

Thanks for helping. Mimi is a fully offline AI field station, so every change is judged by one question: **does it still work, and stay honest, with no internet at all?**

## Ways to help that don't need code

- **Report a wrong or badly sourced answer** with the *Wrong or badly sourced answer* issue form. Each report becomes a case in the [evaluation set](eval/), so it makes every future release measurably better.
- **Try Mimi on new hardware** (Steam Deck, ROG Ally, a mini PC, a Mac, a Raspberry Pi 5) and add your numbers to [docs/BENCHMARKS.md](docs/BENCHMARKS.md).
- **Write a tool.** Drop a Python file into `tools/` to give Mimi a new ability. [tools/README.md](tools/README.md) has the contract and a test harness.

## Getting set up

Any OS works for development. You don't need the 200 GB of content: Core starts without models or books and the UI shows honest "not installed" states.

```bash
git clone https://github.com/AndrewKenady/mimi.git && cd mimi
uv venv -p 3.12 && uv pip install -e "core[dev,build]"   # or python -m venv + pip
cd core && python -m pytest                              # Core tests
python -m mimi serve                                     # Core + built UI on http://127.0.0.1:7600
cd ../ui && npm ci && npm run dev                        # hot-reloading UI on :5173, proxies to Core
```

Full installs per platform, including the Lite tier, are in [docs/INSTALL.md](docs/INSTALL.md).

## Before you open a pull request

| Change | Run |
|---|---|
| Anything in `core/` | `cd core && ruff check . && python -m pytest` |
| Anything in `ui/` | `cd ui && npm run check && npm run build` (plus `npm run contrast` and `npm run test:e2e` when present) |
| Answers, retrieval, prompts or the default model | an `eval/` run before and after. Paste the scoreboard diff into the PR ([docs/EVALUATION.md](docs/EVALUATION.md)) |
| UI | before and after screenshots, dark and light |

CI runs the same checks on Linux, Windows and macOS.

## Principles

1. **Offline is the product.** No runtime network calls, no CDNs, no telemetry. Downloads happen only in the installer and the content manager, from the original publishers, and are checksum-verified.
2. **Honest over impressive.** Cite sources, say "I don't know", label estimates as estimates, and never list content that can't actually be opened.
3. **Measure answer quality.** Model and retrieval decisions are backed by an eval run, not anecdotes. See the decision records in [docs/DECISIONS.md](docs/DECISIONS.md).
4. **Controller-first, accessible always.** Everything must work with a gamepad, a keyboard, touch and a screen reader. Use the tokens and primitives in [docs/DESIGN_SYSTEM.md](docs/DESIGN_SYSTEM.md); don't hard-code colors or sizes.
5. **Small, legible code.** Match the surrounding style. Comment *why*, not *what*. Add an entry to `docs/DECISIONS.md` when you choose between real alternatives.

## Commits and pull requests

- One logical change per PR, with a descriptive title in the imperative ("Library: list documents in PDF collections").
- Add a line to the *Unreleased* section of [CHANGELOG.md](CHANGELOG.md) for anything a user would notice.
- By contributing you agree your code is released under the [MIT License](LICENSE). Content you add to manifests must keep its own license, recorded in [docs/LICENSING.md](docs/LICENSING.md).

## Security

Please don't open public issues for vulnerabilities. See [SECURITY.md](SECURITY.md).

## Conduct

Everyone taking part is expected to follow the [Code of Conduct](CODE_OF_CONDUCT.md).
