Feature: Speech survives streaming boundaries
  Numerical frontend checks and real speech replays run in the configured ASR
  venv. Model replays require scripts/download-asr.sh; exclude @asr_model for
  the suite without model assets.

  Scenario: Transport packet boundaries do not change audio features
    When I check the streaming frontend against a whole-waveform spectrogram
    Then the ASR worker check passes

  Scenario: A short final audio tail is retained exactly once
    When I check the streaming frontend with short audio tails
    Then the ASR worker check passes

  @asr_model
  Scenario: A spoken sentence is retained across packet boundaries
    When I replay the ASR speech fixture with different packet sizes
    Then the ASR worker check passes

  @asr_model
  Scenario: Silence before speech does not discard the first words
    When I replay the ASR speech fixture after initial silence
    Then the ASR worker check passes

  @asr_model
  Scenario: Reset starts the next spoken turn without stale audio
    When I replay the ASR speech fixture in two successive turns
    Then the ASR worker check passes

  @asr_model
  Scenario: A recording keeps every utterance and its timing
    When I replay the ASR speech fixture as one continuous recording
    Then the ASR worker check passes
