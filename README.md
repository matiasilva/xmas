# xmas

A wearable Christmas tree badge: six PWM-driven LEDs, a pattern button and a
PY32F002B microcontroller, powered by a CR2032.

## Layout

- `hardware/` - KiCad 10 project. Open `hardware/tree.kicad_pro`.
  - `tree.pretty/`, `tree.3dshapes/`, `tree.kicad_sym` - project footprints, 3D models and symbols
  - `checks/` - board checks; run `python3 hardware/checks/pad_check.py` and `python3 hardware/checks/led_sim.py`
- `firmware/` - firmware source goes here. Requirements are in `firmware/TODO.md`.
