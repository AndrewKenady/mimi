# Mimi eval — gemma-4-12b vs gemma-4-12b — in Spanish

A: `eval\results\2026-10-20-final-es.jsonl` (2026-10-20) · B: `eval\results\2026-10-20-default-es.jsonl` (2026-10-20)

| Metric | gemma-4-12b | gemma-4-12b | Δ (B − A) |
|---|---|---|---|
| Pass rate (all checks) | 94.0 % | 91.6 % | -2.4 pts |
| Key-fact recall | 96.3 % | 93.1 % | -3.2 pts |
| All key facts present | 93.7 % | 91.2 % | -2.5 pts |
| Behavior correct | 97.0 % | 94.6 % | -2.4 pts |
| Answers with a forbidden claim | 0 | 1 | +1 |
| Citation faithfulness | — | 0.0 % | — |
| Citation precision | 94.6 % | 94.2 % | -0.4 pts |
| Citation coverage | — | 0.0 % | — |
| Unsupported/invalid citations | 34 | 41 | +7 |
| Searched the library | 92.2 % | 92.2 % | +0.0 pts |
| Read an expected article | 47.4 % | 40.9 % | -6.6 pts |
| Read the expected collection | 86.8 % | 84.2 % | -2.6 pts |
| Expected tool used | 100.0 % | 100.0 % | +0.0 pts |
| Time to first token p50 / p90 | 19.1 s / 24.6 s | 16.5 s / 22.8 s | |
| Total time p50 / p90 / p95 | 47.5 s / 72.2 s / 78.3 s | 41.7 s / 63.2 s / 68.1 s | |
| Generation speed p50 (tok/s) | 8.18 | 9.10 | +0.919987 |
| Errors | 0 | 0 | +0 |

### Pass rate by domain

| Domain | gemma-4-12b | gemma-4-12b |
|---|---|---|
| adversarial | 100.0 % | 87.5 % |
| general | 100.0 % | 100.0 % |
| local | 100.0 % | 100.0 % |
| medicine | 85.7 % | 77.1 % |
| repair | 90.0 % | 95.0 % |
| survival | 86.4 % | 90.9 % |
| travel | 100.0 % | 100.0 % |

**Paired items:** 166 · only gemma-4-12b passed: 9 · only gemma-4-12b passed: 5 · exact McNemar p = 0.424 (not a significant difference at 0.05)

- Only gemma-4-12b: adv-008-es, adv-010-es, adv-021-es, med-006-es, med-012-es, med-018-es, med-021-es, med-027-es, med-032-es
- Only gemma-4-12b: med-010-es, med-026-es, med-033-es, rep-002-es, srv-015-es
