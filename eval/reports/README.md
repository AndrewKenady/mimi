# Eval reports

`python eval/score.py` writes one scoreboard per run here:

- `<date>-<model>.md` and `.json`: one run (`eval/score.py RESULTS.jsonl`)
- `<date>-<model-a>-vs-<model-b>.md` and `.json`: an A/B comparison (`--compare`)
- `<date>-retrieval.md` and `.json`: a `--retrieval-only` run
- `-es` or `-fr` at the end: a run in Spanish or French. `--name` picks another file name, and `--label` / `--label-b` name the runs when both sides of an A/B use the same model.

The `*-f1-fixes*` reports are real runs on the ONEXPLAYER F1 reference device (Ryzen 7 7840U, Radeon 780M, 16 GB) with Gemma 4 12B. They cover the English and Spanish sets and the retrieval check (with the golden set's keyword queries, and with the raw questions), plus A/B reports against Mimi 0.2.0 scored the same way. [`docs/BENCHMARKS.md`](../../docs/BENCHMARKS.md#answer-quality-eval-harness) says under what settings they ran. Everything in `eval/fixtures/` is synthetic test data from made-up models (`fixture-model-a`, `fixture-model-b`) and says nothing about any real model. See [`docs/EVALUATION.md`](../../docs/EVALUATION.md) for what the numbers mean and how to read them.
