Feature: Voice activity detection
  A pause after speech auto-stops the turn. The settled 900 ms silence
  window (vad.silence_ms) ends an utterance; shorter pauses do not.

  Scenario: Silence synthesizes to the floor and a sine measures above the gate
    When I convert PCM to dBFS
    Then silence should be -100 dBFS
    And a full-scale sine should be near -3 dBFS

  Scenario: Reads reassemble into exact frames
    When I frame a 1500-byte read stream
    Then there should be 2 full frames
    And the tail should be 220 bytes

  Scenario: A read timeout is not end of stream
    When a read stream times out before data arrives
    Then the reader should have produced a frame

  Scenario: Parec argv selects the source with -d
    Then the parec argv should use "-d" for "@DEFAULT_SOURCE@"

  Scenario: A pause after speech auto-stops at the silence window
    Given an endpointer with silence window 900 ms
    When speech runs for 2 seconds then silence runs for 900 ms
    Then the endpointer should report "silence"

  Scenario: A mid-sentence pause shorter than the window does not stop
    Given an endpointer with silence window 900 ms
    When speech runs for 2 seconds then silence runs for 400 ms
    Then the endpointer should report nothing

  Scenario: A cough-length blip is discarded
    Given an endpointer with silence window 900 ms
    When speech runs for 100 ms then silence runs for 900 ms
    Then the endpointer should report "min_speech"

  Scenario: Sustained speech hits the max duration cap
    Given an endpointer with silence window 900 ms
    When speech runs for 16 seconds
    Then the endpointer should report "max_duration"

  Scenario: No speech hits the start timeout
    Given an endpointer with silence window 900 ms
    When silence runs for 6 seconds
    Then the endpointer should report "start_timeout"

  Scenario: Default config selects the energy backend
    Given an empty agavai config
    When I resolve the vad backend
    Then the resolved backend should be "energy"

  Scenario: Unavailable silero resolves to energy and still auto-stops
    Given a config with vad backend "silero", silence window 900 ms and no Silero model
    When I resolve the vad backend
    Then the resolved backend should be "energy"

  @vad_model
  Scenario: Silero ends each spoken request once and never a noise-only turn
    Given the streaming VAD uses the installed Silero model with a 1100 ms quiet window
    When I replay "clean.af_bella.04", "turn.noise" and "turn.pause.700ms" through one endpointer
    Then "clean.af_bella.04" ends once, within 1.2 seconds of its speech
    And "turn.noise" never ends a turn
    And "turn.pause.700ms" ends once, within 1.2 seconds of its speech

  Scenario: Streaming Silero without its model fails before capture
    Given the streaming VAD selects Silero without its model
    When I build the streaming endpointer
    Then building it fails with "Silero VAD is unavailable: model missing"
    And building it fails with "Run scripts/download-vad.sh."
