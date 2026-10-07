# ASR speech fixture

`asr-sentence.wav` is synthetic speech generated locally with Kokoro-82M,
voice `af_bella`, then resampled from 24 kHz to 16 kHz mono PCM16. It contains:

> Please find the meeting notes from yesterday and open the document in my downloads folder.

The replay tests append two seconds of silence and send the same audio in
different packet sizes. The original worker emitted four premature nonempty
end-of-utterance events, starting with “please find the meet”. The corrected
worker must emit one event containing the complete sentence. A second test
replays it twice with an explicit protocol reset between turns.
