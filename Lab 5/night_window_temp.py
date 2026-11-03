"""Night Window Observatory with DHT11 temperature and humidity.

The Pi samples a privacy-safe view outside a window. When the watch ends it
writes one postcard, morning_postcard.png: detector observations, ASCII from
the crops, a chronological temperature color band whose height represents
humidity, and optional speculative notes from local Qwen.

    python night_window.py observe --headless
    python night_window.py observe --duration 30 --interval 10 --headless
    python night_window.py observe --duration 28800 --interval 20 --qwen-cap 3
    python night_window.py observe --all
    python night_window.py observe --classes bird,car,bus

Default duration is 15 seconds so a forgotten flag cannot watch all night.
Pass --duration for a longer observation. Default interval is 2 seconds,
so a short watch still stacks several frames.
Ctrl-C stops early and still writes the postcard. Quiet Coyote (--gesture) is optional.
The DHT11 is read from GPIO D4 at each observation interval. Use
night_window.py instead when no temperature sensor is connected.
"""
import os
import sys

# Headless unless a window was requested. Qt on the Pi bus-errors if it
# starts with no display, and it can also flash a camera window.
if "--show" not in sys.argv or "--headless" in sys.argv:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    os.environ.setdefault("MPLBACKEND", "Agg")

import argparse

from observatory.coco import WINDOW_CLASSES, class_names_from_args
from observatory.observe import run_observe
from observatory.qwen_notes import DEFAULT_MODEL
from temp_test import create_sensor, read_sensor


def build_parser():
    parser = argparse.ArgumentParser(description="Night Window Observatory")
    sub = parser.add_subparsers(dest="command", required=True)

    observe = sub.add_parser("observe", help="sample the camera, then write morning_postcard.png")
    observe.add_argument("--duration", type=float, default=15,
                         help="seconds to watch (default 15, a short test; set this for a real night)")
    observe.add_argument("--interval", type=float, default=2,
                         help="seconds between samples (default 2, so frames can stack)")
    observe.add_argument("--camera", type=int, default=0, help="camera index")
    observe.add_argument("--model", default="yolo26n_ncnn_model", help="YOLO26 nano NCNN detection model path")
    observe.add_argument("--seg-model", default=None,
                         help="YOLO26 nano segmentation model (default: yolo26n-seg_ncnn_model if present)")
    observe.add_argument("--conf", type=float, default=0.4, help="minimum confidence, 0 to 1")
    observe.add_argument("--imgsz", type=int, default=320, help="frame size the model looks at")
    observe.add_argument("--classes", default=",".join(WINDOW_CLASSES),
                         help="comma-separated COCO names (default: person,bird,bus,car,dog)")
    observe.add_argument("--all", action="store_true", help="detect all 80 COCO classes, not the window set")
    observe.add_argument("--output", default="observations", help="parent directory for this session")
    observe.add_argument("--headless", action="store_true",
                         help="no camera window (this is already the default)")
    observe.add_argument("--show", action="store_true", help="open a window (needs a display); q stops early")
    observe.add_argument("--gesture", action="store_true",
                         help="optional Quiet Coyote start/stop; the timer works without it")
    observe.add_argument("--gesture-wait", type=float, default=20, help="seconds to wait for a start gesture")
    observe.add_argument("--skip-qwen", action="store_true",
                         help="do not call Ollama; the postcard and ASCII are still written")
    observe.add_argument("--qwen-cap", type=int, default=3,
                         help="max crops to send to Qwen (image calls are slow)")
    observe.add_argument("--qwen-model", default=DEFAULT_MODEL, help="local Ollama model, image-capable")
    observe.add_argument("--seed", type=int, default=None, help="layout seed; default comes from the session")
    observe.add_argument("--texture", default=None,
                         help="paper texture image; default is poetic surveillance/paper texture .jpg if present")
    return parser


def _configure_stdio():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


def cmd_observe(args):
    class_names_from_args(args)
    if args.duration <= 0 or args.interval <= 0:
        raise SystemExit("Duration and interval must be greater than 0.")
    if getattr(args, "headless", False):
        args.show = False
    if args.show and sys.platform.startswith("linux") and not os.environ.get("DISPLAY"):
        print("no display found (plain ssh?): running without the window. Use VNC to see it.", flush=True)
        args.show = False
    if not args.show:
        print("Headless: no camera window.", flush=True)
    sensor = create_sensor()
    try:
        run_observe(args, sensor_reader=lambda: read_sensor(sensor))
    finally:
        sensor.exit()
    return 0


def main(argv=None):
    _configure_stdio()
    args = build_parser().parse_args(argv)
    if args.command == "observe":
        return cmd_observe(args)
    raise SystemExit(f"unknown command {args.command}")


if __name__ == "__main__":
    sys.exit(main())