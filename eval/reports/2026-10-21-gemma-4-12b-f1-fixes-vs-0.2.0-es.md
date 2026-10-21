# Mimi eval — Gemma 4 12B, F1 fixes vs Gemma 4 12B, 0.2.0 — in Spanish

A: `eval/results/2026-10-21-final-es.jsonl` (2026-10-21) · B: `eval/results/2026-10-20-default-es.jsonl` (2026-10-20)

| Metric | Gemma 4 12B, F1 fixes | Gemma 4 12B, 0.2.0 | Δ (B − A) |
|---|---|---|---|
| Pass rate (all checks) | 93.4 % | 91.6 % | -1.8 pts |
| Key-fact recall | 95.5 % | 93.1 % | -2.5 pts |
| All key facts present | 93.1 % | 91.2 % | -1.9 pts |
| Behavior correct | 96.4 % | 94.6 % | -1.8 pts |
| Answers with a forbidden claim | 0 | 0 | +0 |
| Citation faithfulness | 0.0 % | 0.0 % | +0.0 pts |
| Citation precision | 95.9 % | 94.2 % | -1.7 pts |
| Citation coverage | 0.0 % | 0.0 % | +0.0 pts |
| Unsupported/invalid citations | 28 | 41 | +13 |
| Searched the library | 92.2 % | 92.2 % | +0.0 pts |
| Read an expected article | 54.7 % | 40.9 % | -13.9 pts |
| Read the expected collection | 86.8 % | 84.2 % | -2.6 pts |
| Expected tool used | 100.0 % | 100.0 % | +0.0 pts |
| Time to first token p50 / p90 | 25.4 s / 34.7 s | 16.5 s / 22.8 s | |
| Total time p50 / p90 / p95 | 53.5 s / 78.2 s / 81.3 s | 41.7 s / 63.2 s / 68.1 s | |
| Generation speed p50 (tok/s) | 7.80 | 9.10 | +1.29 |
| Errors | 0 | 0 | +0 |

### Pass rate by domain

| Domain | Gemma 4 12B, F1 fixes | Gemma 4 12B, 0.2.0 |
|---|---|---|
| adversarial | 95.8 % | 87.5 % |
| general | 100.0 % | 100.0 % |
| local | 100.0 % | 100.0 % |
| medicine | 91.4 % | 77.1 % |
| repair | 85.0 % | 95.0 % |
| survival | 81.8 % | 90.9 % |
| travel | 100.0 % | 100.0 % |

**Paired items:** 166 · only Gemma 4 12B, F1 fixes passed: 10 · only Gemma 4 12B, 0.2.0 passed: 7 · exact McNemar p = 0.6291 (not a significant difference at 0.05)

- Only Gemma 4 12B, F1 fixes: adv-008-es, adv-021-es, med-006-es, med-012-es, med-018-es, med-021-es, med-027-es, med-030-es, med-032-es, med-034-es
- Only Gemma 4 12B, 0.2.0: med-002-es, med-017-es, med-033-es, rep-014-es, rep-018-es, srv-006-es, srv-012-es
