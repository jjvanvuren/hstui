# hstui

A terminal UI for controlling a SteelSeries Arctis Nova 7 headset via [headsetcontrol](https://github.com/Sapd/HeadsetControl).

Built with [urwid](https://urwid.org/).

## Features

- Sidetone and microphone volume control
- 10-band equaliser with presets (Flat, Bass, Focus, Smiley)
- Mute LED brightness, inactive timeout, volume limiter
- Bluetooth call ducking and power-on behaviour
- Live battery level and chatmix display (1-second refresh)
- Fully keyboard-driven with vim-style navigation

## Installation

Requires [headsetcontrol](https://github.com/Sapd/HeadsetControl) on your PATH.

```bash
pipx install .
```

Or in a venv:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

## Usage

```bash
hstui
```

### Key bindings

| Key | Action |
|---|---|
| `j`/`k`/`↑`/`↓` | Navigate between controls |
| `h`/`l`/`←`/`→` | Adjust values |
| `1`-`4` | Select EQ preset |
| `a` | Apply custom EQ |
| `e` | Toggle equaliser section |
| `enter`/`space` | Toggle switches |
| `q` | Quit |
