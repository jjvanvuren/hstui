"""
TUI application for controlling SteelSeries headsets.

Supported devices:
- Arctis Nova 7 (0x2202)
- Arctis Nova Pro Wireless (0x12e0)

Uses headsetcontrol CLI tool for communication with the device.
Built with urwid for native terminal background rendering.
"""

import json
import subprocess
from collections.abc import Hashable

import urwid

# Equaliser band centre frequencies (Hz) for the 10-band EQ
EQ_BAND_LABELS = [
    '32',
    '64',
    '125',
    '250',
    '500',
    '1k',
    '2k',
    '4k',
    '8k',
    '16k',
]

EQ_PRESETS = {
    0: 'Flat',
    1: 'Bass',
    2: 'Focus',
    3: 'Smiley',
}

EQ_PRESET_VALUES = {
    0: [0.0] * 10,
    1: [3.5, 5.5, 4.0, 1.0, -1.5, -1.5, -1.0, -1.0, -1.0, -1.0],
    2: [-5.0, -3.5, -1.0, -3.5, -2.5, 4.0, 6.0, -3.5, 0.0, 0.0],
    3: [3.0, 3.5, 1.5, -1.5, -4.0, -4.0, -2.5, 1.5, 3.0, 4.0],
}

# Known product IDs
PID_ARCTIS_NOVA_7 = '0x2202'
PID_ARCTIS_NOVA_PRO_WIRELESS = '0x12e0'

# Device-specific software presets (sent via -e, not -p)
# Each entry maps preset index to (name, band_values).
DEVICE_EQ_PRESETS: dict[str, dict[int, tuple[str, list[float]]]] = {
    PID_ARCTIS_NOVA_7: {
        4: ('Rtings', [-2.6, -1.3, -6.1, 3.1, 3.4, -0.6, 1.1, 3.4, -8.7, -2.4]),
    },
    PID_ARCTIS_NOVA_PRO_WIRELESS: {
        4: ('oratory1990', [2.9, 0.9, -5.3, -1.2, 2.4, -1.2, 0.7, 2.2, 0.1, -0.2]),
        5: ('Rtings', [0.5, 2.3, -3.8, 1.4, 4.0, -1.8, -1.7, 5.7, -6.9, -7.0]),
    },
}

BATTERY_ICONS = {
    (0, 10): '\U000f007a',  # 󰁺
    (10, 20): '\U000f007b',  # 󰁻
    (20, 30): '\U000f007c',  # 󰁼
    (30, 40): '\U000f007d',  # 󰁽
    (40, 50): '\U000f007e',  # 󰁾
    (50, 60): '\U000f007f',  # 󰁿
    (60, 70): '\U000f0080',  # 󰂀
    (70, 80): '\U000f0081',  # 󰂁
    (80, 90): '\U000f0082',  # 󰂂
    (90, 101): '\U000f0079',  # 󰁹
}

PALETTE = [
    ('default', '', ''),
    ('heading', 'dark cyan,bold', ''),
    ('accent', 'dark cyan', ''),
    ('accent_bold', 'dark cyan,bold', ''),
    ('value', 'dark cyan,bold', ''),
    ('bar_filled', 'dark cyan', ''),
    ('bar_empty', 'dark gray', ''),
    ('focused', 'dark cyan,bold', ''),
    ('toggle_on', 'dark green,bold', ''),
    ('toggle_off', 'dark gray', ''),
    ('error', 'dark red,bold', ''),
    ('battery_good', 'dark green', ''),
    ('battery_warn', 'yellow', ''),
    ('battery_low', 'dark red', ''),
    ('disconnected', 'dark red,bold', ''),
    ('feedback', 'dark gray', ''),
    ('help', 'dark gray', ''),
    ('dim', 'dark gray', ''),
]


def battery_icon(level):
    """
    Return a battery icon for the given level.
    """
    for (lo, hi), icon in BATTERY_ICONS.items():
        if lo <= level < hi:
            return icon
    return '\U000f0083'  # 󰂃 unknown


def battery_colour_attr(level):
    """
    Return a palette attribute name based on battery level.
    """
    if level <= 15:
        return 'battery_low'
    if level <= 30:
        return 'battery_warn'
    return 'battery_good'


def run_headsetcontrol(*args):
    """
    Run headsetcontrol with the given arguments.

    Returns a tuple of (success, stdout_or_stderr).
    """
    try:
        result = subprocess.run(
            ['headsetcontrol', *args],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return True, result.stdout.strip()
        return False, result.stderr.strip()
    except FileNotFoundError:
        return False, 'headsetcontrol not found on PATH'
    except subprocess.TimeoutExpired:
        return False, 'headsetcontrol timed out'
    except Exception as exc:
        return False, str(exc)


def read_device_state(has_chatmix=False):
    """
    Query headsetcontrol for the current device state.

    Returns the first device dict from JSON output, or None on failure.
    When has_chatmix is True, the -m flag is included to query chatmix.
    """
    args = ['-o', 'json', '-b']
    if has_chatmix:
        args.append('-m')
    ok, output = run_headsetcontrol(*args)
    if not ok:
        return None
    try:
        data = json.loads(output)
        devices = data.get('devices', [])
        if devices and devices[0].get('status') == 'success':
            return devices[0]
    except json.JSONDecodeError:
        pass
    return None


def detect_device():
    """
    Detect the connected headset and its capabilities.

    Returns a tuple of (device_name, product_id, capabilities_set).
    On failure, returns ('Unknown', '', set()).
    """
    ok, output = run_headsetcontrol('-o', 'json')
    if not ok:
        return 'Unknown', '', set()
    try:
        data = json.loads(output)
        devices = data.get('devices', [])
        if devices and devices[0].get('status') == 'success':
            device = devices[0]
            name = device.get('product', 'Unknown')
            product_id = device.get('id_product', '')
            caps = set(device.get('capabilities', []))
            return name, product_id, caps
    except json.JSONDecodeError:
        pass
    return 'Unknown', '', set()


def make_bar(value, max_val, width=20) -> list[str | tuple[Hashable, str]]:
    """
    Create a text-based progress bar using block characters.
    """
    if max_val <= 0:
        return [('bar_empty', '\u2591' * width)]
    filled = int(round(value / max_val * width))
    filled = max(0, min(filled, width))
    empty = width - filled
    return [
        ('bar_filled', '\u2588' * filled),
        ('bar_empty', '\u2591' * empty),
    ]


class VimListBox(urwid.ListBox):
    """
    ListBox that translates j/k to down/up for vim-style navigation.
    """

    _KEY_MAP = {'j': 'down', 'k': 'up'}

    def keypress(self, size, key):
        return super().keypress(size, self._KEY_MAP.get(key, key))


class BaseControl(urwid.WidgetWrap):
    """
    Base for all selectable controls with a focus indicator.

    Subclasses must create self._indicator as a urwid.Text widget.
    """

    _indicator: urwid.Text
    _last_focus: bool | None = None

    def selectable(self):
        return True

    def render(self, size, focus=False):
        if focus != self._last_focus:
            self._last_focus = focus
            self._indicator.set_text(('accent', '▸ ') if focus else ('dim', '  '))
        return super().render(size, focus)


class NumericControl(BaseControl):
    """
    A labelled numeric value with a progress bar.

    Adjustable via h/l or left/right keys.
    """

    signals = ['changed']

    def __init__(
        self, label, min_val, max_val, step, initial, control_id, display_fmt=None
    ):
        self.label_text = label
        self.min_val = min_val
        self.max_val = max_val
        self.step = step
        self.value = initial
        self.control_id = control_id
        self._display_fmt = display_fmt or str
        self._user_set = False
        self._indicator = urwid.Text(('dim', ' '))
        self._label_w = urwid.Text(('dim', self.label_text))
        self._value_w = urwid.Text(
            ('dim', self._display_fmt(self.value)), align='right'
        )
        self._bar_w = urwid.Text(make_bar(self.value, self.max_val))
        cols = urwid.Columns(
            [
                (urwid.GIVEN, 2, self._indicator),
                (urwid.GIVEN, 28, self._label_w),
                (urwid.GIVEN, 6, self._value_w),
                (urwid.GIVEN, 1, urwid.Text(' ')),
                (urwid.GIVEN, 20, self._bar_w),
            ],
            dividechars=0,
        )
        super().__init__(cols)

    def _update_display(self):
        val_attr = 'value' if self._user_set else 'dim'
        label_attr = 'default' if self._user_set else 'dim'
        self._label_w.set_text((label_attr, self.label_text))
        self._value_w.set_text((val_attr, self._display_fmt(self.value)))
        self._bar_w.set_text(make_bar(self.value, self.max_val))

    def keypress(self, size, key):
        if key in ('right', 'l', '+'):
            old = self.value
            self.value = min(self.value + self.step, self.max_val)
            if self.value != old:
                self._user_set = True
                self._update_display()
                urwid.emit_signal(self, 'changed', self.control_id, self.value)
            return None
        if key in ('left', 'h', '-'):
            old = self.value
            self.value = max(self.value - self.step, self.min_val)
            if self.value != old:
                self._user_set = True
                self._update_display()
                urwid.emit_signal(self, 'changed', self.control_id, self.value)
            return None
        return key

    def set_value(self, value):
        """
        Programmatically set the value.
        """
        self.value = max(self.min_val, min(value, self.max_val))
        self._update_display()


class EqBandControl(BaseControl):
    """
    A single equaliser band with frequency label and adjustable value.
    """

    signals = ['changed']

    def __init__(self, band_index, label, initial=0.0):
        self.band_index = band_index
        self.band_value = initial
        self._indicator = urwid.Text(('dim', '  '))
        self._freq_w = urwid.Text(('dim', f'{label:>4}'))
        self._val_w = urwid.Text(('value', f'{self.band_value:+.1f}'), align='right')
        self._bar_w = urwid.Text(make_bar(self.band_value + 10.0, 20.0, width=16))
        cols = urwid.Columns(
            [
                (urwid.GIVEN, 2, self._indicator),
                (urwid.GIVEN, 5, self._freq_w),
                (urwid.GIVEN, 6, self._val_w),
                (urwid.GIVEN, 1, urwid.Text(' ')),
                (urwid.GIVEN, 16, self._bar_w),
            ],
            dividechars=0,
        )
        super().__init__(cols)

    def _update_display(self):
        self._val_w.set_text(('value', f'{self.band_value:+.1f}'))
        self._bar_w.set_text(make_bar(self.band_value + 10.0, 20.0, width=16))

    def keypress(self, size, key):
        """
        Handle left/right and h/l for band adjustment.
        """
        if key in ('right', 'l', '+'):
            old = self.band_value
            self.band_value = min(self.band_value + 0.5, 10.0)
            if self.band_value != old:
                self._update_display()
                urwid.emit_signal(self, 'changed', self.band_index, self.band_value)
            return None
        if key in ('left', 'h', '-'):
            old = self.band_value
            self.band_value = max(self.band_value - 0.5, -10.0)
            if self.band_value != old:
                self._update_display()
                urwid.emit_signal(self, 'changed', self.band_index, self.band_value)
            return None
        return key

    def set_value(self, value):
        """
        Programmatically set the band value.
        """
        self.band_value = max(-10.0, min(value, 10.0))
        self._update_display()


class OptionControl(BaseControl):
    """
    A labelled selector for a small fixed set of named options.

    Cycle with h/l or left/right.
    """

    signals = ['changed']

    def __init__(self, label, options, initial=0, control_id=''):
        self.options = options  # list of (value, display_name) tuples
        self.current = initial
        self.control_id = control_id
        self._user_set = False
        self._label_text = label
        self._indicator = urwid.Text(('dim', '  '))
        self._label_w = urwid.Text(('dim', label))
        self._options_w = urwid.Text(self._options_markup())
        cols = urwid.Columns(
            [
                (urwid.GIVEN, 2, self._indicator),
                (urwid.GIVEN, 28, self._label_w),
                (urwid.GIVEN, 7, urwid.Text('')),
                (urwid.PACK, self._options_w),
            ],
            dividechars=0,
        )
        super().__init__(cols)

    def _options_markup(self):
        parts = []
        for i, (_, name) in enumerate(self.options):
            if i == self.current:
                attr = 'accent_bold' if self._user_set else 'dim'
                parts.append((attr, f'[{name}]'))
            else:
                parts.append(('dim', f' {name} '))
            parts.append(('default', ' '))
        return parts

    def _update_display(self):
        label_attr = 'default' if self._user_set else 'dim'
        self._label_w.set_text((label_attr, self._label_text))
        self._options_w.set_text(self._options_markup())

    def keypress(self, size, key):
        if key in ('right', 'l'):
            old = self.current
            self.current = min(self.current + 1, len(self.options) - 1)
            if self.current != old:
                self._user_set = True
                self._update_display()
                value, _ = self.options[self.current]
                urwid.emit_signal(self, 'changed', self.control_id, value)
            return None
        if key in ('left', 'h'):
            old = self.current
            self.current = max(self.current - 1, 0)
            if self.current != old:
                self._user_set = True
                self._update_display()
                value, _ = self.options[self.current]
                urwid.emit_signal(self, 'changed', self.control_id, value)
            return None
        return key


class ToggleControl(BaseControl):
    """
    A labelled toggle switch showing [ON]/[OFF].
    """

    signals = ['changed']

    def __init__(self, label, initial=False, control_id=''):
        self.state = initial
        self.control_id = control_id
        self._user_set = False
        self._label_text = label
        self._indicator = urwid.Text(('dim', '  '))
        self._label_w = urwid.Text(('dim', label))
        self._toggle_w = urwid.Text(self._toggle_markup())
        cols = urwid.Columns(
            [
                (urwid.GIVEN, 2, self._indicator),
                (urwid.GIVEN, 28, self._label_w),
                (urwid.GIVEN, 7, urwid.Text('')),
                (urwid.GIVEN, 5, self._toggle_w),
            ],
            dividechars=0,
        )
        super().__init__(cols)

    def _toggle_markup(self):
        if not self._user_set:
            return ('dim', ' [ON]' if self.state else '[OFF]')
        if self.state:
            return ('toggle_on', ' [ON]')
        return ('toggle_off', '[OFF]')

    def _update_display(self):
        """
        Refresh the toggle display.
        """
        label_attr = 'default' if self._user_set else 'dim'
        self._label_w.set_text((label_attr, self._label_text))
        self._toggle_w.set_text(self._toggle_markup())

    def keypress(self, size, key):
        """
        Handle enter/space to toggle.
        """
        if key in ('enter', ' '):
            self.state = not self.state
            self._user_set = True
            self._update_display()
            urwid.emit_signal(self, 'changed', self.control_id, self.state)
            return None
        return key


class PresetSelector(BaseControl):
    """
    EQ preset selector supporting number keys and h/l cycling.
    """

    signals = ['changed']

    def __init__(self, presets: dict[int, str], initial: int = 0):
        self._presets = presets
        self._sorted_keys = sorted(presets.keys())
        self.current = initial
        self._indicator = urwid.Text(('dim', '  '))
        self._text_w = urwid.Text(self._markup())
        cols = urwid.Columns(
            [
                (urwid.GIVEN, 2, self._indicator),
                (urwid.PACK, self._text_w),
            ],
            dividechars=0,
        )
        super().__init__(cols)

    def _markup(self) -> list[str | tuple[Hashable, str]]:
        parts: list[str | tuple[Hashable, str]] = [('default', 'Preset: ')]
        for idx in self._sorted_keys:
            name = self._presets[idx]
            if idx == self.current:
                parts.append(('accent_bold', f'[{name}]'))
            else:
                parts.append(('dim', f' {name} '))
            parts.append(('default', ' '))
        return parts

    def _update_display(self):
        """
        Refresh the preset display.
        """
        self._text_w.set_text(self._markup())

    def select(self, preset_num):
        """
        Select a preset by number.
        """
        if preset_num in self._presets:
            self.current = preset_num
            self._update_display()
            urwid.emit_signal(self, 'changed', preset_num)

    def keypress(self, size, key):
        """
        Handle left/right cycling and number key selection.
        """
        if key in ('right', 'l'):
            cur_idx = self._sorted_keys.index(self.current)
            next_idx = (cur_idx + 1) % len(self._sorted_keys)
            self.select(self._sorted_keys[next_idx])
            return None
        if key in ('left', 'h'):
            cur_idx = self._sorted_keys.index(self.current)
            prev_idx = (cur_idx - 1) % len(self._sorted_keys)
            self.select(self._sorted_keys[prev_idx])
            return None
        if key.isdigit() and 1 <= int(key) <= len(self._presets):
            self.select(int(key) - 1)
            return None
        return key


class EqHeader(urwid.WidgetWrap):
    """
    Equaliser section header.

    Selectable only when collapsed — triggers auto-expand via on_focus
    callback when it receives focus. Non-selectable when expanded so
    navigation skips straight past it.
    """

    def __init__(self, text, on_focus=None):
        self._text_w = urwid.Text(text)
        self._on_focus = on_focus
        self._last_focus: bool | None = None
        self._selectable = True
        super().__init__(self._text_w)
        # Override WidgetWrap.keypress to never consume keys
        self.keypress = lambda size, key: key  # type: ignore[method-assign]

    def selectable(self):
        return self._selectable

    def set_selectable(self, selectable):
        self._selectable = selectable

    def set_text(self, text):
        self._text_w.set_text(text)

    def render(self, size, focus=False):
        if focus and focus != self._last_focus and self._on_focus is not None:
            self._on_focus()
        self._last_focus = focus
        return super().render(size, focus)


class ApplyButton(BaseControl):
    """
    A simple button widget for applying custom EQ.
    """

    signals = ['click']

    def __init__(self, label):
        self._indicator = urwid.Text(('dim', '  '))
        self._text_w = urwid.Text(('accent', f'[ {label} ]'))
        cols = urwid.Columns(
            [
                (urwid.GIVEN, 2, self._indicator),
                (urwid.PACK, self._text_w),
            ],
            dividechars=0,
        )
        super().__init__(cols)

    def keypress(self, size, key):
        if key in ('enter', ' '):
            urwid.emit_signal(self, 'click')
            return None
        return key


# Register signals for all custom widgets
urwid.register_signal(NumericControl, ['changed'])
urwid.register_signal(EqBandControl, ['changed'])
urwid.register_signal(OptionControl, ['changed'])
urwid.register_signal(ToggleControl, ['changed'])
urwid.register_signal(PresetSelector, ['changed'])
urwid.register_signal(ApplyButton, ['click'])


class HeadsetTUI:
    """
    TUI for controlling a SteelSeries headset.

    Detects the connected device at startup and only builds controls
    for capabilities the device supports.
    """

    def __init__(self):
        self._last_state = None
        self._loop = None
        self._device_name, self._product_id, self._capabilities = detect_device()
        self._build_ui()

    def _has_cap(self, cap):
        """
        Check whether the connected device supports the given capability.
        """
        return cap in self._capabilities

    def _build_ui(self):
        """
        Construct the full urwid widget tree.

        All controls are placed in a single flat ListBox so that
        up/down/j/k navigation moves naturally between every control.
        Section headers are non-selectable Text widgets.
        Only controls supported by the detected device are included.
        """
        # Status bar
        self._status_device = urwid.Text(('heading', self._device_name))
        self._status_battery = urwid.Text(('default', 'Battery: --'))
        self._status_chatmix = None
        self._status_disconnected = urwid.Text(('disconnected', ''))
        status_cols = [
            (urwid.PACK, self._status_device),
            (urwid.GIVEN, 2, urwid.Text('')),
            (urwid.PACK, self._status_battery),
            (urwid.GIVEN, 2, urwid.Text('')),
        ]
        if self._has_cap('CAP_CHATMIX'):
            self._status_chatmix = urwid.Text(('default', 'Chatmix: --'))
            status_cols.append((urwid.PACK, self._status_chatmix))
            status_cols.append((urwid.GIVEN, 2, urwid.Text('')))
        status_cols.append((urwid.PACK, self._status_disconnected))
        status_bar = urwid.Columns(status_cols)

        # Audio controls
        def pct128(v):
            return f'{round(v / 128 * 100)}%'

        # Devices with stepped sidetone (0-3: off/low/med/high)
        _STEPPED_SIDETONE_DEVICES = {PID_ARCTIS_NOVA_PRO_WIRELESS}

        self._sidetone = None
        if self._has_cap('CAP_SIDETONE'):
            if self._product_id in _STEPPED_SIDETONE_DEVICES:
                self._sidetone = OptionControl(
                    'Sidetone',
                    [(0, 'Off'), (1, 'Low'), (2, 'Med'), (3, 'High')],
                    initial=0,
                    control_id='sidetone',
                )
            else:
                self._sidetone = NumericControl(
                    'Sidetone',
                    0,
                    128,
                    8,
                    0,
                    'sidetone',
                    display_fmt=pct128,
                )
            urwid.connect_signal(self._sidetone, 'changed', self._on_control_changed)

        # Lights control
        self._lights = None
        if self._has_cap('CAP_LIGHTS'):
            self._lights = ToggleControl(
                'Lights',
                initial=True,
                control_id='lights',
            )
            urwid.connect_signal(self._lights, 'changed', self._on_toggle_changed)

        # Equaliser controls
        self._has_eq = self._has_cap('CAP_EQUALIZER') or self._has_cap(
            'CAP_EQUALIZER_PRESET'
        )
        self._preset_selector = None
        self._eq_bands = []
        self._apply_btn = None
        self._all_presets: dict[int, str] = {}
        self._all_preset_values: dict[int, list[float]] = {}
        if self._has_eq:
            self._all_presets = dict(EQ_PRESETS)
            self._all_preset_values = dict(EQ_PRESET_VALUES)
            for idx, (name, values) in DEVICE_EQ_PRESETS.get(
                self._product_id, {}
            ).items():
                self._all_presets[idx] = name
                self._all_preset_values[idx] = values
            self._preset_selector = PresetSelector(presets=self._all_presets, initial=0)
            urwid.connect_signal(
                self._preset_selector, 'changed', self._on_preset_changed
            )
            for i, freq_label in enumerate(EQ_BAND_LABELS):
                band = EqBandControl(i, freq_label, initial=0.0)
                self._eq_bands.append(band)
            self._apply_btn = ApplyButton('Apply Custom EQ')
            urwid.connect_signal(self._apply_btn, 'click', self._on_apply_eq)

        # Microphone controls
        self._mic_vol = None
        if self._has_cap('CAP_MICROPHONE_VOLUME'):
            self._mic_vol = NumericControl(
                'Volume',
                0,
                128,
                8,
                128,
                'mic-vol',
                display_fmt=pct128,
            )
            urwid.connect_signal(self._mic_vol, 'changed', self._on_control_changed)

        self._mic_led = None
        if self._has_cap('CAP_MICROPHONE_MUTE_LED_BRIGHTNESS'):
            self._mic_led = OptionControl(
                'Mute LED Brightness',
                [(0, 'Off'), (1, 'Low'), (2, 'Med'), (3, 'High')],
                initial=3,
                control_id='mic-led',
            )
            urwid.connect_signal(self._mic_led, 'changed', self._on_control_changed)

        # Settings controls
        self._inactive = None
        if self._has_cap('CAP_INACTIVE_TIME'):
            self._inactive = NumericControl(
                'Inactive Time (min)',
                0,
                90,
                5,
                30,
                'inactive',
            )
            urwid.connect_signal(self._inactive, 'changed', self._on_control_changed)

        self._bt_call_vol = None
        if self._has_cap('CAP_BT_CALL_VOLUME'):
            self._bt_call_vol = OptionControl(
                'BT Call Ducking',
                [(0, 'Off'), (1, 'Medium'), (2, 'Max')],
                initial=0,
                control_id='bt-call-vol',
            )
            urwid.connect_signal(self._bt_call_vol, 'changed', self._on_control_changed)

        self._vol_limiter = None
        if self._has_cap('CAP_VOLUME_LIMITER'):
            self._vol_limiter = ToggleControl(
                'Volume Limiter',
                initial=True,
                control_id='volume-limiter',
            )
            urwid.connect_signal(self._vol_limiter, 'changed', self._on_toggle_changed)

        self._bt_powered = None
        if self._has_cap('CAP_BT_WHEN_POWERED_ON'):
            self._bt_powered = ToggleControl(
                'BT When Powered On',
                initial=False,
                control_id='bt-powered-on',
            )
            urwid.connect_signal(self._bt_powered, 'changed', self._on_toggle_changed)

        # Feedback line
        self._feedback = urwid.Text(('feedback', ''))

        # Help line — built dynamically based on available controls
        help_parts: list[str | tuple[Hashable, str]] = [
            ('heading', 'q'),
            ('default', ' Quit | '),
            ('heading', 'j/k/\u2191/\u2193'),
            ('default', ' Navigate | '),
            ('heading', 'h/l/\u2190/\u2192'),
            ('default', ' Adjust'),
        ]
        if self._has_eq:
            preset_count = len(self._all_presets)
            help_parts.extend(
                [
                    ('default', ' | '),
                    ('heading', 'e'),
                    ('default', ' Equaliser | '),
                    ('heading', f'1-{preset_count}'),
                    ('default', ' Preset | '),
                    ('heading', 'a'),
                    ('default', ' Apply EQ'),
                ]
            )
        help_text = urwid.Text(help_parts)

        # Build flat list of body items based on detected capabilities
        D = urwid.Divider

        # Collect all optional controls with dividers between them
        controls = []
        for ctrl in [
            self._sidetone,
            self._lights,
            self._mic_vol,
            self._mic_led,
            self._inactive,
            self._bt_call_vol,
            self._vol_limiter,
            self._bt_powered,
        ]:
            if ctrl is not None:
                if controls:
                    controls.append(D())
                controls.append(ctrl)

        # Equaliser section
        self._eq_collapsed = True
        self._eq_header = None
        self._eq_widgets = []
        if self._has_eq:
            self._eq_header = EqHeader(
                ('heading', '\u2500\u2500 Equaliser [e to expand] \u2500\u2500'),
                on_focus=self._on_eq_header_focus,
            )
            self._eq_widgets = [
                self._preset_selector,
                *self._eq_bands,
                self._apply_btn,
            ]

        self._build_body_items = lambda: [
            *controls,
            *(
                [D(), self._eq_header]
                + ([] if self._eq_collapsed else self._eq_widgets)
                if self._has_eq
                else []
            ),
        ]

        self._walker = urwid.SimpleFocusListWalker(self._build_body_items())
        body = VimListBox(self._walker)

        # Frame: status bar at top, feedback + help at bottom
        footer = urwid.Pile([self._feedback, help_text])
        self._frame = urwid.Frame(
            body=body,
            header=status_bar,
            footer=footer,
        )

    def _show_feedback(self, message, attr='feedback'):
        """
        Display a feedback message at the bottom.
        """
        self._feedback.set_text((attr, message))

    def _apply_setting(self, args, description):
        """
        Apply a headsetcontrol setting and show feedback.
        """
        ok, output = run_headsetcontrol(*args)
        if ok:
            self._show_feedback(f'Applied: {description}')
        else:
            self._show_feedback(f'Error: {output}', attr='error')

    _CONTROL_ARGS = {
        'sidetone': ('-s', 'sidetone'),
        'mic-vol': ('--microphone-volume', 'mic volume'),
        'inactive': ('-i', 'inactive time'),
        'mic-led': ('--microphone-mute-led-brightness', 'mic LED brightness'),
        'bt-call-vol': ('--bt-call-volume', 'BT call ducking'),
    }

    def _on_control_changed(self, control_id, value):
        if control_id in self._CONTROL_ARGS:
            flag, label = self._CONTROL_ARGS[control_id]
            self._apply_setting([flag, str(value)], f'{label} = {value}')

    def _on_preset_changed(self, preset_num):
        """
        Handle EQ preset selection.

        Hardware presets (0-3) are sent via -p. Software presets (4+) are
        sent via -e with comma-separated band values.
        """
        preset_name = self._all_presets.get(preset_num, str(preset_num))
        if preset_num in EQ_PRESETS:
            # Hardware preset — send via -p
            self._apply_setting(
                ['-p', str(preset_num)],
                f'EQ preset = {preset_name}',
            )
        elif preset_num in self._all_preset_values:
            # Software preset — send via -e
            values = self._all_preset_values[preset_num]
            eq_str = ','.join(str(v) for v in values)
            self._apply_setting(['-e', eq_str], f'EQ preset = {preset_name}')
        if preset_num in self._all_preset_values:
            values = self._all_preset_values[preset_num]
            for band in self._eq_bands:
                band.set_value(values[band.band_index])

    def _on_apply_eq(self):
        """
        Apply custom equaliser values.
        """
        eq_str = ','.join(str(band.band_value) for band in self._eq_bands)
        self._apply_setting(['-e', eq_str], f'custom EQ = {eq_str}')

    _TOGGLE_ARGS = {
        'lights': ('-l', 'lights'),
        'volume-limiter': ('--volume-limiter', 'volume limiter'),
        'bt-powered-on': ('--bt-when-powered-on', 'BT when powered on'),
    }

    def _on_toggle_changed(self, control_id, state):
        if control_id in self._TOGGLE_ARGS:
            flag, label = self._TOGGLE_ARGS[control_id]
            val = '1' if state else '0'
            self._apply_setting([flag, val], f'{label} = {"on" if state else "off"}')

    def _refresh_status(self, loop=None, data=None):
        """
        Fetch device state and update the status bar.

        Reschedules itself every second.
        """
        has_chatmix = self._has_cap('CAP_CHATMIX')
        state = read_device_state(has_chatmix=has_chatmix)
        # Extract comparable values to avoid redundant redraws
        if state is None:
            new_state = (False, -1, 64)
        else:
            bat = state.get('battery', {})
            new_state = (True, bat.get('level', -1), state.get('chatmix', 64))
        if new_state == self._last_state:
            if loop is not None:
                loop.set_alarm_in(1, self._refresh_status)
            return
        self._last_state = new_state
        connected, level, chatmix = new_state
        if not connected:
            self._status_battery.set_text(('default', 'Battery: --'))
            if self._status_chatmix is not None:
                self._status_chatmix.set_text(('default', 'Chatmix: --'))
            self._status_disconnected.set_text(('disconnected', 'DISCONNECTED'))
        else:
            self._status_disconnected.set_text(('default', ''))
            if level < 0:
                self._status_battery.set_text(('default', 'Battery: --'))
            else:
                icon = battery_icon(level)
                attr = battery_colour_attr(level)
                self._status_battery.set_text((attr, f'{icon} Battery: {level}%'))
            if self._status_chatmix is not None:
                if chatmix < 64:
                    bias = 'Game'
                elif chatmix > 64:
                    bias = 'Chat'
                else:
                    bias = 'Centre'
                self._status_chatmix.set_text(
                    ('default', f'Chatmix: {chatmix} ({bias})'),
                )
        # Schedule next refresh
        if loop is not None:
            loop.set_alarm_in(1, self._refresh_status)

    def _unhandled_input(self, key):
        """
        Handle global key bindings.
        """
        if key in ('q', 'Q'):
            raise urwid.ExitMainLoop()
        if self._has_eq:
            if key == 'e':
                self._toggle_eq_section()
                return True
            if key == 'a':
                self._on_apply_eq()
                return True
            if (
                key.isdigit()
                and 1 <= int(key) <= len(self._all_presets)
                and self._preset_selector is not None
            ):
                self._preset_selector.select(int(key) - 1)
                return True
        return False

    def _on_eq_header_focus(self):
        """
        Called when the EQ header receives focus.

        Defers expansion to after the current render completes,
        since modifying the walker mid-render causes urwid errors.
        Moves focus into the first EQ control after expanding.
        """
        if self._eq_collapsed and self._loop is not None:

            def _expand_and_focus(_loop, _data):
                self._expand_eq_section()
                if self._eq_widgets:
                    eq_start = self._walker.index(self._eq_header) + 1
                    self._walker.set_focus(eq_start)

            self._loop.set_alarm_in(0, _expand_and_focus)

    def _expand_eq_section(self):
        """
        Expand the equaliser section (no-op if already expanded).
        """
        if self._eq_header is None or not self._eq_collapsed:
            return
        self._eq_collapsed = False
        self._eq_header.set_selectable(False)
        self._eq_header.set_text(
            ('heading', '\u2500\u2500 Equaliser [e to collapse] \u2500\u2500')
        )
        eq_start = self._walker.index(self._eq_header) + 1
        for i, w in enumerate(self._eq_widgets):
            self._walker.insert(eq_start + i, w)

    def _collapse_eq_section(self):
        """
        Collapse the equaliser section (no-op if already collapsed).
        """
        if self._eq_header is None or self._eq_collapsed:
            return
        self._eq_collapsed = True
        self._eq_header.set_selectable(True)
        self._eq_header.set_text(
            ('heading', '\u2500\u2500 Equaliser [e to expand] \u2500\u2500')
        )
        eq_start = self._walker.index(self._eq_header) + 1
        del self._walker[eq_start : eq_start + len(self._eq_widgets)]

    def _toggle_eq_section(self):
        """
        Toggle the equaliser section between collapsed and expanded.

        Moves focus to the EQ header when collapsing, or to the first
        EQ control (preset selector) when expanding.
        """
        if self._eq_header is None:
            return
        if self._eq_collapsed:
            self._expand_eq_section()
            # Move focus to the first EQ control
            if self._eq_widgets:
                eq_start = self._walker.index(self._eq_header) + 1
                self._walker.set_focus(eq_start)
        else:
            self._collapse_eq_section()
            # Move focus to the nearest selectable control before the EQ header
            header_idx = self._walker.index(self._eq_header)
            idx = header_idx - 1
            while idx > 0 and not self._walker[idx].selectable():
                idx -= 1
            self._walker.set_focus(idx)

    def run(self):
        """
        Start the urwid main loop.
        """
        self._loop = urwid.MainLoop(
            self._frame,
            palette=PALETTE,
            unhandled_input=self._unhandled_input,
        )
        # Initial status fetch and schedule recurring refresh
        self._refresh_status(loop=self._loop)
        self._loop.run()


def main():
    app = HeadsetTUI()
    app.run()


if __name__ == '__main__':
    main()
