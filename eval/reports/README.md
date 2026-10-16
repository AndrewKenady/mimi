# Eval reports

`python eval/score.py` writes one scoreboard per run here:

- `<date>-<model>.md` and `.json`: one run (`eval/score.py RESULTS.jsonl`)
- `<date>-<model-a>-vs-<model-b>.md` and `.json`: an A/B comparison (`--compare`)
- `<date>-retrieval.md` and `.json`: a `--retrieval-only` run

No real-device reports are committed yet. Everything in `eval/fixtures/` is synthetic test data from made-up models (`fixture-model-a`, `fixture-model-b`) and says nothing about any real model. See [`docs/EVALUATION.md`](../../docs/EVALUATION.md) for what the numbers mean and how to read them.
