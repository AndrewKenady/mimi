# Benchmarks — reference device

ONEXPLAYER F1 · AMD Ryzen 7 7840U (8C/16T) · Radeon 780M (Vulkan, 3 GB carve-out + shared) · 16 GB LPDDR5X-7500 · Windows 11 · llama.cpp b11205 (Vulkan) · measured 2026-09-26 with everyday apps open (≈90 % RAM in use).

## llama-bench (pp512 / tg128, flash attention)
| Model | Size | Prompt t/s | Generation t/s |
|---|---|---|---|
| Qwen3.5-4B Q4_K_M | 2.5 GiB | 344 | 23.5 |
| Qwen3.5-9B Q4_K_M | 5.3 GiB | 208 | 12.8 |
| Qwen3.5-9B, KV q8_0/f16 variations | | 195–199 | 10.8–12.9 (f16 V fastest) |
| Gemma 4 12B QAT Q4_0 | 6.5 GiB | — (context alloc failed at default batch) | 9.2–9.6 via llama-server @ 4k ctx |
| Gemma 4 12B + MTP draft | | — | didn't fit in memory with apps open |

## In-app (llama-server, 8k ctx, q8 K / f16 V, --fit)
| Scenario | Gemma 4 12B | Qwen3.5-9B |
|---|---|---|
| Generation | 6.8–9.2 t/s | 10.8–12.2 t/s |
| Prompt processing | 94–128 t/s | 109–150 t/s |
| Grounded answer, cold (search + 3 articles) | 39–68 s | 49–52 s |
| Follow-up with KV-cache reuse | 36 s (155 new prompt tokens) | 17–42 s |
| Directions via chat | 25 s | — |
| Vision (read a sign) | 29 s | — |

## Other components (CPU)
| Task | Time |
|---|---|
| Kokoro TTS, first sentence (cold / warm) | 4.4 s / 1.5 s |
| Whisper small, 6 s utterance incl. load | 5.5 s |
| Scribe: 25 s recording → transcript + summary | ≈40 s |
| RapidOCR, photo of a sign (warm) | 0.5 s |
| kiwix search + 3 passages (2026-09-26) | 0.2–2.3 s |
| Library search, 153 eval questions (2026-10-21) | 1.1 s median, 2.6 s p90 (0.55 s and 1.3 s in 0.2.0) |
| GeoNames/Wikipedia nearby (16 km) | 3–22 ms |
| Valhalla route, 98 mi | 0.1 s |
| Map tiles (US + Canada, z0–14) | 15.6 GB, local range requests |

## Voice turns (Gemma 4 12B, warm prompt cache)
Measured from the request to the first streamed word and the first complete sentence (the sentence is what Kokoro starts speaking; add ~1.5 s for warm TTS).

| Turn | First word | First sentence | Notes |
|---|---|---|---|
| Chit-chat, new chat | 1.7–1.9 s | 3.3–4.8 s | was 13.4 s before the cache fixes below |
| Library lookup (2 passages × 600 chars) | 8.3 s | 11 s | "Let me look that up" is spoken at ~4.6 s when the search starts |

What made the difference: the system prompt and tool schemas (~1.7k tokens) are identical for text and voice turns and for every chat. The chat-title request continues the conversation instead of evicting that prefix from llama-server's single slot. And the prefix is pre-filled right after the model loads (12 s, in the background).

## Answer quality (eval harness)
Measured on the F1 with `eval/run.py` + `eval/score.py` on the 166-question golden set (methodology in [EVALUATION.md](EVALUATION.md)); the full reports are in [`eval/reports/`](../eval/reports/) and on the [scoreboard](https://andrewkenady.github.io/mimi/scoreboard.html). Each question was asked once with sampling on (Gemma runs at temperature 1.0), so a run is a sample: near 94 %, the 95 % interval is about ±4 points. Both sides of each comparison are scored by the same scorer. Qwen3.5 hasn't been run against the set yet.

| English | Gemma 4 12B, this release (2026-10-21) | Gemma 4 12B, 0.2.0 (2026-10-19) |
|---|---|---|
| Pass rate (all checks) | **94.6 %** (95 % CI 90.0–97.1) | 90.4 % (84.9–94.0) |
| Key-fact recall | 96.4 % | 93.7 % |
| Answers with a forbidden claim | **0** | 1 (a tablespoon of bleach per gallon of drinking water) |
| Behavior correct (answer, hedge or refuse) | 98.2 % | 95.2 % |
| Citation faithfulness | 36.4 % | 36.6 % |
| Unsupported / invalid citations | 233 | 249 |
| Read an expected article | 53.3 % | 37.2 % |
| Time to first token p50 / p90 | 24.4 s / 34.6 s | 16.0 s / 24.4 s |
| Total time p50 / p90 | 50.1 s / 75.0 s | 38.1 s / 60.7 s |
| Errors | 0 | 0 |

12 items pass only in this release and 5 only in 0.2.0 (exact McNemar p = 0.14): better, but at 166 items not yet a significant difference. By domain: adversarial 91.7 → 100 %, medicine 82.9 → 91.4 %, repair 75 → 90 %, survival 90.9 → 86.4 %.

| Spanish | this release (2026-10-21) | 0.2.0 (2026-10-20) |
|---|---|---|
| Pass rate (all checks) | **93.4 %** (88.5–96.3) | 91.6 % (86.3–94.9) |
| Key-fact recall | 95.5 % | 93.1 % |
| Answers with a forbidden claim | 0 | 0 |
| Behavior correct | 96.4 % | 94.6 % |
| Read an expected article | 54.7 % | 40.9 % |
| Time to first token p50 / p90 | 25.4 s / 34.7 s | 16.5 s / 22.8 s |
| Total time p50 / p90 | 53.5 s / 78.2 s | 41.7 s / 63.2 s |

10 items pass only in this release and 7 only in 0.2.0 (p = 0.63). The F1 has no Spanish books, so these questions were answered from the English library, and citation faithfulness isn't measured for Spanish answers. A Spanish score isn't directly comparable with an English one ([EVALUATION.md](EVALUATION.md)). The bleach question still fails in Spanish: the answer gives the surface and kitchen dilutions from the right page but not the drinking-water dose.

**Why this release is slower to answer.** With other apps open on the F1, an 8192-token context no longer fit in graphics memory, and both runs ran on the fallback ladder's 4096-token rung with a q8_0 V cache. That cache added about 3 s to every request that reuses the cached prompt, and a turn makes two or three. The 0.2.0 runs had an f16 V cache, as did this release's first runs on 2026-10-20, at the full context (TTFT p50 16.0 s). V is f16 again by default and q8_0 is only a fallback rung, so the slower start applies only when memory is that short. Generation was 6.4–8.0 tokens/s (p10–p90) at that rung, against 7.8–9.0 for 0.2.0.

| Retrieval check (153 items, R@k over the 137 with expected titles) | R@1 | R@5 | R@10 | MRR | Search p50 / p90 |
|---|---|---|---|---|---|
| Keyword queries, this release | 38.0 % | 47.4 % | 49.6 % | 0.42 | 1.1 s / 2.6 s |
| Keyword queries, 0.2.0 | 11.7 % | 24.1 % | 29.2 % | 0.16 | 0.55 s / 1.3 s |
| Raw questions (`--query-field question`), this release | 38.0 % | 44.5 % | 46.7 % | 0.41 | 1.4 s / 3.4 s |

The retrieval checks ran without the optional semantic rerank (the embedding server wasn't running), and in the answer runs it was up for only about 45 minutes of 5 hours: it was stopped as idle while search used it, a bug fixed since. A search takes about twice as long as in 0.2.0: it now looks up more titles and follows redirects, and with the model at full size Windows' file cache is small, so more reads go to disk ([DECISIONS.md](DECISIONS.md), D10 and D14).
