Feature: Durable sessions preserve observable facts without replaying actions
  Background:
    Given a headless harness with a local scripted language service

  Scenario: Context and ordered facts survive a separate process restart
    When a separate persistent process asks "explain gravity"
    And another process continues that session with "explain that again"
    Then the resumed model request includes "explain gravity"
    And the session ledger contains both turns and ordered lifecycle events
    And session inspection includes the effective configuration fingerprint
    And no headless UI snapshot was created

  Scenario: Full desktop outcomes are durable before the reply
    Given the action service proposes a browser launch
    When the harness receives "open the browser"
    Then durable executions match the full harness outcomes

  Scenario: A process death during a desktop action has an unknown outcome
    When a separate process dies while launching a browser
    Then inspection reports an interrupted turn and unknown action
    When another process continues that session with "yes"
    Then no old action is replayed and a fresh instruction is required

  Scenario: A saved confirmation is never restored as authority
    Given the action service prepares a browser confirmation
    When the harness receives "open the browser but confirm first"
    And the harness closes and resumes its session
    And the harness receives "yes"
    Then no harness desktop action was dispatched
    And the harness response contains "fresh instruction"

  Scenario: A second process cannot mutate a live session
    When another process tries to resume the active harness session
    Then session resume is rejected as already active

  Scenario: The native projection rebuilds saved turns on resume
    When the harness receives "explain gravity"
    And the native adapter resumes that saved session
    Then the native snapshot identifies a resumed durable session with its prior answer

  Scenario: Separate sessions have separate context
    When the harness receives "explain gravity"
    And a new harness session receives "hello"
    Then the new session has no gravity context

  Scenario: Persistence can be disabled
    Given persistence is disabled for the next harness
    When a new harness session receives "hello"
    Then the temporary session has no durable ledger entry

  Scenario Outline: Accepted spoken audio is attached to its exact turn
    Given spoken audio encoding uses "<encoding>"
    When the voice controller accepts "explain gravity" with captured audio
    Then the accepted turn has checksummed "<codec>" audio without idle silence
    And no PCM bytes appear in the durable event stream

    Examples:
      | encoding | codec     |
      | opus     | opus      |
      | absent   | pcm_s16le |
      | timeout  | pcm_s16le |

  Scenario Outline: Abandoned captures retain no audio
    When the voice controller receives an "<ending>" capture
    Then no accepted spoken turn or audio attachment was saved

    Examples:
      | ending |
      | empty  |
      | cancel |
      | error  |

  Scenario: Audio can be disabled while keeping the transcript
    Given spoken-turn audio retention is disabled
    When the voice controller accepts "explain gravity" with captured audio
    Then the spoken transcript is saved without audio

  Scenario: An audio quota retains text and reports the refused attachment
    Given the session audio quota is one megabyte
    When the voice controller accepts a long audio turn
    Then the saved turn reports audio quota exceeded

  Scenario: Process death during encoding cannot claim completed audio
    When a separate process dies while encoding accepted turn audio
    Then saved audio is reported incomplete on inspection and resume

  Scenario: Missing audio is visible in inspection and export
    When the voice controller accepts "explain gravity" with captured audio
    And the finalized attachment goes missing
    Then inspection and export report missing audio

  Scenario: Session export and deletion preserve referenced recordings
    Given a saved harness recording with "We use cube flow for training."
    When the harness receives "summarize the last recording"
    And the harness receives "replace cube flow with Kubeflow"
    And the harness closes and resumes its session
    And the session is exported and deleted through the CLI
    Then the exported ledger retains source revisions and corrected context
    And the referenced recording and its audio still exist

  Scenario: A missing recording reference remains inspectable
    Given a saved harness recording with "We use Kubeflow."
    When the harness receives "summarize the last recording"
    And the referenced recording is moved away
    Then session inspection reports an unavailable source

  Scenario: Explicit pruning deletes only expired inactive sessions
    When expired and recent sessions are pruned through the CLI
    Then only the expired session is removed

  Scenario: A newer storage schema is rejected explicitly
    When a separate CLI encounters a newer session schema
    Then the CLI rejects the unsupported schema

  Scenario: A storage failure prevents desktop dispatch
    Given the action service proposes a browser launch
    And the session database rejects execution-start writes
    When the headless harness attempts "open the browser"
    Then the persistence failure reaches the caller before execution
    And no harness desktop action was dispatched

  Scenario: Resume retains full history after prompt compaction
    Given a long harness conversation with completed screen reads
    When the harness receives "explain the result"
    Then the model received complete exchanges within its byte budget
    When the harness closes and resumes its session
    Then original harness exchanges and outcomes are retained
    And the durable ledger still contains all pre-compaction outcomes

  Scenario: The next voice capture can start while prior audio is encoding
    When two spoken turns arrive while the first audio encoder waits
    Then both turns finish with separate ready audio attachments

  @native_sessions
  Scenario: Session history and identity work in the actual native overlay
    When the native session history check runs
    Then native session selection and typed continuation checks pass

  Scenario: Persistence failure stops the voice controller before another capture
    Given the action service proposes a browser launch
    And the session database rejects execution-start writes
    When the voice controller attempts the action with unavailable storage
    Then persistence failure closes the listener without another capture or action

  Scenario: Recovery remains guarded if the process stops again before a new turn
    When a separate process dies while launching a browser
    And another process restores the interrupted session and exits
    And another process continues that session with "continue"
    Then no old action is replayed and a fresh instruction is required

  Scenario Outline: Invalid persistence settings fail at the CLI boundary
    When the session CLI loads "<setting>"
    Then the persistence configuration error names "<field>"

    Examples:
      | setting             | field          |
      | save_audio="false"  | save_audio     |
      | retention_days=-1   | retention_days |
      | max_audio_mb=true   | max_audio_mb   |

  Scenario: A completed action survives a crash before reply delivery without a duplicate exchange
    When a separate process dies after completing the action but before replying
    And another process continues that session with "yes"
    Then the recovered context has one complete exchange and preserves the known outcome

  @asr_model
  Scenario: The actual streaming capture pump retains accepted speech audio
    When real streaming recognition accepts the speech fixture through the capture pump
    Then the recognized turn and actual captured waveform are durable

  Scenario: Corrupt session storage produces an explicit CLI error
    When the session CLI encounters a corrupt database
    Then the CLI reports the database failure without creating a session
