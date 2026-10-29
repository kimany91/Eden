"""Event IDs of the FLP format used by Eden.

The FLP format is undocumented. These IDs come from public reverse-engineering
work (notably the PyFLP project) and were each checked against a real
FL Studio 20.8 project before being used here. See docs/format-flp.md.
"""

from eden.flp.events import DATA, DWORD, TEXT, WORD

# Project-wide
PROJECT_FL_VERSION = TEXT + 7  # ASCII "20.8.4.2576"
PROJECT_FL_BUILD = DWORD + 31
PROJECT_TEMPO = DWORD + 28  # BPM * 1000
PROJECT_TEMPO_COARSE = WORD + 2  # legacy (< FL 3.4)
PROJECT_TEMPO_FINE = WORD + 29  # legacy
PROJECT_TITLE = TEXT + 2
PROJECT_COMMENTS = TEXT + 3
PROJECT_URL = TEXT + 5
PROJECT_DATA_PATH = TEXT + 10
PROJECT_GENRE = TEXT + 14
PROJECT_ARTISTS = TEXT + 15
PROJECT_TIMESTAMP = DATA + 29  # 2 x float64: created (Delphi date), time spent (days)
TIME_SIG_NUM = 17
TIME_SIG_BEAT = 18

# Channel rack
CHANNEL_NEW = WORD  # value = channel index
CHANNEL_ENABLED = 0
CHANNEL_TYPE = 21
CHANNEL_ROUTED_TO = 22  # signed: mixer insert index
CHANNEL_LOCKED = 32
CHANNEL_NAME_LEGACY = TEXT
CHANNEL_SAMPLE_PATH = TEXT + 4
CHANNEL_LEVELS = DATA + 11  # i32 pan, u32 volume, ...
CHANNEL_AUTOMATION = DATA + 26

CHANNEL_TYPES = {0: "sampler", 2: "native", 3: "layer", 4: "instrument", 5: "automation"}

# Plugins (shared by channels and mixer slots)
PLUGIN_INTERNAL_NAME = TEXT + 9
PLUGIN_NAME = TEXT + 11
PLUGIN_WRAPPER = DATA + 4
PLUGIN_DATA = DATA + 5

# Patterns
PATTERN_NEW = WORD + 1
PATTERN_NAME = TEXT + 1
PATTERN_LENGTH = DWORD + 36
PATTERN_NOTES = DATA + 16

# Arrangements / playlist
ARRANGEMENT_NEW = WORD + 35
ARRANGEMENTS_CURRENT = WORD + 36
ARRANGEMENT_NAME = TEXT + 49
ARRANGEMENT_PLAYLIST = DATA + 25
TRACK_DATA = DATA + 30
TRACK_NAME = TEXT + 47
TIMEMARKER_POSITION = DWORD + 20
TIMEMARKER_NAME = TEXT + 13

# Mixer
MIXER_PARAMS = DATA + 17
INSERT_NAME = TEXT + 12
INSERT_FLAGS = DATA + 28
INSERT_ROUTING = DATA + 27
INSERT_INPUT = DWORD + 26
INSERT_OUTPUT = DWORD + 19  # closes an insert
SLOT_INDEX = WORD + 34  # closes a mixer slot

# Mixer parameter record IDs inside MIXER_PARAMS
MP_SLOT_ENABLED = 0
MP_SLOT_MIX = 1
MP_ROUTE_LEVEL_FIRST = 64  # 64..191: send level to insert (id - 64)
MP_ROUTE_LEVEL_LAST = 191
MP_VOLUME = 192
MP_PAN = 193
MP_STEREO_SEP = 194

# Insert flag bits (second u32 of INSERT_FLAGS), verified on FL 20.8
INSERT_FLAG_POLARITY = 1 << 0
INSERT_FLAG_SWAP_LR = 1 << 1
INSERT_FLAG_EFFECTS_ON = 1 << 2
INSERT_FLAG_ENABLED = 1 << 3
INSERT_FLAG_LOCKED = 1 << 11

# Records inside the "Fruity Wrapper" plugin data (VST/VST3 hosting)
VST_FOURCC = 51
VST_GUID = 52
VST_STATE = 53
VST_NAME = 54
VST_PATH = 55
VST_VENDOR = 56

# Playlist items whose item index is above this value reference a pattern.
PATTERN_BASE = 20480

# Events whose payload is text in FL >= 11.5 (UTF-16LE)
TEXT_IDS_EXTRA = {ARRANGEMENT_NAME, TRACK_NAME, TEXT + 39}
