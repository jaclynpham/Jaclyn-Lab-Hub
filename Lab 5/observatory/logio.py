"""Session files for one night at the window.

detections.jsonl keeps every box. Sightings are computed later for the poster
and are only nearby repeats of a class, not a tracked individual.
"""
import datetime
import json
import math
from pathlib import Path

# Same class, centers this close on the normalized frame, and no further apart
# than SIGHTING_MAX_GAPS sample intervals. Proximity is not identity.
SIGHTING_MAX_DIST = 0.18
SIGHTING_MAX_GAPS = 3


def write_json(path, data):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def read_jsonl(path):
    path = Path(path)
    if not path.is_file():
        return []
    rows = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise SystemExit(f"{path}:{line_no}: invalid JSON ({exc})") from exc
    return rows


def load_session(path):
    session_dir = Path(path)
    meta_path = session_dir / "session.json"
    if not meta_path.is_file():
        raise SystemExit(f"No session.json in {session_dir}")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    detections = read_jsonl(session_dir / "detections.jsonl")
    samples = read_jsonl(session_dir / "samples.jsonl")
    return session_dir, meta, detections, samples


def position_words(cx, cy):
    """Thirds of the frame, the same horizontal split as interpret() in Part E."""
    horizontal = "left" if cx < 1 / 3 else "right" if cx > 2 / 3 else "center"
    vertical = "upper" if cy < 1 / 3 else "lower" if cy > 2 / 3 else "middle"
    return horizontal, vertical


def make_detection(found, frame_shape, crop, timestamp):
    """One saved box. `found` has class_name, class_id, confidence, and xyxy."""
    height, width = frame_shape[:2]
    x1, y1, x2, y2 = [float(value) for value in found["xyxy"]]
    cx = ((x1 + x2) / 2) / width if width else 0.0
    cy = ((y1 + y2) / 2) / height if height else 0.0
    horizontal, vertical = position_words(cx, cy)
    return {
        "timestamp": timestamp,
        "class_name": str(found["class_name"]),
        "class_id": int(found["class_id"]),
        "confidence": round(float(found["confidence"]), 4),
        "bbox": [round(x1, 1), round(y1, 1), round(x2, 1), round(y2, 1)],
        "position": {
            "cx": round(cx, 4),
            "cy": round(cy, 4),
            "horizontal": horizontal,
            "vertical": vertical,
        },
        "crop": crop,
        "frame_width": int(width),
        "frame_height": int(height),
    }


def parse_timestamp(value):
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.datetime.fromisoformat(value)
    except ValueError:
        return None


def spread_indices(count, cap):
    """Evenly spaced indexes. Stable, so a rerender does not drop a different subset."""
    if cap <= 0 or count <= 0:
        return []
    if count <= cap:
        return list(range(count))
    if cap == 1:
        return [0]
    chosen = []
    for step in range(cap):
        index = round(step * (count - 1) / (cap - 1))
        if index not in chosen:
            chosen.append(index)
    return chosen


def group_sightings(detections, interval_s, max_dist=SIGHTING_MAX_DIST, max_gaps=SIGHTING_MAX_GAPS):
    """Group repeated nearby same-class boxes into approximate sightings.

    A detection joins an existing group of the same class when the Euclidean
    distance between normalized centers is at most `max_dist` and the time since
    that group's latest detection is at most `max_gaps` sample intervals.
    Unknown interval means no grouping across time. This does not track identity.
    """
    gap = None if interval_s is None else max(0.0, float(interval_s)) * max_gaps
    groups = []
    for detection in sorted(detections, key=lambda item: item.get("timestamp") or ""):
        position = detection.get("position") or {}
        cx = position.get("cx")
        cy = position.get("cy")
        moment = parse_timestamp(detection.get("timestamp"))
        best = None
        best_dist = None
        if cx is not None and cy is not None and moment is not None and gap is not None:
            for group in groups:
                if group["class_name"] != detection.get("class_name"):
                    continue
                if group["last"] is None:
                    continue
                elapsed = (moment - group["last"]).total_seconds()
                if elapsed < 0 or elapsed > gap:
                    continue
                dist = math.hypot(float(cx) - group["cx"], float(cy) - group["cy"])
                if dist <= max_dist and (best_dist is None or dist < best_dist):
                    best = group
                    best_dist = dist
        if best is None:
            groups.append({
                "class_name": detection.get("class_name") or "unknown",
                "cx": float(cx) if cx is not None else 0.5,
                "cy": float(cy) if cy is not None else 0.5,
                "n": 1,
                "last": moment,
                "members": [detection],
            })
            continue
        count = best["n"]
        best["cx"] = (best["cx"] * count + float(cx)) / (count + 1)
        best["cy"] = (best["cy"] * count + float(cy)) / (count + 1)
        best["n"] = count + 1
        best["last"] = moment
        best["members"].append(detection)
    return groups
