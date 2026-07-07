# Cursor Model Pricing

Source: user-provided export from Cursor Docs, `https://cursor.com/docs/models-and-pricing`.

Verified: 2026-05-17 (all rows matched Cursor's published page exactly; no updates required).

Updated 2026-06-02: added Composer 2.5 and Composer 2.5 (Fast) rows, confirmed against Cursor's published pricing page. Note the Fast variant does not scale all axes by a flat multiplier: input is 6x ($0.5 -> $3) and output is 6x ($2.5 -> $15), but cache read is only 2.5x ($0.2 -> $0.5). Don't assume fast cache-read = 6x base.

All prices are USD per 1M tokens. A dash means the supplied table did not list a separate cache-write price.

| Name | Input | Cache Write | Cache Read | Output |
| --- | ---: | ---: | ---: | ---: |
| Claude 4 Sonnet | $3 | $3.75 | $0.3 | $15 |
| Claude 4 Sonnet 1M | $6 | $7.5 | $0.6 | $22.5 |
| Claude 4.5 Haiku | $1 | $1.25 | $0.1 | $5 |
| Claude 4.5 Opus | $5 | $6.25 | $0.5 | $25 |
| Claude 4.5 Sonnet | $3 | $3.75 | $0.3 | $15 |
| Claude 4.6 Opus | $5 | $6.25 | $0.5 | $25 |
| Claude 4.6 Opus (Fast mode) | $30 | $37.5 | $3 | $150 |
| Claude 4.6 Sonnet | $3 | $3.75 | $0.3 | $15 |
| Claude 4.7 Opus | $5 | $6.25 | $0.5 | $25 |
| Claude Opus 4.7 (fast mode) | $30 | $37.5 | $3 | $150 |
| Composer 1 | $1.25 | - | $0.125 | $10 |
| Composer 1.5 | $3.5 | - | $0.35 | $17.5 |
| Composer 2 | $0.5 | - | $0.2 | $2.5 |
| Composer 2.5 | $0.5 | - | $0.2 | $2.5 |
| Composer 2.5 (Fast) | $3 | - | $0.5 | $15 |
| Gemini 2.5 Flash | $0.3 | - | $0.03 | $2.5 |
| Gemini 3 Flash | $0.5 | - | $0.05 | $3 |
| Gemini 3 Pro | $2 | - | $0.2 | $12 |
| Gemini 3 Pro Image Preview | $2 | - | $0.2 | $12 |
| Gemini 3.1 Pro | $2 | - | $0.2 | $12 |
| GPT-5 | $1.25 | - | $0.125 | $10 |
| GPT-5 Fast | $2.5 | - | $0.25 | $20 |
| GPT-5 Mini | $0.25 | - | $0.025 | $2 |
| GPT-5-Codex | $1.25 | - | $0.125 | $10 |
| GPT-5.1 Codex | $1.25 | - | $0.125 | $10 |
| GPT-5.1 Codex Max | $1.25 | - | $0.125 | $10 |
| GPT-5.1 Codex Mini | $0.25 | - | $0.025 | $2 |
| GPT-5.2 | $1.75 | - | $0.175 | $14 |
| GPT-5.2 Codex | $1.75 | - | $0.175 | $14 |
| GPT-5.3 Codex | $1.75 | - | $0.175 | $14 |
| GPT-5.4 | $2.5 | - | $0.25 | $15 |
| GPT-5.4 Mini | $0.75 | - | $0.075 | $4.5 |
| GPT-5.4 Nano | $0.2 | - | $0.02 | $1.25 |
| GPT-5.5 | $5 | - | $0.5 | $30 |
| Grok 4.20 | $2 | - | $0.2 | $6 |
| Grok 4.3 | $1.25 | - | $0.2 | $2.5 |
| Kimi K2.5 | $0.6 | - | $0.1 | $3 |
