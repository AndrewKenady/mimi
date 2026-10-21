# Mimi eval — Gemma 4 12B, F1 fixes vs Gemma 4 12B, 0.2.0

A: `eval/results/2026-10-21-final-en.jsonl` (2026-10-21) · B: `eval/results/2026-10-19-default.jsonl` (2026-10-20)

| Metric | Gemma 4 12B, F1 fixes | Gemma 4 12B, 0.2.0 | Δ (B − A) |
|---|---|---|---|
| Pass rate (all checks) | 94.6 % | 90.4 % | -4.2 pts |
| Key-fact recall | 96.4 % | 93.7 % | -2.7 pts |
| All key facts present | 94.3 % | 89.9 % | -4.4 pts |
| Behavior correct | 98.2 % | 95.2 % | -3.0 pts |
| Answers with a forbidden claim | 0 | 1 | +1 |
| Citation faithfulness | 36.4 % | 36.6 % | +0.2 pts |
| Citation precision | 54.9 % | 49.8 % | -5.1 pts |
| Citation coverage | 51.3 % | 54.3 % | +3.0 pts |
| Unsupported/invalid citations | 233 | 249 | +16 |
| Searched the library | 91.6 % | 90.4 % | -1.2 pts |
| Read an expected article | 53.3 % | 37.2 % | -16.1 pts |
| Read the expected collection | 88.8 % | 90.1 % | +1.3 pts |
| Expected tool used | 100.0 % | 100.0 % | +0.0 pts |
| Time to first token p50 / p90 | 24.4 s / 34.6 s | 16.0 s / 24.4 s | |
| Total time p50 / p90 / p95 | 50.1 s / 75.0 s / 81.7 s | 38.1 s / 60.7 s / 67.0 s | |
| Generation speed p50 (tok/s) | 7.78 | 8.41 | +0.63 |
| Errors | 0 | 0 | +0 |

### Pass rate by domain

| Domain | Gemma 4 12B, F1 fixes | Gemma 4 12B, 0.2.0 |
|---|---|---|
| adversarial | 100.0 % | 91.7 % |
| general | 97.3 % | 97.3 % |
| local | 100.0 % | 100.0 % |
| medicine | 91.4 % | 82.9 % |
| repair | 90.0 % | 75.0 % |
| survival | 86.4 % | 90.9 % |
| travel | 100.0 % | 100.0 % |

**Paired items:** 166 · only Gemma 4 12B, F1 fixes passed: 12 · only Gemma 4 12B, 0.2.0 passed: 5 · exact McNemar p = 0.1435 (not a significant difference at 0.05)

- Only Gemma 4 12B, F1 fixes: adv-010, adv-021, med-010, med-014, med-018, med-022, med-026, med-034, rep-002, rep-011, rep-019, srv-002
- Only Gemma 4 12B, 0.2.0: med-002, med-006, med-012, srv-009, srv-015
