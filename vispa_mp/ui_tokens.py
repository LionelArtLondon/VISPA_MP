"""Review window tokens, copied from VISPA Cue so both tools share one scale.

Every number is in logical pixels. ``SCALE`` is the interface size (100 / 115 / 130 %),
read from VISPA_MP_UI_SCALE before the window is built. Views use these names.
"""

import os


def _scale():
    """Settings › Interface size (Lionel, 13 Nov 2026): 100, 115 or 130 %, read once when Cue starts."""
    try:
        value = float(os.environ.get('VISPA_MP_UI_SCALE', '1'))
    except ValueError:
        return 1.0
    return value if value in (1.0, 1.15, 1.3) else 1.0


SCALE = _scale()
INTERFACE_SIZES = (100, 115, 130)


def px(value):
    """A size in logical pixels, at the interface scale."""
    return max(1, round(value * SCALE))


# ---- text: three sizes, two exceptions, nothing under 12 px -------------------------------------------------------
TEXT_CONTENT = px(14)        # sound lines, track names, fields
TEXT_DIALOGUE = px(15)       # the Dialogue table's lines, a step larger (Lionel, 13 Nov 2026)
TEXT_SECONDARY = px(12)      # timecodes, counters, statuses, column headers, block labels
TEXT_TITLE = px(13)          # panel titles, semibold
TEXT_IMAGE_NUMBER = px(15)   # « Image 004 » in Lettering, semibold
TEXT_RYTHMO = px(19)         # the rythmo band: the largest text on screen
TEXT_RYTHMO_NAME = px(12)    # the speaker above a rythmo line, bold
TEXT_PROPOSAL = px(16)       # comic text proposals in Sounds, bold italic
TEXT_TRACK = px(13)          # timeline track names
TEXT_MINIMUM = px(12)
MONO_FAMILY = 'Consolas'     # timecodes: tabular figures that never move
TEXT_FAMILY = 'Segoe UI'

# ---- controls: two heights ------------------------------------------------------------------------------------------
CONTROL = px(28)             # buttons, drop-down lists, fields, icon buttons (28 × 28)
ROW_PLAY = px(24)            # the small play buttons in list rows (24 × 24)
ICON = px(16)                # an icon in a button
RADIUS = px(4)

# ---- window structure ---------------------------------------------------------------------------------------------
HEADER_HEIGHT = px(44)
FOOTER_HEIGHT = px(36)
TOOL_COLUMN = px(44)
TOOL_GAP = px(6)
TOOL_GROUP_GAP = px(14)
THUMBNAIL = px(28)
PART_SELECTOR_WIDTH = px(520)
PART_SELECTOR_MINIMUM = px(160)
PANEL_TITLE = px(30)
PANEL_BUTTON = px(22)
SEPARATOR_LINE = px(3)       # the visible line between panels
SEPARATOR_GRAB = px(8)       # the zone the pointer can take
LIST_HEADER = px(28)
LIST_ROW = px(34)
FILTER_ROW = px(40)
LETTERING_INFO = px(170)
LETTERING_STRIP = px(150)
LETTERING_ARROW_GAP = px(8)
TRACK_HEADER = px(150)       # the timeline's column of track names
TRACK_FOLD = px(16)          # the fold arrow, in a click zone of at least 24 px
TRACK_FOLD_ZONE = px(24)
TRACK_BLOCK = px(26)         # a block on a timeline track
TRACK_BLOCK_RADIUS = px(3)
TRACK_MINIMUM = dict(images=px(46), sound=px(40), dialogue=px(34), vocal=px(34), effect=px(34), uncertain=px(34))
SOUND_SELECTOR_WIDTH = px(230)
# In Compare, each half's header has room for the whole name: « … · Oscar V2 · 17 proposals · 12 set aside ».
COMPARE_SELECTOR_WIDTH = px(460)
SEARCH_WIDTH = px(150)
CHARACTER_WIDTH = px(150)

# ---- colours (the mock-up's palette, in the spirit of Cue's dark theme) --------------------------------------------
APP_BG = '#081820'
PANEL_BG = '#102631'
PANEL_TITLE_BG = '#1C3E4B'
BAR_BG = '#0E232C'           # header and status bar
TOOL_BG = '#0B1D25'
COLUMN_HEADER_BG = '#0D212A'
BORDER_STRONG = '#3A6A7A'
BORDER_ROW = '#1F4250'
SEPARATOR = '#5A97A9'
TEXT_MAIN = '#E8F2F5'
TEXT_MUTED = '#A3BCC5'
ACCENT = '#2FD0C0'
PRIMARY_BG = '#1FB5A7'
PRIMARY_TEXT = '#04201D'
SELECTED_ROW = '#175460'
ACCEPT_BORDER, ACCEPT_TEXT = '#46C486', '#8BE6B6'
REJECT_BORDER, REJECT_TEXT = '#E08173', '#F5B0A6'
PLAYHEAD = '#FF8A5C'
CONTROL_BG = '#17323E'
CONTROL_HOVER = '#20525C'
# Timeline blocks, one colour per track, different in lightness as well as hue.
TRACK_COLOURS = dict(dialogue=('#5D4FC4', '#FFFFFF', None), vocal=('#E7B3DD', '#2A0F25', None),
                     effect=('#1C7F7A', '#FFFFFF', None), uncertain=(None, '#D5E6EB', '#9FB8C1'))


def contrast(foreground, background):
    """WCAG contrast ratio between two #rrggbb colours."""
    def luminance(colour):
        channels = [int(colour[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
        return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]
    high, low = sorted((luminance(foreground), luminance(background)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def window_stylesheet():
    """The Transcribe window's own rules, added after the theme's: sizes and colours from the tokens above."""
    inner = CONTROL - 2                       # QSS heights exclude the 1 px border on each side
    return f"""
QDialog, QStackedWidget, .QWidget {{ background: {APP_BG}; }}
QWidget {{ font-family: '{TEXT_FAMILY}'; font-size: {TEXT_CONTENT}px; color: {TEXT_MAIN}; }}
QPushButton, QToolButton, QComboBox {{ background: {CONTROL_BG}; border: 1px solid {BORDER_STRONG};
    border-radius: {RADIUS}px; padding: 0 10px; min-height: {inner}px; max-height: {inner}px; }}
QPushButton:hover, QToolButton:hover, QComboBox:hover {{ background: {CONTROL_HOVER}; border-color: {ACCENT}; }}
QPushButton:disabled, QToolButton:disabled, QComboBox:disabled {{ color: {TEXT_MUTED}; background: #10232c;
    border-color: #1f3a46; }}
QComboBox {{ padding: 0 4px 0 10px; }}
QLineEdit {{ background: {APP_BG}; border: 1px solid {BORDER_STRONG}; border-radius: {RADIUS}px; padding: 0 8px;
    min-height: {inner}px; max-height: {inner}px; }}
QComboBox QLineEdit {{ border: 0; padding: 0; min-height: 0; max-height: 16777215px; }}
QPushButton[primary="true"], QToolButton[primary="true"] {{ background: {PRIMARY_BG}; border-color: {PRIMARY_BG};
    color: {PRIMARY_TEXT}; font-weight: 600; }}
QPushButton[primary="true"]:hover, QToolButton[primary="true"]:hover {{ background: {ACCENT}; border-color: {ACCENT};
    color: {PRIMARY_TEXT}; }}
QPushButton[primary="true"]:disabled, QToolButton[primary="true"]:disabled {{ background: #10232c;
    border-color: #1f3a46; color: {TEXT_MUTED}; }}
QPushButton[quiet="true"] {{ background: transparent; color: {TEXT_MUTED}; }}
QHeaderView::section {{ background: {COLUMN_HEADER_BG}; color: {TEXT_MUTED}; font-size: {TEXT_SECONDARY}px;
    font-weight: 500; padding: 0 8px; min-height: {LIST_HEADER}px; max-height: {LIST_HEADER}px; border: 0;
    border-bottom: 1px solid {BORDER_STRONG}; }}
QTableWidget, QTableView, QListView, QTreeView {{ background: {PANEL_BG}; }}
QTableWidget::item:selected, QTableView::item:selected {{ background: {SELECTED_ROW}; color: #ffffff; }}
QMenu {{ font-size: {TEXT_CONTENT}px; }}
QToolTip {{ font-size: {TEXT_SECONDARY + 1}px; }}
QCheckBox {{ font-size: {TEXT_CONTENT}px; }}
"""
