"""
TUI application for controlling a SteelSeries Arctis Nova 7 headset.

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


def read_device_state():
    """
    Query headsetcontrol for the current device state.

    Returns the first device dict from JSON output, or None on failure.
    """
    ok, output = run_headsetcontrol('-o', 'json', '-b', '-m')
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
    EQ preset selector supporting 1-4 number keys and h/l cycling.
    """

    signals = ['changed']

    def __init__(self, initial=0):
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
        for idx, name in EQ_PRESETS.items():
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
        if preset_num in EQ_PRESETS:
            self.current = preset_num
            self._update_display()
            urwid.emit_signal(self, 'changed', preset_num)

    def keypress(self, size, key):
        """
        Handle left/right cycling and number key selection.
        """
        if key in ('right', 'l'):
            self.select((self.current + 1) % len(EQ_PRESETS))
            return None
        if key in ('left', 'h'):
            self.select((self.current - 1) % len(EQ_PRESETS))
            return None
        if key in ('1', '2', '3', '4'):
            self.select(int(key) - 1)
            return None
        return key


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
    TUI for controlling a SteelSeries Arctis Nova 7 headset.
    """

    def __init__(self):
        self._last_state = None
        self._build_ui()

    def _build_ui(self):
        """
        Construct the full urwid widget tree.

        All controls are placed in a single flat ListBox so that
        up/down/j/k navigation moves naturally between every control.
        Section headers are non-selectable Text widgets.
        """
        # Status bar
        self._status_device = urwid.Text(('heading', 'Arctis Nova 7'))
        self._status_battery = urwid.Text(('default', 'Battery: --'))
        self._status_chatmix = urwid.Text(('default', 'Chatmix: --'))
        self._status_disconnected = urwid.Text(('disconnected', ''))
        status_bar = urwid.Columns(
            [
                (urwid.PACK, self._status_device),
                (urwid.GIVEN, 2, urwid.Text('')),
                (urwid.PACK, self._status_battery),
                (urwid.GIVEN, 2, urwid.Text('')),
                (urwid.PACK, self._status_chatmix),
                (urwid.GIVEN, 2, urwid.Text('')),
                (urwid.PACK, self._status_disconnected),
            ]
        )

        # Audio controls
        def pct128(v):
            return f'{round(v / 128 * 100)}%'

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

        # Equaliser controls
        self._preset_selector = PresetSelector(initial=0)
        urwid.connect_signal(self._preset_selector, 'changed', self._on_preset_changed)

        self._eq_bands = []
        for i, freq_label in enumerate(EQ_BAND_LABELS):
            band = EqBandControl(i, freq_label, initial=0.0)
            self._eq_bands.append(band)

        self._apply_btn = ApplyButton('Apply Custom EQ')
        urwid.connect_signal(self._apply_btn, 'click', self._on_apply_eq)

        # Microphone controls
        self._mic_vol = NumericControl(
            'Volume',
            0,
            128,
            8,
            128,
            'mic-vol',
            display_fmt=pct128,
        )
        self._mic_led = OptionControl(
            'Mute LED Brightness',
            [(0, 'Off'), (1, 'Low'), (2, 'Med'), (3, 'High')],
            initial=3,
            control_id='mic-led',
        )
        urwid.connect_signal(self._mic_vol, 'changed', self._on_control_changed)
        urwid.connect_signal(self._mic_led, 'changed', self._on_control_changed)

        # Settings controls
        self._inactive = NumericControl(
            'Inactive Time (min)',
            0,
            90,
            5,
            30,
            'inactive',
        )
        self._bt_call_vol = OptionControl(
            'BT Call Ducking',
            [(0, 'Off'), (1, 'Medium'), (2, 'Max')],
            initial=0,
            control_id='bt-call-vol',
        )
        self._vol_limiter = ToggleControl(
            'Volume Limiter',
            initial=True,
            control_id='volume-limiter',
        )
        self._bt_powered = ToggleControl(
            'BT When Powered On',
            initial=False,
            control_id='bt-powered-on',
        )
        urwid.connect_signal(self._inactive, 'changed', self._on_control_changed)
        urwid.connect_signal(self._bt_call_vol, 'changed', self._on_control_changed)
        urwid.connect_signal(self._vol_limiter, 'changed', self._on_toggle_changed)
        urwid.connect_signal(self._bt_powered, 'changed', self._on_toggle_changed)

        # Feedback line
        self._feedback = urwid.Text(('feedback', ''))

        # Help line
        help_text = urwid.Text(
            [
                ('heading', 'q'),
                ('default', ' Quit | '),
                ('heading', 'j/k/↑/↓'),
                ('default', ' Navigate | '),
                ('heading', 'h/l/←/→'),
                ('default', ' Adjust | '),
                ('heading', 'e'),
                ('default', ' Equaliser | '),
                ('heading', '1-4'),
                ('default', ' Preset | '),
                ('heading', 'a'),
                ('default', ' Apply EQ'),
            ]
        )

        # Build flat list: section headers (non-selectable) + controls (selectable)
        def section_header(title):
            return urwid.Text(('heading', f'── {title} ──'))

        self._eq_collapsed = True
        self._eq_header = urwid.Text(('heading', '── Equaliser [e to expand] ──'))
        self._eq_widgets = [
            self._preset_selector,
            *self._eq_bands,
            self._apply_btn,
        ]

        D = urwid.Divider
        self._build_body_items = lambda: [
            urwid.Text(
                ('dim', 'Settings below cannot be read from device — defaults shown')
            ),
            D(),
            self._sidetone,
            D(),
            self._mic_vol,
            D(),
            self._mic_led,
            D(),
            self._inactive,
            D(),
            self._bt_call_vol,
            D(),
            self._vol_limiter,
            D(),
            self._bt_powered,
            D(),
            self._eq_header,
            *([] if self._eq_collapsed else self._eq_widgets),
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
        """
        self._apply_setting(
            ['-p', str(preset_num)],
            f'EQ preset = {EQ_PRESETS.get(preset_num, preset_num)}',
        )
        if preset_num in EQ_PRESET_VALUES:
            values = EQ_PRESET_VALUES[preset_num]
            for band in self._eq_bands:
                band.set_value(values[band.band_index])

    def _on_apply_eq(self):
        """
        Apply custom equaliser values.
        """
        eq_str = ','.join(str(band.band_value) for band in self._eq_bands)
        self._apply_setting(['-e', eq_str], f'custom EQ = {eq_str}')

    _TOGGLE_ARGS = {
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
        state = read_device_state()
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
        if key == 'e':
            self._toggle_eq_section()
            return True
        if key == 'a':
            self._on_apply_eq()
            return True
        if key in ('1', '2', '3', '4'):
            self._preset_selector.select(int(key) - 1)
            return True
        return False

    def _toggle_eq_section(self):
        """
        Toggle the equaliser section between collapsed and expanded.
        """
        self._eq_collapsed = not self._eq_collapsed
        if self._eq_collapsed:
            self._eq_header.set_text(('heading', '── Equaliser [e to expand] ──'))
        else:
            self._eq_header.set_text(('heading', '── Equaliser [e to collapse] ──'))
        eq_start = self._walker.index(self._eq_header) + 1
        if self._eq_collapsed:
            del self._walker[eq_start : eq_start + len(self._eq_widgets)]
        else:
            for i, w in enumerate(self._eq_widgets):
                self._walker.insert(eq_start + i, w)

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
