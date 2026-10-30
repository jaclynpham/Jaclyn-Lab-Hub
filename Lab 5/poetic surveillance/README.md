# Poetic Surveillance

The Pi watches a window, one still frame every few seconds. When the watch ends it writes one file, `observations/<timestamp>/morning_postcard.png`. The card is ASCII made from the masked crops, with the date, the observation period, and a short line beside each figure. If Ollama is running, that line is a guess from local Qwen and begins with `Qwen imagines:`. Those sentences are imagination, not verified facts.

Get consent from everyone in the household before a camera run. Point the camera away from beds and away from neighboring windows. Crops are deleted when the postcard has been written. Each session folder keeps only the PNG.

Run every command below from this folder, `Lab 5/poetic surveillance`.

## Setup

Use the Lab 5 virtualenv if you already made one for Part A:

```bash
cd "Lab 5"
source .venv/bin/activate
cd "poetic surveillance"
```

Or make a venv here and install this folder's requirements. They match the Lab 5 list, plus Pillow for the postcard.

```bash
cd "Lab 5/poetic surveillance"
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

The detector is the Part A export, `yolo26n_ncnn_model`. Leave that folder in `Lab 5`. This program finds it there. If you still need to export it, do that once from `Lab 5`:

```bash
python -c "from ultralytics import YOLO; YOLO('yolo26n.pt').export(format='ncnn')"
```

Qwen is optional. It is not installed by `requirements.txt`. On the Pi, with [Ollama](https://ollama.com) already running:

```bash
ollama pull qwen3.5:0.8b
```

The program calls `http://localhost:11434` and the model `qwen3.5:0.8b`. If Ollama is down, pass `--skip-qwen`. The postcard and the ASCII are still written.

## Run

A short test is 15 seconds, with a frame about every 2 seconds. It does not open a camera window.

```bash
python night_window.py observe --headless
```

Five minutes:

```bash
python night_window.py observe --duration 300 --headless
```

A longer night. Eight hours is 28800 seconds. A wider interval keeps the Pi cooler. Ctrl-C still writes the postcard from whatever was seen.

```bash
tmux new -s night
python night_window.py observe --duration 28800 --interval 20 --qwen-cap 3
```

`--show` is the only flag that opens a window, and it needs a display. Press `q` in that window, or Ctrl-C, to stop early.

Other flags:

```bash
python night_window.py observe --duration 600 --classes bird,car,bus --skip-qwen
python night_window.py observe --duration 600 --all
python night_window.py observe --duration 60 --gesture --skip-qwen
python night_window.py observe --duration 60 --seed 7 --skip-qwen
```

`--all` detects every COCO class. The default filter is person, bird, bus, car, and dog. `--gesture` looks for the Quiet Coyote pose from Part C, using `HandTrackingModule.py` in the parent Lab 5 folder. The timer and Ctrl-C work without it.

`--qwen-cap` limits how many crops are sent to Ollama, because image calls are slow. Nearby repeats of the same class share one caption. Up to six of those frames are drawn on top of each other.

## What gets saved

Each session folder contains only `morning_postcard.png`, a portrait image, 1470 × 2108. The paper texture in this folder, `paper texture .jpg`, is washed in faintly. If that file is missing, the card uses a generated paper field.

The top left has `DATE` and `OBSERVATION PERIOD`. Beside each figure, the time and description are smaller. There is no confidence, coordinate, count, legend, or footer. If nothing can be drawn, the card still finishes and says "No detections recorded".

Do not pass `--seg-model` unless you mean to. The NCNN segmentation export can Bus-error on the Pi. The normal run isolates each crop with OpenCV GrabCut. A crop that still cannot be separated from its box is left off the card.

## Tests

```bash
python -m unittest discover -s tests -q
```
