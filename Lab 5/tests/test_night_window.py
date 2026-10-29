"""Tests for the Night Window Observatory. Standard-library unittest only."""
import io
import json
import re
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

import sys
LAB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LAB))

from PIL import Image
from night_window import build_parser, main
from observatory.ascii_art import CHAR_ASPECT, DENSITY_RAMP, image_to_ascii
from observatory.coco import class_names_from_args, resolve_class_ids
from observatory.gesture import is_quiet_coyote
from observatory.logio import (
    group_sightings,
    load_session,
    make_detection,
    read_jsonl,
    write_json,
)
from observatory.observe import build_predictor, padded_crop, run_observe
from observatory.segment import (
    SEG_CANDIDATES,
    grabcut_mask,
    instances_from_result,
    mask_is_isolated,
    resolve_seg_path,
)
from observatory.postcard import (
    NO_DETECTIONS,
    POSTCARD_HEIGHT,
    POSTCARD_WIDTH,
    postcard_content,
    render_postcard_image,
    write_postcard,
)
from observatory.poster import find_texture, format_rgb, plan_layout, seed_from_session
from observatory.qwen_notes import (
    OLLAMA_URL,
    SYSTEM,
    build_request,
    collect_notes,
    prepare_speculations,
    prompt_for,
)


def _args(tmp, extra=None):
    argv = ["observe", "--output", str(tmp)]
    if extra:
        argv.extend(extra)
    return build_parser().parse_args(argv)


class FakeCamera:
    def __init__(self):
        self.released = False
        self.reads = 0

    def read(self):
        self.reads += 1
        frame = np.zeros((480, 640, 3), np.uint8)
        frame[80:260, 100:220] = (30, 40, 200)
        return True, frame

    def release(self):
        self.released = True


class FakePredictor:
    def __init__(self, boxes=None):
        self.calls = 0
        self.boxes = [] if boxes is None else boxes

    def __call__(self, frame):
        self.calls += 1
        return list(self.boxes)


class Clock:
    def __init__(self):
        self.t = 1000.0

    def time(self):
        return self.t

    def sleep(self, seconds):
        self.t += float(seconds)


BIRD = {
    "class_id": 14,
    "class_name": "bird",
    "confidence": 0.82,
    "xyxy": [100, 80, 220, 260],
}


class AsciiTests(unittest.TestCase):
    def test_ramp_endpoints_aspect_and_color_image(self):
        self.assertEqual(DENSITY_RAMP[0], " ")
        self.assertEqual(DENSITY_RAMP[-1], "$")
        self.assertIn("<", DENSITY_RAMP)
        white = np.full((40, 80), 255, np.uint8)
        black = np.full((40, 80), 0, np.uint8)
        white_art = image_to_ascii(white, cols=80, char_aspect=1)
        black_art = image_to_ascii(black, cols=80, char_aspect=1)
        self.assertEqual(white_art.splitlines(), [" " * 80] * 40)
        self.assertEqual(black_art.splitlines(), [DENSITY_RAMP[-1] * 80] * 40)

        split = np.full((40, 80), 255, np.uint8)
        split[:, :40] = 0
        art = image_to_ascii(split, cols=80, char_aspect=1)
        self.assertEqual(len(art.splitlines()), 40)
        self.assertTrue(all(line[:40] == DENSITY_RAMP[-1] * 40 for line in art.splitlines()))
        self.assertTrue(all(line[40:] == " " * 40 for line in art.splitlines()))

        bgr = np.full((20, 20, 3), 255, np.uint8)
        bgr_art = image_to_ascii(bgr, cols=10, char_aspect=0.5)
        self.assertEqual(len(bgr_art.splitlines()), 5)
        self.assertTrue(all(set(line) == {" "} for line in bgr_art.splitlines()))
        self.assertEqual(image_to_ascii(np.zeros((0, 10), np.uint8)), "")

        square = np.full((100, 100, 3), 128, np.uint8)
        squared = image_to_ascii(square, cols=40, char_aspect=CHAR_ASPECT)
        self.assertEqual(len(squared.splitlines()), max(1, int(round(40 * CHAR_ASPECT))))
        self.assertTrue(all(len(line) == 40 for line in squared.splitlines()))

        masked = np.zeros((40, 80), np.uint8)
        mask = np.zeros((40, 80), np.uint8)
        mask[:, 20:60] = 255
        masked_art = image_to_ascii(masked, cols=80, char_aspect=1, mask=mask)
        self.assertTrue(all(line[:20] == " " * 20 and line[60:] == " " * 20 for line in masked_art.splitlines()))
        self.assertTrue(all(set(line[20:60]) == {DENSITY_RAMP[-1]} for line in masked_art.splitlines()))

    def test_sample_images_keep_aspect(self):
        for name in ("bus.jpg", "snap.jpg", "predict/bus.jpg"):
            path = LAB / name
            image = cv2.imread(str(path))
            self.assertIsNotNone(image, name)
            cols = 48
            art = image_to_ascii(image, cols=cols)
            height, width = image.shape[:2]
            expected_rows = max(1, int(round(cols * (height / float(width)) * CHAR_ASPECT)))
            lines = art.splitlines()
            self.assertEqual(len(lines), expected_rows, name)
            self.assertTrue(all(len(line) == cols for line in lines), name)
            self.assertTrue(set(art) <= set(DENSITY_RAMP + "\n"))
            if width > height:
                self.assertLess(len(lines), cols, name)


class FormatTests(unittest.TestCase):
    def test_rgb_format(self):
        self.assertEqual(format_rgb(0, 0, 0), "rgb(0, 0, 0)")
        self.assertEqual(format_rgb(255, 128, 3), "rgb(255, 128, 3)")
        for value in (format_rgb(0, 10, 255),):
            self.assertRegex(value, r"rgb\((\d{1,3}), (\d{1,3}), (\d{1,3})\)")
            channels = [int(part) for part in re.findall(r"\d+", value)]
            self.assertTrue(all(0 <= channel <= 255 for channel in channels))
        with self.assertRaises(ValueError):
            format_rgb(256, 0, 0)
        with self.assertRaises(ValueError):
            format_rgb(0, -1, 0)

    def test_layout_is_deterministic_for_a_seed(self):
        detections = [
            {"bbox": [0, 0, 100, 80], "frame_width": 640, "frame_height": 480},
            {"bbox": [10, 10, 400, 300], "frame_width": 640, "frame_height": 480},
        ]
        first = plan_layout(detections, 123)
        second = plan_layout(detections, 123)
        other = plan_layout(detections, 999)
        self.assertEqual(first, second)
        self.assertNotEqual(first, other)
        self.assertNotEqual(first[0]["color"], other[0]["color"])
        for item in first:
            self.assertRegex(item["color"], r"rgb\(\d{1,3}, \d{1,3}, \d{1,3}\)")
            channels = [int(part) for part in re.findall(r"\d+", item["color"])]
            self.assertTrue(all(0 <= channel <= 255 for channel in channels))
            self.assertGreaterEqual(item["font_px"], 8)
            self.assertLessEqual(item["cols"], 76)


class LogTests(unittest.TestCase):
    def test_roundtrip_and_missing_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            session = Path(tmp)
            found = make_detection(BIRD, (480, 640, 3), "crops/bird.jpg", "2026-10-28T23:05:00")
            self.assertEqual(found["timestamp"], "2026-10-28T23:05:00")
            self.assertEqual(found["class_name"], "bird")
            self.assertEqual(found["confidence"], 0.82)
            self.assertEqual(found["bbox"], [100.0, 80.0, 220.0, 260.0])
            self.assertEqual(found["position"]["horizontal"], "left")
            self.assertEqual(found["position"]["vertical"], "middle")
            self.assertAlmostEqual(found["position"]["cx"], 0.25)
            self.assertEqual(found["crop"], "crops/bird.jpg")
            write_json(session / "session.json", {"started": "2026-10-28T23:05:00", "interval_s": 10})
            (session / "detections.jsonl").write_text(json.dumps(found) + "\n\n", encoding="utf-8")
            (session / "samples.jsonl").write_text(
                json.dumps({"timestamp": "2026-10-28T23:05:00", "detections": 1, "frame_ok": True}) + "\n",
                encoding="utf-8",
            )
            loaded_dir, meta, detections, samples = load_session(session)
            self.assertEqual(loaded_dir, session)
            self.assertEqual(detections, [found])
            self.assertEqual(len(samples), 1)
            self.assertEqual(meta["interval_s"], 10)
            self.assertEqual(read_jsonl(session / "missing.jsonl"), [])
            with self.assertRaises(SystemExit):
                load_session(session / "nope")

    def test_sightings_are_proximity_not_identity(self):
        near = [
            _det("bird", "2026-10-28T01:00:00", 0.40, 0.40),
            _det("bird", "2026-10-28T01:00:10", 0.42, 0.41),
        ]
        far = [
            _det("bird", "2026-10-28T01:00:00", 0.05, 0.10),
            _det("bird", "2026-10-28T01:00:10", 0.90, 0.80),
        ]
        self.assertEqual(len(group_sightings(near, 10)), 1)
        self.assertEqual(len(group_sightings(near, 10)[0]["members"]), 2)
        self.assertEqual(len(group_sightings(far, 10)), 2)
        self.assertEqual(len(near), 2)


def _fixture_meta():
    return {
        "started": "2026-10-28T23:05:00",
        "ended": "2026-10-29T06:10:00",
        "stopped": "duration",
        "interval_s": 10,
        "camera": 0,
        "model": "yolo26n_ncnn_model",
        "conf": 0.4,
        "classes": ["bus"],
        "all_classes": False,
        "id": "fixture",
    }


def _ellipse_mask(shape):
    mask = np.zeros(shape[:2], np.uint8)
    height, width = shape[:2]
    cv2.ellipse(
        mask, (width // 2, height // 2), (max(4, int(width * 0.28)), max(4, int(height * 0.34))),
        0, 0, 360, 255, -1,
    )
    return mask


class PostcardTests(unittest.TestCase):
    def test_captions_are_sparse_and_the_card_is_deterministic(self):
        image = np.full((160, 200, 3), 245, np.uint8)
        cv2.circle(image, (100, 80), 46, (15, 15, 15), -1)
        mask = _ellipse_mask(image.shape)
        self.assertTrue(mask_is_isolated(mask))
        nasty = "person"
        detection = {
            "timestamp": "2026-10-28T02:11:00",
            "class_name": nasty,
            "class_id": 0,
            "confidence": 0.5,
            "bbox": [40, 20, 160, 140],
            "position": {"cx": 0.2, "cy": 0.3, "horizontal": "left", "vertical": "upper"},
            "crop_image": image,
            "mask_image": mask,
            "frame_width": 640,
            "frame_height": 480,
        }
        repeat = dict(detection, timestamp="2026-10-28T02:11:10", confidence=0.42)
        louder = dict(detection, confidence=0.91)
        meta = _fixture_meta()
        notes = [{
            "timestamp": louder["timestamp"],
            "class_name": nasty,
            "text": "A streetlight considers the hour.",
            "model": "qwen3.5:0.8b",
        }]
        content = postcard_content(meta, [detection, repeat, louder], [], notes, note_status="fresh")
        self.assertEqual(len(content["captions"]), 1)
        self.assertEqual(content["captions"][0]["time"], "2:11 AM")
        self.assertEqual(content["captions"][0]["description"], "Qwen imagines: A streetlight considers the hour.")
        self.assertNotIn("0.91", content["captions"][0]["description"])
        self.assertNotIn("conf", content["captions"][0]["description"])
        self.assertEqual(content["message"], "")
        blob = content["date"] + content["period"] + content["captions"][0]["description"]
        self.assertNotIn("OBSERVATIONS", blob)
        self.assertNotIn("Approximate", blob)
        first = render_postcard_image(meta, [detection, repeat, louder], [], notes, seed=7, texture_bytes=None)
        second = render_postcard_image(meta, [detection, repeat, louder], [], notes, seed=7, texture_bytes=None)
        other = render_postcard_image(meta, [detection, repeat, louder], [], notes, seed=8, texture_bytes=None)
        self.assertEqual(first.size, (POSTCARD_WIDTH, POSTCARD_HEIGHT))
        self.assertEqual(first.tobytes(), second.tobytes())
        self.assertNotEqual(first.tobytes(), other.tobytes())
        unmasked = dict(detection, mask_image=np.full(image.shape[:2], 255, np.uint8))
        bare = render_postcard_image(meta, [unmasked], [], [], seed=7, texture_bytes=None)
        empty = render_postcard_image(meta, [], [], [], seed=7, texture_bytes=None)
        self.assertEqual(bare.tobytes(), empty.tobytes())
        self.assertNotEqual(first.tobytes(), empty.tobytes())

    def test_zero_detections_and_texture(self):
        meta = _fixture_meta()
        samples = [
            {"timestamp": "2026-10-28T23:05:00", "detections": 0, "frame_ok": True},
            {"timestamp": "2026-10-29T06:10:00", "detections": 0, "frame_ok": True},
        ]
        content = postcard_content(meta, [], samples, [], note_status="no-crops")
        self.assertEqual(content["message"], NO_DETECTIONS)
        self.assertEqual(NO_DETECTIONS, "No detections recorded")
        self.assertEqual(content["date"], "10/28/2026")
        self.assertIn("11:05 PM", content["period"])
        self.assertIn("6:10 AM", content["period"])
        self.assertEqual(content["captions"], [])
        quiet = render_postcard_image(meta, [], samples, [], seed=1, texture_bytes=None, note_status="no-crops")
        self.assertEqual(quiet.size, (POSTCARD_WIDTH, POSTCARD_HEIGHT))
        texture = find_texture(None)
        self.assertIsNotNone(texture)
        self.assertEqual(texture.name, "paper texture .jpg")
        self.assertIsNone(find_texture(str(Path(tempfile.gettempdir()) / "missing-paper.jpg")))
        textured = render_postcard_image(
            meta, [], samples, [], seed=1,
            texture_bytes=texture.read_bytes(), note_status="no-crops",
        )
        self.assertEqual(textured.size, quiet.size)
        self.assertNotEqual(textured.tobytes(), quiet.tobytes())

    def test_mask_changes_the_card_and_a_full_box_does_not(self):
        bus = cv2.imread(str(LAB / "bus.jpg"))
        self.assertIsNotNone(bus)
        mask = _ellipse_mask(bus.shape)
        detection = {
            "timestamp": "2026-10-28T01:15:00",
            "class_name": "bus",
            "class_id": 5,
            "confidence": 0.91,
            "bbox": [20, 30, 400, 280],
            "position": {"cx": 0.5, "cy": 0.5, "horizontal": "center", "vertical": "middle"},
            "crop_image": bus,
            "mask_image": mask,
            "frame_width": 640,
            "frame_height": 480,
        }
        meta = {
            "started": "2026-10-28T01:00:00",
            "ended": "2026-10-28T01:20:00",
            "stopped": "duration",
            "interval_s": 10,
            "camera": 0,
            "classes": ["bus"],
            "all_classes": False,
        }
        content = postcard_content(meta, [detection], [], [], note_status="skipped")
        self.assertEqual(content["captions"][0]["description"], "bus")
        self.assertEqual(content["captions"][0]["time"], "1:15 AM")
        self.assertNotIn("0.91", content["captions"][0]["description"])
        card = render_postcard_image(meta, [detection], [], [], seed=11, texture_bytes=None, note_status="skipped")
        whole = dict(detection)
        whole.pop("mask_image")
        untouched = render_postcard_image(meta, [whole], [], [], seed=11, texture_bytes=None, note_status="skipped")
        empty = render_postcard_image(meta, [], [], [], seed=11, texture_bytes=None, note_status="skipped")
        self.assertEqual(untouched.tobytes(), empty.tobytes())
        self.assertNotEqual(card.tobytes(), empty.tobytes())
        with tempfile.TemporaryDirectory() as tmp:
            path = write_postcard(
                Path(tmp) / "morning_postcard.png", meta, [detection], [], [], 11,
                texture_bytes=None, note_status="skipped",
            )
            self.assertEqual([item.name for item in Path(tmp).iterdir()], ["morning_postcard.png"])
            self.assertFalse(path.with_name(path.name + ".partial").exists())
            with Image.open(path) as saved:
                self.assertEqual(saved.size, (POSTCARD_WIDTH, POSTCARD_HEIGHT))
                self.assertEqual(saved.format, "PNG")


class SegmentTests(unittest.TestCase):
    def test_detection_boxes_are_not_masks_and_grabcut_keeps_a_circle(self):
        self.assertNotIn("yolo26n_ncnn_model", SEG_CANDIDATES)
        self.assertIsNone(resolve_seg_path("no/such/yolo26n-seg_ncnn_model"))

        class BoxesOnly:
            masks = None
            boxes = object()
            names = {0: "person"}

        self.assertEqual(instances_from_result(BoxesOnly()), [])
        flat = np.full((120, 120, 3), 180, np.uint8)
        self.assertFalse(mask_is_isolated(grabcut_mask(flat)))
        self.assertFalse(mask_is_isolated(np.full((80, 80), 255, np.uint8)))
        circle = np.full((180, 180, 3), 235, np.uint8)
        cv2.circle(circle, (90, 90), 48, (20, 30, 40), -1)
        isolated = grabcut_mask(circle)
        self.assertTrue(mask_is_isolated(isolated))
        self.assertLess(int(isolated[4, 4]), 128)
        self.assertGreater(int(isolated[90, 90]), 128)


class QwenTests(unittest.TestCase):
    def test_request_pattern_and_skip(self):
        body = build_request("qwen3.5:0.8b", "note", image_bytes=b"jpeg-bytes")
        self.assertFalse(body["think"])
        self.assertFalse(body["stream"])
        self.assertEqual(body["model"], "qwen3.5:0.8b")
        self.assertIn("images", body)
        self.assertEqual(body["options"]["num_predict"], 80)
        self.assertIn("imaginative", SYSTEM)
        self.assertIn("clothing", SYSTEM)
        self.assertIn("identify", SYSTEM)
        prompt = prompt_for({
            "class_name": "bus",
            "timestamp": "2026-10-28T01:00:00",
            "confidence": 0.5,
            "position": {"vertical": "upper", "horizontal": "left"},
        })
        self.assertIn("imagination", prompt)
        self.assertIn("clothing", prompt)
        self.assertIn("identity", prompt)
        self.assertIn("relationships", prompt)
        self.assertIn("intent", prompt)
        with tempfile.TemporaryDirectory() as tmp:
            def refuse(*args, **kwargs):
                raise AssertionError("Ollama should not be called")
            notes, status = prepare_speculations(tmp, [], skip=True, cap=3, post=refuse)
            self.assertEqual(notes, [])
            self.assertEqual(status, "skipped")

            session = Path(tmp)
            (session / "crops").mkdir(exist_ok=True)
            crop = session / "crops" / "bus.jpg"
            crop.write_bytes((LAB / "bus.jpg").read_bytes())
            detection = {"timestamp": "2026-10-28T01:00:00", "class_name": "bus", "confidence": 0.4,
                         "position": {"vertical": "middle", "horizontal": "center"}, "crop": "crops/bus.jpg"}
            seen = {}

            def post(url, json=None, timeout=None):
                seen["url"] = url
                seen["body"] = json
                class Reply:
                    def raise_for_status(self):
                        return None
                    def json(self):
                        return {"response": "A streetlight considers the hour.", "thinking": "hidden"}
                return Reply()

            notes, status = prepare_speculations(session, [detection], skip=False, cap=1, post=post)
            self.assertEqual(status, "fresh")
            self.assertEqual(notes[0]["text"], "A streetlight considers the hour.")
            self.assertNotIn("hidden", notes[0]["text"])
            self.assertEqual(seen["url"], OLLAMA_URL)
            self.assertFalse(seen["body"]["think"])
            self.assertIn("images", seen["body"])

            import requests

            def down(url, json=None, timeout=None):
                raise requests.ConnectionError("down")

            kept, kept_status = prepare_speculations(session, [detection], skip=False, cap=1, post=down)
            self.assertEqual(kept_status, "failed-kept-saved")
            self.assertEqual(kept[0]["text"], "A streetlight considers the hour.")
            (session / "speculations.json").unlink()
            notes, status = prepare_speculations(session, [detection], skip=False, cap=1, post=down)
            self.assertEqual(status, "failed")
            self.assertEqual(notes, [])

            before = {path.name for path in session.iterdir()}
            memory = dict(detection)
            memory["crop_path"] = str(crop)
            skipped, skipped_status = collect_notes([memory], skip=True, cap=3, post=refuse)
            self.assertEqual(skipped, [])
            self.assertEqual(skipped_status, "skipped")
            self.assertEqual({path.name for path in session.iterdir()}, before)
            fresh, fresh_status = collect_notes([memory], skip=False, cap=1, post=post)
            self.assertEqual(fresh_status, "fresh")
            self.assertEqual(fresh[0]["text"], "A streetlight considers the hour.")
            self.assertNotIn("crop", fresh[0])
            self.assertEqual({path.name for path in session.iterdir()}, before)


def _only_postcard(session):
    names = [path.name for path in session.rglob("*") if path.is_file()]
    return names


class ObserveTests(unittest.TestCase):
    def test_fake_clock_stops_at_duration_and_keeps_interrupt(self):
        frame = np.zeros((480, 640, 3), np.uint8)
        crop = padded_crop(frame, BIRD["xyxy"])
        self.assertIsNotNone(crop)
        self.assertLess(crop.shape[1], 640)
        self.assertLess(crop.shape[0], 480)
        self.assertGreater(crop.shape[1], 120)
        with tempfile.TemporaryDirectory() as tmp:
            clock = Clock()
            camera = FakeCamera()
            predictor = FakePredictor([BIRD])
            args = _args(tmp, ["--duration", "30", "--interval", "10", "--skip-qwen"])
            output = io.StringIO()
            with patch("sys.stdout", output):
                session = run_observe(args, camera=camera, predictor=predictor, clock=clock.time, sleeper=clock.sleep)
            self.assertTrue(camera.released)
            self.assertEqual(clock.t, 1030.0)
            text = output.getvalue()
            self.assertIn("3 samples, 3 detections", text)
            self.assertEqual(_only_postcard(session), ["morning_postcard.png"])
            with Image.open(session / "morning_postcard.png") as card:
                self.assertEqual(card.size, (POSTCARD_WIDTH, POSTCARD_HEIGHT))

        with tempfile.TemporaryDirectory() as tmp:
            clock = Clock()

            def interrupt(seconds):
                clock.t += float(seconds)
                raise KeyboardInterrupt

            camera = FakeCamera()
            args = _args(tmp, ["--duration", "30", "--interval", "10", "--skip-qwen"])
            output = io.StringIO()
            with patch("sys.stdout", output):
                session = run_observe(
                    args, camera=camera, predictor=FakePredictor([BIRD]),
                    clock=clock.time, sleeper=interrupt,
                )
            self.assertTrue(camera.released)
            text = output.getvalue()
            self.assertIn("1 sample, 1 detection", text)
            self.assertIn("interrupt", text)
            self.assertEqual(_only_postcard(session), ["morning_postcard.png"])

    def test_command_stops_after_configured_duration(self):
        with tempfile.TemporaryDirectory() as tmp:
            camera = FakeCamera()
            started = time.time()
            with patch("observatory.observe.open_camera", return_value=camera), \
                 patch("observatory.observe.build_predictor", return_value=FakePredictor()):
                code = main([
                    "observe", "--duration", "0.7", "--interval", "0.25",
                    "--output", tmp, "--skip-qwen",
                ])
            elapsed = time.time() - started
            self.assertEqual(code, 0)
            self.assertTrue(camera.released)
            self.assertGreaterEqual(elapsed, 0.65)
            self.assertLess(elapsed, 8)
            sessions = [path for path in Path(tmp).iterdir() if path.is_dir()]
            self.assertEqual(len(sessions), 1)
            self.assertEqual(_only_postcard(sessions[0]), ["morning_postcard.png"])

    def test_class_filter_and_short_default(self):
        parser = build_parser()
        default = parser.parse_args(["observe"])
        self.assertEqual(default.duration, 15)
        self.assertEqual(default.interval, 10)
        self.assertFalse(default.show)
        self.assertTrue(parser.parse_args(["observe", "--headless"]).headless)
        self.assertEqual(
            class_names_from_args(default),
            ["person", "bird", "bus", "car", "dog"],
        )
        self.assertIsNone(class_names_from_args(parser.parse_args(["observe", "--all"])))
        with self.assertRaises(SystemExit):
            class_names_from_args(parser.parse_args(["observe", "--classes", "bird,unicorn"]))
        self.assertEqual(resolve_class_ids({0: "person", 14: "bird", 5: "bus"}, ["bird", "person"]), [14, 0])
        with self.assertRaises(SystemExit):
            build_predictor("no/such/yolo26n_ncnn_model", 0.4, 320, ["person"])

    def test_seed_comes_from_the_session(self):
        meta = {"started": "2026-10-28T01:00:00", "ended": "2026-10-28T02:00:00",
                "interval_s": 10, "camera": 0, "classes": ["bird"], "all_classes": False}
        self.assertEqual(seed_from_session(meta), seed_from_session(dict(meta)))
        other = dict(meta)
        other["started"] = "2026-10-29T01:00:00"
        self.assertNotEqual(seed_from_session(meta), seed_from_session(other))


class GestureTests(unittest.TestCase):
    def test_quiet_coyote_distances(self):
        points = [[index, 0, 0] for index in range(21)]
        self.assertFalse(is_quiet_coyote(points))
        self.assertFalse(is_quiet_coyote(points[:5]))
        points[16] = [16, 0, 0]
        points[12] = [12, 50, 0]
        points[4] = [4, 30, 40]
        points[8] = [8, 30, 200]
        points[20] = [20, 0, 150]
        self.assertTrue(is_quiet_coyote(points))


def _det(name, timestamp, cx, cy):
    return {
        "timestamp": timestamp,
        "class_name": name,
        "position": {"cx": cx, "cy": cy, "horizontal": "center", "vertical": "middle"},
    }


if __name__ == "__main__":
    unittest.main()
