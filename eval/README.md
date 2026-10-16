# Mimi eval

A reproducible way to measure how well Mimi answers: whether it finds the right article, gets the facts right, cites sources that actually say what it claims, behaves sensibly on trick questions, and how long all of that takes. Methodology and limitations are in [docs/EVALUATION.md](../docs/EVALUATION.md).

```
eval/
  questions/*.jsonl   the golden set: 166 questions across 7 domains (schema in goldset.py)
  goldset.py          loading, validation, and the answer checks (key facts, forbidden claims, behavior)
  run.py              asks a live Mimi every question and records answers, sources, tools and timings
  score.py            turns a results file into a Markdown scoreboard + JSON summary; A/B comparisons
  fixtures/           SYNTHETIC results from made-up models, used by the tests (not real numbers)
  reports/            scoreboards written by score.py
  results/            raw run output (git-ignored)
```

## Running it on the device

Run these on the Mimi device itself, with Mimi running. On loopback Mimi signs you in as the owner when "Sign in automatically on this device" is on and no PIN is required. Otherwise add `--user <name> --pin <pin>`. Paths below are for the Windows reference device; on other systems use any Python 3.11+ that has `httpx` installed (`pip install httpx selectolax`).

```powershell
# 1. Retrieval only: is the right article in the search results? (~1 minute, no model needed)
python\python.exe eval\run.py --retrieval-only
python\python.exe eval\score.py eval\results\<date>-retrieval.jsonl

# 2. Full answers with the current main model (166 questions; budget 1.5–3 hours on the 780M)
python\python.exe eval\run.py

# 3. The D6 question: the same set on another model. --model switches Settings → Models → main
#    for the run and switches it back afterwards.
python\python.exe eval\run.py --model gemma-4-12b
python\python.exe eval\run.py --model qwen3.5-9b
python\python.exe eval\score.py eval\results\<date>-gemma-4-12b.jsonl --compare eval\results\<date>-qwen3.5-9b.jsonl
```

Smaller runs: `--domain medicine,adversarial`, `--ids med-001,adv-012` or `--limit 10`. A run can be stopped and restarted at any time: it picks up where it left off (rows that errored are retried). Use `--fresh` to start over.

### What a run does

- Every question goes in as a **temporary chat** (no memories, history or `remember` calls) and is deleted afterwards. Use `--mode field_medic` etc. to test a mode, and `--think` / `--no-think` to pin "think harder".
- Before the first question, a throwaway "Hello" turn loads the model and fills its prompt cache, so loading time doesn't land on question one (`--no-warmup` to skip). If the answering model isn't the one you asked for (battery saver swaps the main model for the quick one), the run stops.
- For every cited library source, the run fetches the article text (`/api/library/article`, at most `--passage-chars`, 20 000 by default). That lets `score.py` check citations offline.
- Location questions (`loc-*`) are scored against whether the device knew its location when the run started: with no location set, the right behavior is to ask for one. Set a location on the Map first if you want to test the answers themselves.
- Timings are measured by the client: first server event, first answer token (TTFT), first tool call, and total. The server's own total and tokens/s are recorded too.

### Repeat runs and variance

Sampling is on (Gemma uses temperature 1.0), so one run of one model is a sample, not a verdict. For a decision, use `--repeats 3` (the scoreboard averages per item) and check the McNemar p-value in the A/B report. Under about 0.05, the difference in pass rate is unlikely to be noise. Run both models in the same session with the same apps open: memory pressure changes the speed numbers a lot (see BENCHMARKS.md).

## Scoring

```powershell
python\python.exe eval\score.py RESULTS.jsonl                       # -> eval/reports/<date>-<model>.md/.json
python\python.exe eval\score.py A.jsonl --compare B.jsonl            # A/B with per-item flips and McNemar p
python\python.exe eval\score.py RESULTS.jsonl --stdout               # print instead of writing files
python\python.exe eval\score.py RESULTS.jsonl --embed-url http://127.0.0.1:7611/v1/embeddings    # paraphrase-aware grounding (bge-m3 server must be up)
python\python.exe eval\score.py RESULTS.jsonl --judge-url http://127.0.0.1:7610/v1/chat/completions  # optional LLM judge
```

Scoring needs no model. `--embed-url` and `--judge-url` are optional and use any OpenAI-compatible endpoint. Mimi's own llama-servers listen on 7611 (embeddings, started on demand) and 7610 (chat). Grading a model with itself is a weak check, so prefer a different (ideally larger) judge model. Judge verdicts are recorded next to the heuristic ones, and the report shows how often the two agree.

Try it without a device on the synthetic fixtures:

```bash
cd core && python ../eval/score.py ../eval/fixtures/results-a.jsonl --compare ../eval/fixtures/results-b.jsonl --stdout
```

## Adding questions

Append a line to the right `questions/*.jsonl` file. Keep facts stable and well known, write key facts as forgiving regexes (accept "2 inches" as well as "5 cm"), and phrase forbidden claims affirmatively: a match inside a negated sentence ("do **not** put butter on it") is ignored. `cd core && python -m pytest tests/test_eval_pipeline.py` validates the whole set (unique ids, known domains and collections, valid regexes).
