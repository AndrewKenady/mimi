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
| kiwix search + 3 passages | 0.2–2.3 s |
| GeoNames/Wikipedia nearby (16 km) | 3–22 ms |
| Valhalla route, 98 mi | 0.1 s |
| Map tiles (US + Canada, z0–14) | 15.6 GB, local range requests |
