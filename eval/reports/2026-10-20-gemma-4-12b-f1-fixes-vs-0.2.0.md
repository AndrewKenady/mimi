# Mimi eval — gemma-4-12b vs gemma-4-12b

A: `eval\results\2026-10-20-final-en.jsonl` (2026-10-20) · B: `eval\results\2026-10-19-default.jsonl` (2026-10-20)

| Metric | gemma-4-12b | gemma-4-12b | Δ (B − A) |
|---|---|---|---|
| Pass rate (all checks) | 94.0 % | 90.4 % | -3.6 pts |
| Key-fact recall | 95.8 % | 93.7 % | -2.1 pts |
| All key facts present | 93.7 % | 89.9 % | -3.8 pts |
| Behavior correct | 97.6 % | 95.2 % | -2.4 pts |
| Answers with a forbidden claim | 0 | 1 | +1 |
| Citation faithfulness | 38.2 % | 36.6 % | -1.6 pts |
| Citation precision | 51.2 % | 49.8 % | -1.4 pts |
| Citation coverage | 54.3 % | 54.3 % | -0.0 pts |
| Unsupported/invalid citations | 266 | 249 | -17 |
| Searched the library | 92.2 % | 90.4 % | -1.8 pts |
| Read an expected article | 48.9 % | 37.2 % | -11.7 pts |
| Read the expected collection | 88.2 % | 90.1 % | +2.0 pts |
| Expected tool used | 100.0 % | 100.0 % | +0.0 pts |
| Time to first token p50 / p90 | 16.0 s / 22.9 s | 16.0 s / 24.4 s | |
| Total time p50 / p90 / p95 | 39.1 s / 59.7 s / 65.8 s | 38.1 s / 60.7 s / 67.0 s | |
| Generation speed p50 (tok/s) | 8.49 | 8.41 | -0.0785207 |
| Errors | 0 | 0 | +0 |

### Pass rate by domain

| Domain | gemma-4-12b | gemma-4-12b |
|---|---|---|
| adversarial | 91.7 % | 91.7 % |
| general | 97.3 % | 97.3 % |
| local | 100.0 % | 100.0 % |
| medicine | 88.6 % | 82.9 % |
| repair | 90.0 % | 75.0 % |
| survival | 95.5 % | 90.9 % |
| travel | 100.0 % | 100.0 % |

**Paired items:** 166 · only gemma-4-12b passed: 9 · only gemma-4-12b passed: 3 · exact McNemar p = 0.146 (not a significant difference at 0.05)

- Only gemma-4-12b: med-014, med-022, med-026, med-034, rep-002, rep-018, rep-019, srv-001, srv-002
- Only gemma-4-12b: med-006, med-008, srv-015
