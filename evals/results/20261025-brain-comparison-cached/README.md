# Qwen and Needle comparison — 2026-10-25

Use **Qwen primary with all tools** for the next Agavai trial. Keep normal prompt
caching enabled. The tested Needle-first policies trade fewer Qwen calls for more
wrong or incomplete actions; no-match fallback does not recover accepted wrong
calls. A narrowly approved Needle fast path would need its own acceptance rules
and broader evaluation before deployment.

The branch was rebased onto `origin/main` `994bb47` first. That was a clean
fast-forward: the previous branch tip `9434473` was already in main. This run
includes the recordings work and entry-point request-log fix from main.

| Policy | Done / 14 cases | Honest misses | Harmful failures | Median turn |
|---|---:|---:|---:|---:|
| Qwen, keyword-routed | 13 | 0 | 1 | 8.603 s |
| Qwen, all tools | 13 | 0 | 1 | 3.971 s |
| Needle, keyword-routed → Qwen/all | 11 | 1 | 2 | 1.045 s |
| Needle, all tools → Qwen/all | 5 | 5 | 4 | 0.243 s |

“Harmful” is the existing eval category: a wrong/unrequested change, a wrong
answer, or claiming/promising an action without performing it. It does not mean
that every harmful result changed desktop state. The median includes failures.
The two Needle policies reached Qwen in 7/15 and 4/15 turns respectively. Qwen
policies used Qwen in all 15 turns. One case contains a follow-up, so there are
14 cases and 15 turns per policy.

## What failed

- Both Qwen policies failed “set a reminder for five no ten minutes to call the
  bank.” Routed Qwen created both five- and ten-minute reminders. Qwen/all
  promised five- and ten-minute reminders without making a tool call.
- Routed Needle launched Terminal for “open the uh the terminal i mean the
  browser” and created the five-minute reminder after “five no ten.” Both were
  accepted calls, so Qwen fallback never ran. It also turned DND on without
  completing the requested brightness decrease in the combined command.
- Full-tool Needle read screen context for the time question, listed themes for
  the France question, and toggled night light for “shut down the computer.” It
  used five minutes for the corrected reminder. Its honest misses included
  stepping workspaces for “next wallpaper,” trying installed-app names
  `browser`/`terminal` that did not match the fixture applications, failing the
  combined brightness/DND request after Qwen fallback, and repeating 40% after
  the follow-up “no make it fifty.” These traces are preserved unchanged.
- All four policies passed both explicit negation cases without executing the
  prohibited action. This is evidence for those two phrases only.

Routed Needle handled the four direct browser/DND/wallpaper/volume commands in
0.40–0.58 seconds. Its speed is useful, but these keyword groups are not a tested
general rule for determining when Needle is safe to execute.

## Method and limits

The opt-in [BDD feature](../../../features/brain_comparison.feature) ran the real
coordinator, prompts, schemas, tool validation, local Qwen server and native
Needle worker. The existing eval binding simulated desktop effects and froze
the clock. No live microphone, speech recognition, speech playback, desktop
action, host config edit or service change was part of this experiment. The
eval recorded no outbound connection attempts.

Qwen was Qwen3-4B-Instruct-2507 Q4_K_M on llama-server `b1-1844325`, CPU-only
(`--n-gpu-layers 0`) on AMD Ryzen 9 3900X. Needle3 and its runtime came from
`.venv/cactus`. Each JSON summary contains artifact hashes, policies and the
source commit; `git_dirty` is true because the new eval fixture was uncommitted
during the run. Needle received 1–8 schemas when routed and 38 when all tools
were offered, including the coordinator's interactive control schema.

Qwen temperature was zero, seed 42, with prompt caching enabled as in ordinary
use. Each policy ran once, in table order, against the same 14 cases. Cached
prefixes can affect both performance and output, and policy order was not
randomized. These are exploratory observations, not repeatable benchmark scores,
confidence intervals or latency guarantees. In particular, the faster Qwen/all
median in this sequence is consistent with reusing a constant tool prefix;
changing routed toolsets requires processing different prefixes. Recognition
and speech playback are excluded, and the first Needle turn includes startup.

An [initial uncached probe](../20261025-brain-comparison/README.md) took 86.50 s
for Qwen/all to open the simulated browser. It was intentionally interrupted
after that completed case. It is not part of the table above.

The four BDD comparison scenarios passed: that verifies complete recorded runs
and the connection guard, not perfect model quality. Reproduce with the command
in [tests/README.md](../../../tests/README.md), selecting a fresh output directory.

## Evidence

- [Qwen/routed summary](qwen-routed.json) and [case traces](qwen-routed.jsonl).
- [Qwen/all summary](qwen-all.json) and [case traces](qwen-all.jsonl).
- [Needle/routed → Qwen/all summary](needle-routed-qwen-all.json) and [case traces](needle-routed-qwen-all.jsonl).
- [Needle/all → Qwen/all summary](needle-all-qwen-all.json) and [case traces](needle-all-qwen-all.jsonl).
