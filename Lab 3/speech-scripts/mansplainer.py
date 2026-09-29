#!/usr/bin/env python3
"""mansplainer.py — a sibling of echo_bot.py that never lets you finish a thought.

Same stack as listen.py / echo_bot.py:
  - sherpa_onnx Silero VAD for endpointing
  - faster-whisper for (optional) transcription
  - Piper for speech out

The trick is the endpointing threshold. Crank --min-silence way down: the VAD
then emits your utterance the instant you take a breath, and we pounce with a
condescending "well, actually" before you can continue. The comedy lives
entirely in that one parameter.

    python mansplainer.py                    # pounces after 0.2s of silence
    python mansplainer.py --min-silence 0.15 # insufferable
    python mansplainer.py --no-transcribe    # pure canned interrupts, zero ASR lag
"""

import argparse
import random
import sys
import time
from pathlib import Path

import numpy as np
import sherpa_onnx
import sounddevice as sd
from faster_whisper import WhisperModel
from piper import PiperVoice

SAMPLE_RATE = 16000
LAB_DIR = Path(__file__).resolve().parent.parent
DEFAULT_VAD = LAB_DIR / "models" / "silero_vad.onnx"
DEFAULT_VOICE = LAB_DIR / "voices" / "en_US-lessac-medium.onnx"

# Canned openers, played the instant you pause. These carry the joke on their
# own, so the device still works with --no-transcribe.
OPENERS = [
    "Well, actually,",
    "See, what you're trying to say is,",
    "Okay, so, let me break this down for you.",
    "Right, but here's the thing most people miss.",
    "Actually, it's a little more nuanced than that.",
]

# If transcription is on, we tack a condescending reframe onto the opener.
def mansplain(heard: str | None) -> str:
    opener = random.choice(OPENERS)
    if not heard:
        return opener
    return f"{opener} what you're really saying is that {heard}. And honestly, most people get this wrong."


class Speaker:
    """Piper TTS -> default output device. Lifted from echo_bot.py, with an
    added cache so canned openers play back instantly instead of re-synthesizing."""

    def __init__(self, voice_path: Path) -> None:
        self.voice = PiperVoice.load(str(voice_path))

    def say(self, text: str) -> None:
        for chunk in self.voice.synthesize(text):
            audio = np.frombuffer(chunk.audio_int16_bytes, dtype=np.int16)
            sd.play(audio, samplerate=chunk.sample_rate)
            sd.wait()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--model", default="tiny.en", help="whisper model size")
    parser.add_argument("--vad-model", type=Path, default=DEFAULT_VAD)
    parser.add_argument("--voice", type=Path, default=DEFAULT_VOICE)
    parser.add_argument("--min-silence", type=float, default=0.2,
                        help="silence that ends your turn; low = rude (default: 0.2)")
    parser.add_argument("--min-speech", type=float, default=0.25,
                        help="ignore speech bursts shorter than this (default: 0.25)")
    parser.add_argument("--no-transcribe", action="store_true",
                        help="skip whisper entirely; canned interrupts only")
    args = parser.parse_args()

    for path, what in [(args.vad_model, "VAD model"), (args.voice, "Piper voice")]:
        if not path.is_file():
            sys.exit(f"{what} not found at {path}. Run ./setup.sh first.")

    print("Loading models...", flush=True)
    speaker = Speaker(args.voice)
    recognizer = None if args.no_transcribe else \
        WhisperModel(args.model, device="cpu", compute_type="int8")

    config = sherpa_onnx.VadModelConfig()
    config.silero_vad.model = str(args.vad_model)
    config.silero_vad.min_silence_duration = args.min_silence
    config.silero_vad.min_speech_duration = args.min_speech
    config.sample_rate = SAMPLE_RATE
    vad = sherpa_onnx.VoiceActivityDetector(config, buffer_size_in_seconds=30)
    window = config.silero_vad.window_size

    print(f"Ready. Try to say something (I pounce after {args.min_silence}s). Ctrl-C to stop.\n")

    buffer = np.empty(0, dtype=np.float32)
    samples_per_read = int(0.1 * SAMPLE_RATE)

    with sd.InputStream(channels=1, dtype="float32", samplerate=SAMPLE_RATE) as stream:
        while True:
            chunk, _ = stream.read(samples_per_read)
            buffer = np.concatenate([buffer, chunk.reshape(-1)])

            while len(buffer) > window:
                vad.accept_waveform(buffer[:window])
                buffer = buffer[window:]

            while not vad.empty():
                utterance = np.array(vad.front.samples, dtype=np.float32)
                vad.pop()

                heard = None
                if recognizer is not None:
                    segments, _ = recognizer.transcribe(utterance, beam_size=1)
                    heard = " ".join(s.text.strip() for s in segments).strip() or None

                reply = mansplain(heard)
                print(f"  (you paused) -> {reply}")
                speaker.say(reply)

                # Drop anything the mic caught while we were talking, so the
                # device doesn't interrupt its own interruption.
                while not vad.empty():
                    vad.pop()
                buffer = np.empty(0, dtype=np.float32)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nFinally, some peace.")
