#!/usr/bin/env python3
"""ask_number.py — combine Part A (Piper TTS) with Part B (faster-whisper STT).

Piper asks for a phone number, arecord captures the answer to a WAV, and
base.en transcribes it. A quick end-to-end test of speech-out + speech-in.

    python ask_number.py
"""

import subprocess
from pathlib import Path

from faster_whisper import WhisperModel

LAB_DIR = Path(__file__).resolve().parent.parent
VOICES = LAB_DIR / "voices"
QUESTION = "What is your phone number?"
RECORD_SECONDS = 7          # long enough to say a full number, with pauses
ANSWER_WAV = "answer.wav"

# --- Part A: Piper asks the question out loud ---
subprocess.run([
    "python3", "-m", "piper",
    "--model", "en_US-lessac-medium",
    "--data-dir", str(VOICES),
    "--output-file", "question.wav",
    "--", QUESTION,
], check=True)
subprocess.run(["aplay", "question.wav"], check=True)
print(f'Asked: "{QUESTION}"')

# --- Record the spoken answer ---
print(f"Recording for {RECORD_SECONDS}s... speak now.")
subprocess.run([
    "arecord", "-d", str(RECORD_SECONDS),
    "-f", "cd", "-c", "1", "-r", "16000", ANSWER_WAV,
], check=True)

# --- Part B: transcribe the answer with base.en ---
model = WhisperModel("base.en", device="cpu", compute_type="int8")
segments, _ = model.transcribe(ANSWER_WAV, beam_size=1)
text = " ".join(s.text.strip() for s in segments)
print(f'Heard: "{text}"')
