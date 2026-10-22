"""Publish eval scoreboards to the project site (site/scoreboard.html reads them).

    python eval/publish.py OUT_DIR        # e.g. _site/scoreboard, from .github/workflows/pages.yml

Copies every report score.py wrote to eval/reports/*.json into OUT_DIR, writes
OUT_DIR/index.json (newest first, with each report's question language), and scores the synthetic fixtures into
OUT_DIR/sample.json so the page can show its layout before a real run exists. The
sample is marked synthetic in the file itself, and the page labels it everywhere.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import goldset
import score


def describe(path: Path, report: dict) -> dict:
    """One line of the index: what a report covers, without loading it whole on the page."""
    runs = [report["a"], report["b"]] if "compare" in report else [report]
    return {
        "file": path.name,
        "kind": "compare" if "compare" in report else "single",
        "run_date": max(r.get("run_date") or "" for r in runs),
        "models": [m for r in runs for m in r.get("models") or []],
        # one name per run: its label, when two runs of the same model are compared, else its model(s)
        "labels": [r.get("label") or " + ".join(r.get("models") or []) for r in runs],
        # reports from before the Spanish and French sets have no languages: they are English
        "languages": sorted({x for r in runs for x in r.get("languages") or ["en"]}),
        "devices": sorted({d for r in runs for d in r.get("devices") or []}),
        "mimi_versions": sorted({v for r in runs for v in r.get("mimi_versions") or []}),
        "items": max(((r.get("chat") or {}).get("overall") or (r.get("retrieval") or {}).get("overall") or {}).get("n", 0) for r in runs),
        "retrieval_only": all("chat" not in r for r in runs),
    }


def publish(out: Path, reports: Path = score.REPORTS) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    entries = []
    for p in sorted(reports.glob("*.json")):
        report = json.loads(p.read_text("utf-8"))
        shutil.copyfile(p, out / p.name)
        entries.append(describe(p, report))
    entries.sort(key=lambda e: (e["run_date"], e["file"]), reverse=True)

    items = goldset.load(None)
    a = score.summarize(items, score.load_rows(str(HERE / "fixtures" / "results-a.jsonl")), source="fixtures/results-a.jsonl")
    b = score.summarize(items, score.load_rows(str(HERE / "fixtures" / "results-b.jsonl")), source="fixtures/results-b.jsonl")
    sample = {"synthetic": True, "a": {k: v for k, v in a.items() if k != "rows"}, "b": {k: v for k, v in b.items() if k != "rows"},
              "compare": score.compare(a, b)}
    (out / "sample.json").write_text(json.dumps(sample, ensure_ascii=False), "utf-8")

    index = {"reports": entries, "sample": "sample.json", "question_set": len(items)}
    (out / "index.json").write_text(json.dumps(index, indent=1, ensure_ascii=False), "utf-8")
    return index


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    idx = publish(Path(sys.argv[1]))
    print(f"published {len(idx['reports'])} report(s) and a synthetic sample to {sys.argv[1]}")
