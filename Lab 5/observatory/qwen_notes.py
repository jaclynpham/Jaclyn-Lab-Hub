"""Speculative poster notes from local Qwen. The ASCII is not made here.

Same Ollama request as ask_qwen.py: localhost, thinking off, a short cap,
and an optional base64 image for qwen3.5:0.8b. Nothing is sent off the machine.
"""
import base64
import json
from pathlib import Path

import requests

from observatory.logio import spread_indices

OLLAMA_URL = "http://localhost:11434/api/generate"
DEFAULT_MODEL = "qwen3.5:0.8b"

SYSTEM = (
    "You are a small bedside device writing one speculative sentence for a morning postcard. "
    "The sentence is imaginative, not a report of fact. "
    "Do not identify a person. Do not guess relationships, intent, clothing, age, or other attributes. "
    "Do not describe the picture as a confirmed observation. "
    "Write one short sentence, with no label and no list."
)


def prompt_for(detection):
    position = detection.get("position") or {}
    vertical = position.get("vertical") or "unknown"
    horizontal = position.get("horizontal") or "unknown"
    try:
        confidence = f"{float(detection.get('confidence')):.2f}"
    except (TypeError, ValueError):
        confidence = "unknown"
    return (
        f"Detector metadata, which may be wrong: class {detection.get('class_name')}, "
        f"time {detection.get('timestamp')}, confidence {confidence}, "
        f"approximate position {vertical} {horizontal}. "
        "Write a speculative note about a night outside a window. "
        "It must be obvious imagination. Do not state identity, relationships, intent, or clothing."
    )


def build_request(model, prompt, image_bytes=None, max_tokens=80):
    """The ask_qwen.py body: think is false, stream is false, answers stay short."""
    request = {
        "model": model,
        "system": SYSTEM,
        "prompt": prompt,
        "think": False,
        "stream": False,
        "keep_alive": "5m",
        "options": {"temperature": 0.3, "num_predict": max_tokens},
    }
    if image_bytes is not None:
        request["images"] = [base64.b64encode(image_bytes).decode("ascii")]
    return request


def speculate(session_dir, detection, model=DEFAULT_MODEL, post=None, timeout=600):
    crop = detection.get("crop")
    image_bytes = None
    if crop:
        path = Path(session_dir) / crop
        if path.is_file():
            image_bytes = path.read_bytes()
    request = build_request(model, prompt_for(detection), image_bytes=image_bytes)
    post = post or requests.post
    response = post(OLLAMA_URL, json=request, timeout=timeout)
    response.raise_for_status()
    reply = response.json()
    text = str(reply.get("response") or "").strip()
    return text


def crops_for_notes(session_dir, detections, cap):
    available = []
    for detection in detections:
        crop = detection.get("crop")
        if crop and (Path(session_dir) / crop).is_file():
            available.append(detection)
    return [available[index] for index in spread_indices(len(available), cap)]


def load_saved_notes(path):
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    if not isinstance(data, list):
        return None
    return data


def collect_notes(detections, skip, cap, model=DEFAULT_MODEL, post=None, timeout=600):
    """Ask local Qwen about a few crops. Nothing is written to the session folder."""
    if skip:
        return [], "skipped"
    available = [
        detection for detection in detections
        if detection.get("crop_path") and Path(detection["crop_path"]).is_file()
    ]
    chosen = [available[index] for index in spread_indices(len(available), max(0, int(cap)))]
    if not chosen:
        return [], "no-crops"
    notes = []
    post_fn = post or requests.post
    try:
        for detection in chosen:
            image_bytes = Path(detection["crop_path"]).read_bytes()
            request = build_request(model, prompt_for(detection), image_bytes=image_bytes)
            response = post_fn(OLLAMA_URL, json=request, timeout=timeout)
            response.raise_for_status()
            text = str(response.json().get("response") or "").strip()
            if not text:
                continue
            notes.append({
                "timestamp": detection.get("timestamp"),
                "class_name": detection.get("class_name"),
                "text": text,
                "model": model,
            })
    except requests.RequestException as exc:
        print(f"Ollama request failed: {exc}", flush=True)
        if notes:
            return notes, "partial"
        return [], "failed"
    return notes, "fresh"


def prepare_speculations(session_dir, detections, skip, cap, model=DEFAULT_MODEL, post=None):
    """Return (notes, status). Status is saved, skipped, no-crops, fresh, partial, or failed.

    `--skip-qwen` never calls Ollama. Saved notes from an earlier render are reused
    because they are already part of the session, and they stay labeled as imagination.
    """
    session_dir = Path(session_dir)
    path = session_dir / "speculations.json"
    saved = load_saved_notes(path)
    if skip:
        if saved:
            return saved, "saved"
        return [], "skipped"
    chosen = crops_for_notes(session_dir, detections, cap)
    if not chosen:
        return [], "no-crops"
    notes = []
    try:
        for detection in chosen:
            text = speculate(session_dir, detection, model=model, post=post)
            if not text:
                continue
            notes.append({
                "timestamp": detection.get("timestamp"),
                "class_name": detection.get("class_name"),
                "crop": detection.get("crop"),
                "text": text,
                "model": model,
            })
    except requests.RequestException as exc:
        print(f"Ollama request failed: {exc}", flush=True)
        if notes:
            path.write_text(json.dumps(notes, indent=2) + "\n", encoding="utf-8")
            return notes, "partial"
        if saved:
            return saved, "failed-kept-saved"
        return [], "failed"
    path.write_text(json.dumps(notes, indent=2) + "\n", encoding="utf-8")
    return notes, "fresh"
