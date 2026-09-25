# Sky clock for the Adafruit MiniPiTFT (ST7789).
#
# Display hardware: screen_test.py / screen_boot_script.py
# Text drawing:     screen_boot_script.py
#
# Real clock hour picks the phase (morning / afternoon / evening).
# A repeating 10-minute cycle only blends that phase's two colors.
# Example: at 17:00 the phase is Afternoon, so 17:00-17:10 runs
# #B0E0E6 -> #007BFF, then that same blue gradient loops.

import time
import digitalio
import board
from PIL import Image, ImageDraw, ImageFont
import adafruit_rgb_display.st7789 as st7789

# ---------------------------
# Phase palettes (start -> end over 10 minutes)
# ---------------------------
MORNING_START = (255, 210, 0)      # #FFD200
MORNING_END = (247, 151, 30)       # #F7971E

AFTERNOON_START = (176, 224, 230)  # #B0E0E6
AFTERNOON_END = (0, 123, 255)      # #007BFF

EVENING_START = (225, 190, 231)    # #E1BEE7
EVENING_END = (106, 27, 146)       # #6A1B92

# How long one in-phase gradient takes, then it repeats.
CYCLE_SECONDS = 600

# Real-time hour ranges. 17:00 is Afternoon.
MORNING_HOURS = range(6, 12)       # 6:00-11:59
AFTERNOON_HOURS = range(12, 18)    # 12:00-17:59
# Everything else (18:00-5:59) is Evening/Night.

# ---------------------------
# SPI + Display configuration
# ---------------------------
cs_pin = digitalio.DigitalInOut(board.D5)
dc_pin = digitalio.DigitalInOut(board.D25)
reset_pin = None
BAUDRATE = 64000000
spi = board.SPI()

disp = st7789.ST7789(
    spi,
    cs=cs_pin,
    dc=dc_pin,
    rst=reset_pin,
    baudrate=BAUDRATE,
    width=135,
    height=240,
    x_offset=53,
    y_offset=40,
)

height = disp.width
width = disp.height
image = Image.new("RGB", (width, height))
rotation = 90
draw = ImageDraw.Draw(image)

font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
time_font = ImageFont.truetype(font_path, 36)
label_font = ImageFont.truetype(font_path, 22)

backlight = digitalio.DigitalInOut(board.D22)
backlight.switch_to_output()
backlight.value = True


def lerp(a, b, t):
    return a + (b - a) * t


def mix_rgb(start, end, t):
    """Blend two RGB tuples. t=0 is start, t=1 is end."""
    r = int(lerp(start[0], end[0], t))
    g = int(lerp(start[1], end[1], t))
    b = int(lerp(start[2], end[2], t))
    return (r, g, b)


def phase_for_hour(hour):
    """Pick palette from the real clock, not from the 10-minute cycle."""
    if hour in MORNING_HOURS:
        return "Morning", MORNING_START, MORNING_END, True
    if hour in AFTERNOON_HOURS:
        return "Afternoon", AFTERNOON_START, AFTERNOON_END, False
    return "Evening", EVENING_START, EVENING_END, False


def centered_text(text, font, y, fill):
    bbox = draw.textbbox((0, 0), text, font=font)
    text_width = bbox[2] - bbox[0]
    x = (width - text_width) // 2
    draw.text((x, y), text, font=font, fill=fill)


print("In-phase 10-minute gradient clock. Ctrl+C to stop.")

try:
    while True:
        local = time.localtime()
        hour = local.tm_hour
        clock_text = time.strftime("%H:%M:%S", local)

        # Align to the clock: 17:00 -> 17:10 is one full start->end blend.
        # (minute % 10) makes windows :00-:10, :10-:20, :20-:30, ...
        elapsed = (local.tm_min % 10) * 60 + local.tm_sec
        pos = elapsed / float(CYCLE_SECONDS)

        phase_name, start, end, dark_text = phase_for_hour(hour)
        rgb = mix_rgb(start, end, pos)

        draw.rectangle((0, 0, width, height), outline=0, fill=rgb)

        text_fill = "#000000" if dark_text else "#FFFFFF"
        centered_text(phase_name, label_font, 28, text_fill)
        centered_text(clock_text, time_font, 62, text_fill)

        disp.image(image, rotation)
        time.sleep(0.25)
except KeyboardInterrupt:
    print("\nStopped.")
