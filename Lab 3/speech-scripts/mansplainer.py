#!/usr/bin/env python3
"""mansplainer.py — a sibling of echo_bot.py that never lets you finish a thought.

Same stack as listen.py / echo_bot.py:
  - sherpa_onnx Silero VAD for endpointing
  - faster-whisper for transcription
  - Piper for speech out

--min-silence is how long a breath has to last before we talk. Understanding
starts while you are still talking: a side thread transcribes the audio so
far and fetches the opening sentence of the Wikipedia page for the longest
content word. The breath only has to start playback.

A missing page, or a lookup that takes longer than 1.2s, falls back to a
paraphrase, so a dead network still finishes the turn. The fetch needs Wi-Fi
on the Pi. A hit is usually a few tenths of a second; the timeout is the
worst case, and it only bites when nothing was cached while you were talking.

    python mansplainer.py
    python mansplainer.py --min-silence 0.15   # insufferable
    python mansplainer.py --partial 0.4        # transcribe sooner, more often
    python mansplainer.py --no-transcribe      # canned interrupts, no ASR
"""

import argparse
import json
import random
import re
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
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
    "Fun fact.",
    "Let me just chime in.",
    "Not to be the devil's advocate.",
    "Well, actually.",
    "Okay, so, let me break this down for you.",
    "Right, but here's the thing most people miss.",
    "Actually, it's a little more nuanced than that.",
    "Sorry, real quick.",
    "I don't mean to interrupt.",
    "Hold on, this is the interesting part.",
    "Since you brought it up.",
    "Funny you should say that.",
    "Quick sidebar.",
    "Before you finish that thought.",
    "That's adjacent to a better point.",
]

# Words that don't carry the point. Dropped so a paraphrase isn't your sentence again.
_STOP = {
    "a", "an", "the", "i", "you", "we", "they", "he", "she", "it", "me", "my",
    "your", "our", "their", "to", "of", "and", "or", "but", "if", "in", "on",
    "for", "with", "at", "from", "as", "is", "are", "was", "were", "be", "been",
    "am", "do", "did", "does", "have", "has", "had", "that", "this", "these",
    "those", "just", "so", "like", "um", "uh", "yeah", "well", "okay", "ok",
    "really", "very", "about", "into", "than", "then", "there", "here", "when",
    "what", "how", "why", "who", "which", "because", "going", "gonna", "wanna",
    "want", "think", "know", "mean", "said", "say", "saying", "im", "i'm", "ive",
    "i've", "id", "i'd", "its", "it's", "dont", "don't", "doesnt", "doesn't",
    "didnt", "didn't", "cant", "can't", "wont", "won't", "isnt", "isn't",
    "wasnt", "wasn't", "youre", "you're", "thats", "that's", "lets", "let's",
    "maybe", "probably", "actually", "basically", "literally", "still", "already",
    "also", "got", "get", "getting", "now", "something", "anything", "everything",
    "nothing", "someone", "everyone", "keep", "keeps", "kept", "make", "makes",
    "should", "could", "would", "can", "will", "shall", "might", "must",
}

_WIKI = "https://en.wikipedia.org/api/rest_v1/page/summary/"
_fact_cache: dict[str, str | None] = {}
_fact_lock = threading.Lock()
_fact_wait: dict[str, threading.Event] = {}

_PARAPHRASES = (
    "The shorter version is that this is about {topic}, and the long version was mostly decoration.",
    "What that actually amounts to is {topic}. The extra detail doesn't change the claim.",
    "You're circling {topic}. That is the whole point, and the rest is scenery.",
    "Strip it down and it's a point about {topic}. The story around it is optional.",
    "The part that matters is {topic}. Everything else was you warming up.",
)

_GENERIC = (
    "There's a shorter way to put that, and it isn't the way you were heading.",
    "The claim under that sentence is smaller than the sentence.",
    "You buried the point. The point was the first concrete thing, and then you kept talking.",
)


def _topic(heard: str) -> str:
    """One or two content words, not a clip of the original sentence."""
    words = re.findall(r"[a-z0-9']+", heard.lower())
    kept = []
    for w in words:
        if w in _STOP or len(w) <= 2 or w in kept:
            continue
        kept.append(w)
    if not kept:
        return ""
    # Longest words are the ones carrying the point. Keep at most two.
    salient = sorted(kept, key=len, reverse=True)[:2]
    if len(salient) == 1:
        return salient[0]
    return f"{salient[0]} and {salient[1]}"


def _keyword(heard: str) -> str | None:
    """The single most salient content word — the thing to look up."""
    words = re.findall(r"[a-z0-9']+", heard.lower())
    kept = [w for w in words if w not in _STOP and len(w) > 2]
    if not kept:
        return None
    return max(kept, key=len)


def _fetch_summary(term: str, timeout: float) -> tuple[str | None, bool]:
    """Return (first sentence or None, whether that result is worth caching).

    A missing page stays cached. A network hiccup does not, so the next
    breath can try again once Wi-Fi is back.
    """
    try:
        url = _WIKI + urllib.parse.quote(term, safe="")
        req = urllib.request.Request(url, headers={"User-Agent": "mansplainer-lab/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.load(resp)
        if data.get("type") == "disambiguation":
            return None, True
        extract = (data.get("extract") or "").strip()
        if not extract:
            return None, True
        return re.split(r"(?<=[.!?])\s", extract)[0], True
    except urllib.error.HTTPError as exc:
        return None, exc.code == 404
    except Exception:
        return None, False


def _live_fact(heard: str, timeout: float = 1.2) -> str | None:
    """Opening sentence of the Wikipedia summary for the topic word.

    Callers looking up the same word share one request.
    """
    term = _keyword(heard)
    if not term:
        return None

    with _fact_lock:
        if term in _fact_cache:
            return _fact_cache[term]
        wait = _fact_wait.get(term)
        if wait is None:
            wait = threading.Event()
            _fact_wait[term] = wait
            owner = True
        else:
            owner = False

    if not owner:
        wait.wait(timeout + 0.3)
        with _fact_lock:
            return _fact_cache.get(term)

    fact, cacheable = _fetch_summary(term, timeout)
    with _fact_lock:
        if cacheable:
            _fact_cache[term] = fact
        _fact_wait.pop(term, None)
    wait.set()
    return fact


def _prefetch(heard: str) -> None:
    """Start the Wikipedia fetch now, so the breath doesn't have to."""
    term = _keyword(heard)
    if not term:
        return
    with _fact_lock:
        if term in _fact_cache or term in _fact_wait:
            return
    threading.Thread(target=_live_fact, args=(heard,), daemon=True).start()


def _paraphrase(heard: str) -> str:
    topic = _topic(heard)
    if not topic:
        return random.choice(_GENERIC)
    return random.choice(_PARAPHRASES).format(topic=topic)


def mansplain(heard: str | None) -> str:
    opener = random.choice(OPENERS)
    if not heard:
        return opener
    body = _live_fact(heard) or _paraphrase(heard)
    return f"{opener} {body}"


def _transcribe(recognizer: WhisperModel, audio: np.ndarray) -> str | None:
    if len(audio) < int(0.15 * SAMPLE_RATE):
        return None
    segments, _ = recognizer.transcribe(
        audio,
        beam_size=1,
        language="en",
        without_timestamps=True,
        condition_on_previous_text=False,
    )
    text = " ".join(seg.text.strip() for seg in segments).strip()
    return text or None


class Transcriber:
    """faster-whisper on a side thread, over the words still being said.

    The model decodes a clip; it does not emit a word at a time. Every
    `partial` seconds of new speech we decode the utterance so far and start
    the Wikipedia fetch. When the VAD hears a breath, that line is usually
    already in hand.
    """

    def __init__(self, recognizer: WhisperModel | None, partial: float) -> None:
        self._recognizer = recognizer
        self._partial_n = int(max(partial, 0.3) * SAMPLE_RATE)
        self._cv = threading.Condition()
        self._frames: list[np.ndarray] = []
        self._n = 0
        self._heard: str | None = None
        self._heard_n = 0
        self._job: np.ndarray | None = None
        self._busy = False
        self._busy_gen = -1
        self._gen = 0
        if recognizer is not None:
            threading.Thread(target=self._loop, name="live-whisper", daemon=True).start()

    def extend(self, frame: np.ndarray) -> None:
        if self._recognizer is None or len(frame) == 0:
            return
        with self._cv:
            self._frames.append(np.array(frame, dtype=np.float32, copy=True))
            self._n += len(frame)
            self._schedule_locked()

    def latest(self) -> str | None:
        with self._cv:
            return self._heard

    def has_audio(self) -> bool:
        with self._cv:
            return self._n > 0 or self._heard is not None

    def reset(self) -> None:
        with self._cv:
            self._clear_locked()

    def take(self, final: np.ndarray) -> str | None:
        """Transcript for the utterance that just ended.

        A partial that already landed is used as soon as nothing newer is
        in flight. Otherwise the finished clip is decoded here — that path
        is the short utterance, the one that ended before the first partial.
        """
        if self._recognizer is None:
            return None
        with self._cv:
            # A decode already running has nearly the whole turn. Wait briefly
            # so the breath isn't spent on a clip we meant to finish while
            # they were still talking. Past the grace period, speak anyway.
            self._wait_pending_locked(1.2 if self._heard is None else 0.35)

            if not self._heard and not self._pending_locked():
                audio = np.array(final, dtype=np.float32, copy=True)
                self._frames = [audio]
                self._n = len(audio)
                self._heard_n = 0
                self._job = audio
                self._cv.notify()

            deadline = time.monotonic() + 2.0
            while not self._heard and self._pending_locked() and time.monotonic() < deadline:
                self._cv.wait(timeout=0.05)

            text = self._heard
            self._clear_locked()
            return text

    def _pending_locked(self) -> bool:
        return self._job is not None or (self._busy and self._busy_gen == self._gen)

    def _wait_pending_locked(self, grace: float) -> None:
        if not self._pending_locked():
            return
        deadline = time.monotonic() + grace
        while self._pending_locked() and time.monotonic() < deadline:
            self._cv.wait(timeout=0.05)

    def _schedule_locked(self) -> None:
        if self._busy or self._job is not None:
            return
        if self._n - self._heard_n < self._partial_n or not self._frames:
            return
        self._job = np.concatenate(self._frames)
        self._cv.notify()

    def _clear_locked(self) -> None:
        self._frames = []
        self._n = 0
        self._heard = None
        self._heard_n = 0
        self._job = None
        self._gen += 1
        self._cv.notify_all()

    def _loop(self) -> None:
        assert self._recognizer is not None
        while True:
            with self._cv:
                while self._job is None:
                    self._cv.wait()
                audio = self._job
                gen = self._gen
                end_n = self._n
                self._job = None
                self._busy = True
                self._busy_gen = gen

            try:
                text = _transcribe(self._recognizer, audio)
            except Exception as exc:
                print(f"  (whisper) {exc}", file=sys.stderr)
                text = None

            with self._cv:
                fresh = gen == self._gen
            if text and fresh:
                _prefetch(text)

            with self._cv:
                if gen == self._gen:
                    if text:
                        self._heard = text
                    self._heard_n = end_n
                self._busy = False
                if gen == self._gen:
                    self._schedule_locked()
                self._cv.notify_all()


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
    parser.add_argument("--partial", type=float, default=0.5,
                        help="seconds of new speech between live transcriptions (default: 0.5)")
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
    ear = Transcriber(recognizer, args.partial)

    config = sherpa_onnx.VadModelConfig()
    config.silero_vad.model = str(args.vad_model)
    config.silero_vad.min_silence_duration = args.min_silence
    config.silero_vad.min_speech_duration = args.min_speech
    config.sample_rate = SAMPLE_RATE
    vad = sherpa_onnx.VoiceActivityDetector(config, buffer_size_in_seconds=30)
    window = config.silero_vad.window_size

    if recognizer is not None and not hasattr(vad, "is_speech_detected"):
        sys.exit("This sherpa-onnx build has no VAD.is_speech_detected(); "
                 "upgrade sherpa-onnx to 1.10 or newer.")

    print(f"Ready. Try to say something (I pounce after {args.min_silence}s, "
          f"and I transcribe while you talk). Ctrl-C to stop.\n")

    buffer = np.empty(0, dtype=np.float32)
    samples_per_read = int(0.1 * SAMPLE_RATE)
    shown: str | None = None

    with sd.InputStream(channels=1, dtype="float32", samplerate=SAMPLE_RATE) as stream:
        while True:
            chunk, _ = stream.read(samples_per_read)
            buffer = np.concatenate([buffer, chunk.reshape(-1)])

            while len(buffer) > window:
                frame = buffer[:window]
                buffer = buffer[window:]
                vad.accept_waveform(frame)

                if recognizer is not None and vad.is_speech_detected():
                    ear.extend(frame)
                elif ear.has_audio() and vad.empty():
                    # A blip too short to be a turn. Drop it so the next
                    # sentence is transcribed on its own.
                    ear.reset()
                    shown = None

            live = ear.latest()
            if live and live != shown:
                shown = live
                print(f"  (hearing) {live}", flush=True)

            while not vad.empty():
                utterance = np.array(vad.front.samples, dtype=np.float32)
                vad.pop()

                heard = ear.take(utterance)
                reply = mansplain(heard)
                print(f"  (you paused) -> {reply}", flush=True)
                speaker.say(reply)

                # Drop anything the mic caught while we were talking, so the
                # device doesn't interrupt its own interruption.
                while not vad.empty():
                    vad.pop()
                buffer = np.empty(0, dtype=np.float32)
                ear.reset()
                shown = None


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nFinally, some peace.")
