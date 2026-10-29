# Night Window Observatory

The Pi watches a window for a duration you set, one frame every few seconds. When that period ends it writes one file, `morning_postcard.png`. The card holds detector observations, ASCII made from the crops, and optional notes from local Qwen. Qwen's notes are imagination, not verified facts.

Part 1 scripts (`yolo_person.py`, `overnight.py`, `morning.py`, and the rest) are unchanged. Run these commands from the `Lab 5` folder, in the same virtualenv as the rest of the lab.

Get consent from everyone in the household before a camera run. Point the camera away from beds and away from neighboring windows. Crops are deleted when the postcard has been written. The session folder keeps only the PNG.

## Short test

The default watch is 15 seconds, with a sample every 10 seconds. That is a test, not a night.

```bash
python night_window.py observe --headless
```

That does not open a camera window. `--show` is the only flag that does, and it needs VNC. Press `q` in that window, or Ctrl-C, to stop early. The postcard is still written from whatever was seen.

The command prints the session folder. Inside it, the only file is `morning_postcard.png`.

## Longer observation

Pass `--duration` yourself. Nothing longer than the 15-second default runs unless you do. Interval stays in the lab's 5 to 30 second range unless you change it. This samples still frames. It does not record video.

```bash
tmux new -s night
python night_window.py observe --duration 28800 --interval 20 --qwen-cap 3
```

Eight hours is 28800 seconds. Ctrl-C in the morning still writes the postcard. `--qwen-cap` limits how many crops are sent to local Ollama, because image calls are slow on the Pi. `--skip-qwen` still writes the postcard and the ASCII when Ollama is down or you want the picture quickly.

Other useful flags:

```bash
python night_window.py observe --duration 600 --interval 15 --classes bird,car,bus --skip-qwen
python night_window.py observe --duration 600 --all
python night_window.py observe --duration 60 --gesture --skip-qwen
python night_window.py observe --duration 60 --seed 7 --skip-qwen
```

`--all` detects every COCO class, same idea as `yolo_person.py --all`. The default filter is person, bird, bus, car, and dog. `--gesture` looks for the Quiet Coyote pose from Part C. The timer and Ctrl-C work without it. If MediaPipe cannot start, the watch still runs on the timer.

The detection model defaults to `yolo26n_ncnn_model` from Part A. Camera index, confidence, and `imgsz` match the Part B/E scripts (`--camera`, `--conf`, `--imgsz`).

The normal run does not open a window and does not load a second YOLO model. Each crop is isolated with OpenCV GrabCut. The detection model does not produce masks. A crop that still cannot be separated from its box is left off the card. `--seg-model` can point at a segmentation checkpoint, but the NCNN segmentation export is what Bus-errors on the Pi, so leave that flag off.

## What gets saved

Each session folder contains only:

- `morning_postcard.png` — portrait, 1470 × 2108, openable without a browser

Crops are written to a temporary folder so the postcard can be drawn, then that folder is removed. There is no log, HTML page, or crop directory left behind.

Repeated nearby boxes of the same class become one figure. The rule is: same class, normalized centers within 0.18 of the frame, and no more than 3 sample intervals apart. That is proximity. It is not the same individual. The card does not list every frame.

## Postcard

The top left has `DATE` and `OBSERVATION PERIOD` in small monospace type, about 8–10 pt at 300 dpi. The rest of the sheet is colored ASCII of the masked objects. Beside each figure is its time and one short description. When Qwen answers, that line begins with `Qwen imagines:`. There is no confidence, coordinate, count, legend, or footer.

Colors are `rgb(r, g, b)` with each channel chosen from 0–255. A color that would disappear into the paper is drawn again. Layout and color come from a seed derived from the session, unless you pass `--seed`. The same session data draws the same card. Text sits on the paper, with a one-pixel halo so it stays readable. It is not set in a box.

If `poetic surveillance/paper texture .jpg` is present it is washed in faintly. If that file is missing, the card uses a generated paper field and says so in the terminal. Nothing is fetched from the network.

If nothing can be drawn, the card still finishes and says "No detections recorded".

## Tests

```bash
python -m unittest discover -s tests -q
```

## Limits

YOLO can miss an object or mislabel it. Qwen's sentence is imagination, marked `Qwen imagines:`, and it is not a verified observation. A detection box is not a silhouette. The ASCII is only the masked foreground. The watch was not timed on a Pi camera in this checkout unless you run it there yourself. Ultralytics is not installed in this Mac checkout, so the segmentation path here is OpenCV GrabCut unless `yolo26n-seg_ncnn_model` is present.
