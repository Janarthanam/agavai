# Whistle turn completion and Needle no-match report

## Why speech did not submit

The deployed config selected `whistle-cactus` with `endpoint = "manual"`. Whistle provides streaming words and a final flush, but no native end-of-turn event. The session therefore kept waiting for Enter, even after the microphone became quiet. The overlay incorrectly continued saying that the request would send when speaking finished.

This was an incomplete deployment of the expected voice interaction. Earlier tests proved recognition, explicit finalization and cancellation; they did not test automatic turn completion for Whistle. Treating those checks as enough for a voice deployment missed the behavior the user needed.

The fix adds explicit `endpoint = "vad"` using the existing energy classifier and endpointer over the same microphone PCM. The recognizer continues receiving audio while the classifier measures 20 ms frames. At least 250 ms of speech followed by 900 ms of quiet requests a final flush; only that final transcript is submitted. Initial silence does not submit, a shorter pause keeps listening, brief noise is discarded, and cancellation or duration limits do not execute a request. Enter remains available. Manual mode now explicitly says to press Enter.

## Why “No matching tool call” was spoken

The latest captured request was: “Thank you. Show me all the tools considered there.” Replaying that text against the installed model produced:

1. The keyword router selected no tool heads; Needle received an empty tool list.
2. Needle returned `function_calls: []`, with the native explanation “no tools declared, returning the empty call.” There is currently no tool for describing the assistant's available tools or its routing trace.
3. The adapter correctly classified this as unsupported. However, the deployed config had no `[brain.large]`, so escalation was unavailable.
4. The coordinator raised the adapter's internal diagnostic as an error, then returned that same string for display and speech. This last step was the user-facing bug.

The earlier “what time is it” failure has a different upstream cause: the router did offer `clock_now`, but Needle returned no calls and claimed that only reminder tools existed. That is a model selection error, not a missing clock implementation. “Open the browser” returned the correct `launch(browser)` call in the same probe.

Unsupported or empty responses without a usable larger tier now produce: “I could not handle that request. Try asking me to open an app or find a file.” The original reason, backend and offered tool names remain in debug logs. With a larger tier configured, the existing escalation path still runs before producing failure feedback. No action is invented or reported as successful.

## Limits

Needle remains the selected local tool model; this fix does not make it a general conversational model or add a hidden Qwen fallback. Unhandled requests can still occur, but they no longer speak the raw no-match diagnostic. A larger configured model is needed to recover broader requests automatically.

Energy endpointing detects quiet, not sentence meaning. Long pauses can split a request, and background noise can delay submission. The quiet window and thresholds are configurable. Recorded-audio checks establish integration; microphone conditions still need user verification.

## Verification

All 297 Behave scenarios / 1533 steps passed, including native Parakeet and Cactus checks. The suite uses the explicit Parakeet example config because its frontend tests need the Parakeet environment; Cactus checks use the installed Cactus environment:

```bash
PYTHONPATH=src AGAVAI_CONFIG="$PWD/share/config.example.toml" \
  AGAVAI_CACTUS_TEST_DIR="$HOME/.local/share/agavai/cactus" \
  .venv/bin/behave --format progress
```

New checks cover automatic streaming/batch finalization through the capture path, identical replay results, initial silence, a 700 ms mid-request pause, short-noise rejection, cancellation, Enter, maximum duration, irregular PCM packets and final short frames. The native UI check verifies different instructions for manual and automatic modes. Both reported unsupported requests have feedback regressions; larger-tier escalation remains covered.
