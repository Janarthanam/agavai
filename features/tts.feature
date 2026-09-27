Feature: Talk-back with Kokoro-82M
  Whisper is STT only. Spoken replies use Kokoro on CPU when the venv and ONNX files exist.

  Scenario: Kokoro is used when the CPU venv and model files exist
    Given a kokoro-ready temp config
    When I speak "hello from agavai"
    Then the speak engine should be "kokoro"
    And the synth command should run the TTS venv python

  Scenario: Missing Kokoro files do not crash speak
    Given a config that prefers kokoro with no assets
    When I speak "hello from agavai"
    Then the speak engine should not be "kokoro"
