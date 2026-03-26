# hstui

A terminal UI for controlling SteelSeries headsets via [headsetcontrol](https://github.com/Sapd/HeadsetControl).

Built with [urwid](https://urwid.org/).

## Supported devices

- SteelSeries Arctis Nova 7
- SteelSeries Arctis Nova Pro Wireless

The TUI detects the connected device at startup and only shows controls it supports.

## Features

- Sidetone control (numeric slider or stepped, depending on device)
- 10-band equaliser with presets (Flat, Bass, Focus, Smiley)
- Lights toggle (Nova Pro Wireless)
- Microphone volume and mute LED brightness (Nova 7)
- Inactive timeout, volume limiter (Nova 7)
- Bluetooth call ducking and power-on behaviour (Nova 7)
- Live battery level and chatmix display (Nova 7)
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
