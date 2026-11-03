"""Portrait postcard. Date, period, ASCII objects, and one caption each.

Text is small monospace on the paper. There is no readout panel. A YOLO box
is drawn only where a segmentation mask kept the foreground.
"""
import io
import json
import random
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from observatory.ascii_art import CHAR_ASPECT, image_to_ascii
from observatory.logio import group_sightings, parse_timestamp, spread_indices
from observatory.poster import find_texture, plan_layout, place_piece
from observatory.segment import mask_is_isolated

POSTCARD_WIDTH = 1470
POSTCARD_HEIGHT = 2108
PRINT_DPI = 300
NO_DETECTIONS = "No detections recorded"
INK = (28, 22, 16)
HALO = (246, 241, 230)
# Header stays a step larger than the notes beside each figure.
LABEL_PT = 6
BODY_PT = 7
CAPTION_PT = 5
TEMPERATURE_STOPS = (
    (15.0, (72, 50, 150)),
    (20.0, (50, 120, 210)),
    (25.0, (40, 170, 190)),
    (30.0, (80, 180, 80)),
    (35.0, (245, 205, 45)),
    (40.0, (220, 45, 35)),
)

# Light stroke, shipped with the lab so the Pi does not fall back to Courier.
MONO_FONTS = (
    Path(__file__).resolve().parent / "fonts" / "IBMPlexMono-Light.ttf",
    "/Library/Fonts/SF-Mono-Light.otf",
    "/usr/share/fonts/opentype/ibm-plex/IBMPlexMono-Light.otf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf",
    "/usr/share/fonts/truetype/freefont/FreeMono.ttf",
)


def _pt(points):
    """Pixel size of a point at the postcard's print resolution."""
    return max(1, int(round(points * PRINT_DPI / 72.0)))


def _font(size):
    for path in MONO_FONTS:
        if Path(path).is_file():
            return ImageFont.truetype(path, size=size)
    return ImageFont.load_default(size=size)


def _fmt_date(value):
    moment = parse_timestamp(value)
    if moment is None:
        return str(value) if value else ""
    return f"{moment.month:02d}/{moment.day:02d}/{moment.year}"


def _fmt_time(value):
    moment = parse_timestamp(value)
    if moment is None:
        return str(value) if value else ""
    hour = str(moment.hour % 12 or 12)
    return f"{hour}:{moment.strftime('%M %p')}"


def _span(meta, samples):
    started = (meta or {}).get("started")
    ended = (meta or {}).get("ended") or started
    if samples:
        started = samples[0].get("timestamp") or started
        ended = samples[-1].get("timestamp") or ended
    return started, ended


def _mask_array(detection):
    mask = detection.get("mask_image")
    if mask is not None:
        return mask
    path = detection.get("mask_path")
    if path and Path(path).is_file():
        return cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    return None


def _crop_array(detection):
    image = detection.get("crop_image")
    if image is not None:
        return image
    path = detection.get("crop_path") or detection.get("crop")
    if path and Path(path).is_file():
        return cv2.imread(str(path), cv2.IMREAD_COLOR)
    return None


def _usable(detection):
    return _crop_array(detection) is not None and mask_is_isolated(_mask_array(detection))


# How many frames of one nearby repeat are drawn on top of each other.
LAYER_CAP = 6
LAYER_TOTAL = 18


def select_sightings(detections, interval_s):
    """One caption per nearby repeat. Proximity is not identity."""
    return [item["anchor"] for item in _layer_groups(detections, interval_s)]


def layered_drawings(detections, interval_s):
    """Several frames from each nearby group, stacked instead of discarded."""
    drawings = []
    for group_index, item in enumerate(_layer_groups(detections, interval_s)):
        members = item["members"]
        indexes = spread_indices(len(members), item["per"])
        best_index = members.index(item["anchor"])
        if best_index not in indexes:
            indexes[-1] = best_index
        indexes = sorted(set(indexes))
        for slot, index in enumerate(indexes):
            drawings.append({
                "detection": members[index],
                "group": group_index,
                "slot": slot,
                "count": len(indexes),
                "caption": members[index] is item["anchor"],
                "anchor": item["anchor"],
            })
    return drawings


def _layer_groups(detections, interval_s):
    grouped = []
    for group in group_sightings(detections, interval_s):
        members = [item for item in group.get("members") or [] if _usable(item)]
        if members:
            grouped.append(members)
    if not grouped:
        return []
    per = LAYER_CAP
    while per > 1 and len(grouped) * per > LAYER_TOTAL:
        per -= 1
    layers = []
    for members in grouped:
        best = max(members, key=lambda item: float(item.get("confidence") or 0))
        layers.append({"members": members, "anchor": best, "per": per})
    return layers


def _shift_ink(color, slot):
    if slot == 0:
        return color
    red, green, blue = color
    turn = slot % 3
    if turn == 1:
        return ((red + 72) % 256, green, (blue + 36) % 256)
    if turn == 2:
        return (red, (green + 80) % 256, (blue + 28) % 256)
    return ((red + 36) % 256, (green + 36) % 256, blue)


def _caption_text(detection, notes):
    for note in notes:
        if not isinstance(note, dict):
            continue
        if note.get("timestamp") != detection.get("timestamp"):
            continue
        if note.get("class_name") != detection.get("class_name"):
            continue
        text = " ".join(str(note.get("text") or "").split())
        if not text:
            continue
        if text.lower().startswith("qwen imagines"):
            return text
        return f"Qwen imagines: {text}"
    return " ".join(str(detection.get("class_name") or "").split())


def postcard_content(meta, detections, samples, speculations, note_status="skipped"):
    """The words actually drawn: header, captions, and the empty-night line."""
    meta = meta or {}
    notes = [note for note in (speculations or []) if isinstance(note, dict)]
    started, ended = _span(meta, samples)
    date = _fmt_date(meta.get("started") or started)
    if ended:
        period = f"{_fmt_time(started)} – {_fmt_time(ended)}"
    else:
        period = _fmt_time(started)
    sightings = select_sightings(detections, meta.get("interval_s"))
    captions = [
        {"time": _fmt_time(item.get("timestamp")), "description": _caption_text(item, notes)}
        for item in sightings
    ]
    message = "" if captions else NO_DETECTIONS
    return {"date": date, "period": period, "captions": captions, "message": message, "note_status": note_status}


def _cover_texture(texture_bytes, width, height):
    texture = Image.open(io.BytesIO(texture_bytes)).convert("RGB")
    scale = max(width / texture.width, height / texture.height)
    resized = texture.resize(
        (max(width, int(texture.width * scale) + 1), max(height, int(texture.height * scale) + 1)),
        Image.Resampling.LANCZOS,
    )
    left = max(0, (resized.width - width) // 2)
    top = max(0, (resized.height - height) // 2)
    return resized.crop((left, top, left + width, top + height))


def paper_background(width, height, seed, texture_bytes=None):
    """Subtle paper. The supplied texture is washed back; otherwise a seeded fiber field."""
    if texture_bytes:
        cover = _cover_texture(texture_bytes, width, height)
        wash = Image.new("RGB", (width, height), (250, 246, 236))
        return Image.blend(cover, wash, 0.62)
    rng = np.random.default_rng(int(seed) % (2**32))
    field = rng.integers(236, 248, (height, width), dtype=np.uint8)
    count = 1800
    ys = rng.integers(0, height, count)
    xs = rng.integers(0, width, count)
    field[ys, xs] = rng.integers(196, 220, count).astype(np.uint8)
    return Image.fromarray(field, mode="L").convert("RGB")


def _parse_rgb(text):
    parts = [
        int(piece)
        for piece in str(text).replace("rgb", "").replace("(", "").replace(")", "").split(",")
        if piece.strip()
    ]
    if len(parts) != 3:
        return INK
    return tuple(max(0, min(255, value)) for value in parts)


def _wrap(text, font, width):
    text = " ".join(str(text).split())
    if not text:
        return []
    lines = []
    current = ""
    for word in text.split(" "):
        trial = word if not current else current + " " + word
        if font.getlength(trial) <= width:
            current = trial
            continue
        if current:
            lines.append(current)
        if font.getlength(word) <= width:
            current = word
            continue
        chunk = ""
        for character in word:
            if font.getlength(chunk + character) <= width:
                chunk += character
            else:
                if chunk:
                    lines.append(chunk)
                chunk = character
        current = chunk
    if current:
        lines.append(current)
    return lines


def _trim_ascii(art):
    lines = art.splitlines()
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    if not lines or not any(line.strip() for line in lines):
        return ""
    left = min(len(line) - len(line.lstrip(" ")) for line in lines)
    right = min(len(line) - len(line.rstrip(" ")) for line in lines)
    if right:
        lines = [line[left:len(line) - right] for line in lines]
    else:
        lines = [line[left:] for line in lines]
    return "\n".join(lines)


def _ascii_block(detection, cols):
    image = _crop_array(detection)
    mask = _mask_array(detection)
    if image is None or not mask_is_isolated(mask):
        return ""
    return _trim_ascii(image_to_ascii(image, cols=cols, char_aspect=CHAR_ASPECT, mask=mask))


def _draw_text(draw, x, y, text, font):
    for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
        draw.text((x + dx, y + dy), text, font=font, fill=HALO)
    draw.text((x, y), text, font=font, fill=INK)


def _temperature_color(value):
    value = max(TEMPERATURE_STOPS[0][0], min(TEMPERATURE_STOPS[-1][0], float(value)))
    for (low_temp, low_color), (high_temp, high_color) in zip(TEMPERATURE_STOPS, TEMPERATURE_STOPS[1:]):
        if value <= high_temp:
            fraction = (value - low_temp) / (high_temp - low_temp)
            return tuple(round(low + fraction * (high - low)) for low, high in zip(low_color, high_color))
    return TEMPERATURE_STOPS[-1][1]


def _temperature_readings(samples):
    readings = []
    for sample in samples or []:
        try:
            temperature = float(sample["temperature_c"])
            humidity = max(0.0, min(100.0, float(sample["humidity_percent"])))
        except (KeyError, TypeError, ValueError):
            continue
        readings.append({
            "timestamp": parse_timestamp(sample.get("timestamp")),
            "temperature": temperature,
            "humidity": humidity,
        })
    return readings


def _temperature_band_height(humidity, page_height):
    return max(1, round(page_height * (0.02 + 0.18 * humidity / 100.0)))


def _stamp_segment(image, bounds, color, height, rng):
    left, top, right, bottom = bounds
    width = max(1, right - left)
    fringe = max(2, round(height * 0.16))
    local_height = max(1, bottom - top)
    mask = Image.new("L", (width + 1, local_height + fringe * 2 + 1), 0)
    mask_draw = ImageDraw.Draw(mask)
    steps = max(5, min(36, width // 10))
    top_edge = []
    bottom_edge = []
    for index in range(steps + 1):
        local_x = round(width * index / steps)
        edge_jitter = max(3, round(height * 0.32))
        top_edge.append((local_x, fringe + rng.randint(-edge_jitter, edge_jitter)))
        bottom_edge.append((local_x, fringe + local_height + rng.randint(-edge_jitter, edge_jitter)))
    mask_draw.line(top_edge, fill=70, width=max(2, round(height * 0.10)))
    mask_draw.line(bottom_edge, fill=70, width=max(2, round(height * 0.10)))
    mask_draw.polygon(top_edge + list(reversed(bottom_edge)), fill=220)
    # Larger voids and streaks create the broken transfer of a physical stamp.
    for _ in range(max(10, width // 20)):
        hole_w = rng.randint(2, max(3, width // 12))
        hole_h = rng.randint(1, max(2, round(height * 0.16)))
        x = rng.randint(0, max(0, width - hole_w))
        y = rng.randint(0, max(0, local_height + fringe * 2 - hole_h))
        mask_draw.ellipse((x, y, x + hole_w, y + hole_h), fill=rng.randint(15, 70))
    for _ in range(max(5, width // 55)):
        x = rng.randint(0, width)
        y = rng.choice((
            rng.randint(0, max(0, fringe)),
            rng.randint(fringe + local_height, mask.height - 1),
        ))
        mask_draw.ellipse((x, y, x + rng.randint(1, 5), y + rng.randint(1, 3)), fill=rng.randint(15, 55))
    # Vary alpha within each segment, not between segments, like uneven ink.
    mask_array = np.asarray(mask, dtype=np.float32)
    texture = np.random.default_rng(rng.randrange(2**32)).normal(0.86, 0.38, mask_array.shape)
    alpha = np.clip(mask_array * texture * 0.72, 0, 190).astype(np.uint8)
    pigment = Image.new("RGB", mask.size, color)
    image.paste(pigment, (left, top - fringe), Image.fromarray(alpha, mode="L"))


def _draw_temperature_band(image, samples, left, right, band_center, page_height, seed):
    readings = _temperature_readings(samples)
    if not readings:
        return 0
    times = [reading["timestamp"] for reading in readings]
    if all(moment is not None for moment in times):
        durations = [
            max(0.0, (times[index + 1] - times[index]).total_seconds())
            for index in range(len(times) - 1)
        ]
        durations.append(durations[-1] if durations and durations[-1] > 0 else 1.0)
    else:
        durations = [1.0] * len(readings)
    total = sum(durations) or len(readings)
    x = left
    max_height = 0
    rng = random.Random(seed)
    stamp_rng = random.Random(seed + 1)
    for index, (reading, duration) in enumerate(zip(readings, durations)):
        next_x = right if index == len(readings) - 1 else left + round((right - left) * duration / total + (x - left))
        next_x = max(x + 1, min(right, next_x))
        band_height = _temperature_band_height(reading["humidity"], page_height)
        max_height = max(max_height, band_height)
        center = band_center + rng.randint(-1, 1)
        _stamp_segment(
            image,
            (x, center - band_height // 2, next_x, center + (band_height + 1) // 2),
            _temperature_color(reading["temperature"]),
            band_height,
            stamp_rng,
        )
        x = next_x
    return max_height


def _overlaps(a, b, pad=10):
    return not (a[2] + pad <= b[0] or b[2] + pad <= a[0] or a[3] + pad <= b[1] or b[3] + pad <= a[1])


def _place_caption(left, top, block_w, block_h, cap_w, cap_h, stage_w, stage_h, occupied):
    """Put the caption on open paper, beside its figure when that spot is free."""
    gap = 40
    candidates = [
        (left + block_w + gap, top),
        (left - cap_w - gap, top),
        (left, top + block_h + gap),
        (left, top - cap_h - gap),
        (left + block_w + gap, top + block_h + gap),
        (left - cap_w - gap, top + block_h + gap),
    ]
    step_x = max(24, int(cap_w * 0.35))
    step_y = max(24, int(cap_h * 0.5))
    limit_x = max(9, int(stage_w - cap_w - 8))
    limit_y = max(9, int(stage_h - cap_h - 8))
    for y in range(8, limit_y, step_y):
        for x in range(8, limit_x, step_x):
            candidates.append((x, y))
    anchor_x = left + block_w + gap
    anchor_y = top
    candidates.sort(key=lambda point: (point[0] - anchor_x) ** 2 + (point[1] - anchor_y) ** 2)
    for x, y in candidates:
        if x < 8 or y < 8 or x + cap_w > stage_w - 8 or y + cap_h > stage_h - 8:
            continue
        rect = (x, y, x + cap_w, y + cap_h)
        if any(_overlaps(rect, other, pad=12) for other in occupied):
            continue
        return int(x), int(y)
    return int(min(max(8, left), max(8, stage_w - cap_w - 8))), int(min(max(8, top + block_h + gap), max(8, stage_h - cap_h - 8)))


def render_postcard_image(meta, detections, samples, speculations, seed,
                          texture_bytes=None, note_status="skipped"):
    content = postcard_content(meta, detections, samples, speculations, note_status)
    width, height = POSTCARD_WIDTH, POSTCARD_HEIGHT
    image = paper_background(width, height, seed, texture_bytes)
    draw = ImageDraw.Draw(image)
    label = _font(_pt(LABEL_PT))
    value = _font(_pt(BODY_PT))
    margin = 78
    readings = _temperature_readings(samples)
    band_height = max(
        (_temperature_band_height(reading["humidity"], height) for reading in readings),
        default=0,
    )
    band_top = 34
    band_center = band_top + band_height // 2
    if band_height:
        _draw_temperature_band(image, samples, margin, width - margin, band_center, height, seed)
    draw = ImageDraw.Draw(image)
    y = 68
    _draw_text(draw, margin, y, "DATE", label)
    y += _pt(LABEL_PT) + 4
    _draw_text(draw, margin, y, content["date"], value)
    y += _pt(BODY_PT) + 14
    _draw_text(draw, margin, y, "OBSERVATION PERIOD", label)
    y += _pt(LABEL_PT) + 4
    _draw_text(draw, margin, y, content["period"], value)
    y += _pt(BODY_PT) + 22
    art_top = y
    art_box = (margin, art_top, width - margin, height - 64)
    art_w = art_box[2] - art_box[0]
    art_h = art_box[3] - art_box[1]
    art = Image.new("RGBA", (max(art_w, 1), max(art_h, 1)), (0, 0, 0, 0))
    art_draw = ImageDraw.Draw(art)
    drawings = layered_drawings(detections, (meta or {}).get("interval_s"))
    anchors = []
    seen_groups = set()
    for item in drawings:
        if item["group"] in seen_groups:
            continue
        seen_groups.add(item["group"])
        anchors.append(item["anchor"])
    layout = plan_layout(anchors, seed)
    plans = {index: plan for index, plan in enumerate(layout)}
    pieces = []
    for item in drawings:
        detection = item["detection"]
        plan = plans[item["group"]]
        scaled = dict(plan)
        scale = 0.78 + 0.08 * item["slot"]
        scaled["font_px"] = max(16, int(plan["font_px"] * 2.4 * scale))
        art_text = _ascii_block(detection, scaled["cols"])
        if not art_text:
            continue
        scaled["cols"] = max(len(line) for line in art_text.splitlines())
        font_px, left, top = place_piece(scaled, art_text, stage_w=art_w, stage_h=art_h)
        nudge = item["slot"] - (item["count"] - 1) / 2.0
        left = int(left + nudge * 46)
        top = int(top + nudge * 28)
        left = max(0, min(left, max(0, art_w - 48)))
        top = max(0, min(top, max(0, art_h - 48)))
        pieces.append({
            "detection": detection,
            "plan": plan,
            "art": art_text,
            "font": _font(font_px),
            "font_px": font_px,
            "left": left,
            "top": top,
            "color": _shift_ink(_parse_rgb(plan["color"]), item["slot"]),
            "slot": item["slot"],
            "caption": item["caption"],
        })
    for piece in sorted(pieces, key=lambda item: (item["slot"], item["plan"]["z"])):
        lines = piece["art"].splitlines()
        advance = piece["font"].getlength("0") or piece["font_px"] * CHAR_ASPECT
        step = max(1, int(round(advance / CHAR_ASPECT)))
        piece["step"] = step
        width_px = max((piece["font"].getlength(line) for line in lines), default=advance)
        block = Image.new("RGBA", (max(2, int(width_px) + 2), max(2, len(lines) * step + 2)), (0, 0, 0, 0))
        block_draw = ImageDraw.Draw(block)
        for index, line in enumerate(lines):
            block_draw.text((0, index * step), line, font=piece["font"], fill=piece["color"] + (255,))
        angle = piece["plan"]["rotate"]
        if abs(angle) > 0.2:
            block = block.rotate(angle, resample=Image.Resampling.BICUBIC, expand=True)
        art.paste(block, (int(piece["left"]), int(piece["top"])), block)
    caption_font = _font(_pt(CAPTION_PT))
    notes = [note for note in (speculations or []) if isinstance(note, dict)]
    occupied = []
    for piece in pieces:
        lines = piece["art"].splitlines()
        step = piece["step"]
        block_w = max(piece["font"].getlength(line) for line in lines)
        block_h = max(step, len(lines) * step)
        pad = 16
        piece["block"] = (
            piece["left"] - pad, piece["top"] - pad,
            piece["left"] + block_w + pad, piece["top"] + block_h + pad,
        )
        occupied.append(piece["block"])
    for piece in pieces:
        if not piece["caption"]:
            continue
        lines = piece["art"].splitlines()
        step = piece["step"]
        block_w = max(piece["font"].getlength(line) for line in lines)
        block_h = max(step, len(lines) * step)
        description = _caption_text(piece["detection"], notes)
        caption_lines = [_fmt_time(piece["detection"].get("timestamp"))] + _wrap(description, caption_font, 200)
        cap_w = min(220, max(caption_font.getlength(line) for line in caption_lines) + 4)
        cap_h = int(len(caption_lines) * (_pt(CAPTION_PT) + 3))
        x, y_text = _place_caption(
            piece["left"], piece["top"], block_w, block_h, cap_w, cap_h, art_w, art_h, occupied,
        )
        cursor = y_text
        for line in caption_lines:
            _draw_text(art_draw, x, cursor, line, caption_font)
            cursor += _pt(CAPTION_PT) + 3
        occupied.append((x, y_text, x + cap_w, y_text + cap_h))
    if content["message"]:
        _draw_text(art_draw, 8, 12, content["message"], caption_font)
    image.paste(art, (art_box[0], art_box[1]), art)
    return image.convert("RGB")


def write_postcard(path, meta, detections, samples, speculations, seed,
                   texture_bytes=None, note_status="skipped"):
    image = render_postcard_image(
        meta, detections, samples, speculations, seed,
        texture_bytes=texture_bytes, note_status=note_status,
    )
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".partial")
    image.save(temporary, format="PNG")
    temporary.replace(path)
    return path


def write_record_log(path, meta, detections, samples, speculations):
    """Save the data used to render the postcard in a readable text file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".partial")
    record = {
        "meta": meta,
        "samples": samples,
        "detections": detections,
        "speculations": speculations,
    }
    temporary.write_text(json.dumps(record, indent=2, default=str) + "\n", encoding="utf-8")
    temporary.replace(path)
    return path


def retain_only(folder, keep):
    """Drop every file in the session folder except the finished outputs."""
    folder = Path(folder)
    if isinstance(keep, (str, Path)):
        keep = [keep]
    keep = {Path(path).resolve() for path in keep}
    for path in sorted(folder.rglob("*"), reverse=True):
        if path.resolve() in keep:
            continue
        if path.is_file() or path.is_symlink():
            path.unlink()
        elif path.is_dir():
            try:
                path.rmdir()
            except OSError:
                pass


def load_texture_bytes(explicit=None):
    found = find_texture(explicit)
    if found is None:
        looked = explicit or "poetic surveillance/paper texture .jpg"
        print(f"Paper texture unavailable ({looked}). Postcard uses a generated paper background.", flush=True)
        return None, looked
    print(f"Paper texture: {found}", flush=True)
    return found.read_bytes(), str(found)
