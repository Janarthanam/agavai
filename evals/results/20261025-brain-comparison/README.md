# Initial uncached probe (incomplete)

On 2026-10-25, the first Qwen/all browser case passed in 86.50 seconds through
the real coordinator and simulated desktop. Temperature was zero, seed 42,
prompt caching disabled. The first model call spent 37.70 seconds evaluating
3,049 prompt tokens and 2.24 seconds decoding (local llama-server journal).

The agent intentionally interrupted this BDD run before the second case finished
to compare normal cached operation and add a routed-Qwen baseline. This file is
one observation, not a completed comparison or a performance guarantee. Its
trace is preserved in `qwen-all.jsonl`; the completed cached experiment is in
`../20261025-brain-comparison-cached/`.
