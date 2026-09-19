"""Constants for Probe-ability integration."""

DOMAIN = "probe_ability"

CONF_INTERNAL_SENSOR = "internal_sensor"
CONF_INTERNAL_SENSOR_2 = "internal_sensor_2"
CONF_INTERNAL_SENSOR_3 = "internal_sensor_3"
CONF_INTERNAL_SENSOR_4 = "internal_sensor_4"
CONF_AMBIENT_SENSOR = "ambient_sensor"

# Internal-probe config keys in probe order.  The first is required, the rest
# are optional.  A probe's index is its *slot* (internal_sensor_N → N-1), not
# its position among the keys that happen to be set: with probes 1 and 4
# configured, probe 4 is index 3 everywhere (entities, service calls, the
# card) and slots 2 and 3 are simply empty.
PROBE_SENSOR_KEYS = (
    CONF_INTERNAL_SENSOR,
    CONF_INTERNAL_SENSOR_2,
    CONF_INTERNAL_SENSOR_3,
    CONF_INTERNAL_SENSOR_4,
)
MAX_PROBES = len(PROBE_SENSOR_KEYS)

# Optional display names for the probes ("Green", "Red" …), one key per
# PROBE_SENSOR_KEYS slot.  Unset → the card and notifications say "Probe N".
CONF_PROBE_NAME = "probe_name"
CONF_PROBE_NAME_2 = "probe_name_2"
CONF_PROBE_NAME_3 = "probe_name_3"
CONF_PROBE_NAME_4 = "probe_name_4"
PROBE_NAME_KEYS = (
    CONF_PROBE_NAME,
    CONF_PROBE_NAME_2,
    CONF_PROBE_NAME_3,
    CONF_PROBE_NAME_4,
)

# Probe usage modes (set at cook-start time, not in config flow)
PROBE_MODE_INDIVIDUAL = "individual"
PROBE_MODE_COMBINED = "combined"

# Runtime attributes (set via service / card, not config flow)
ATTR_TARGET_TEMP = "target_temp"
ATTR_COOK_NAME = "cook_name"

# Services
SERVICE_START_COOK = "start_cook"
SERVICE_STOP_COOK = "stop_cook"
SERVICE_SET_TARGET = "set_target"

# Defaults
DEFAULT_TARGET_TEMP = 74.0
DEFAULT_COOK_NAME = "Cook"

# Minimum seconds between recorded readings (debounce)
MIN_READING_INTERVAL = 30

# Seconds after a sensor state event before evaluating auto-stop
AUTO_STOP_DELAY = 5

# Peak temps within this margin of target count as reached — typical meat
# probe accuracy is ±0.5°C, so a 53.5° peak against a 54° target is done.
TARGET_REACHED_TOLERANCE_C = 0.5

# Storage
STORAGE_VERSION = 1

# Temperature display unit (°C or °F) — stored in config entry, set once at setup
CONF_TEMP_UNIT = "temp_unit"
TEMP_UNIT_CELSIUS = "C"
TEMP_UNIT_FAHRENHEIT = "F"

# Data export (fine-tuning / analysis)
CONF_EXPORT_DATA = "export_cook_data"
EXPORT_SUBDIR = "probe_ability_exports"

# Anonymous cook sharing (opt-in)
CONF_SHARE_DATA = "share_cook_data"

# Supabase — anon key is intentionally public (INSERT-only via RLS)
SUPABASE_URL = "https://hlsfrqvfhtauoyhugyou.supabase.co"
SUPABASE_KEY = "sb_publishable_UaNANuzjnNgEP7wGaBARNg_lUbBrMjK"

# Companion-app Live Activities — list of notify service names (without the
# "notify." prefix), stored in entry.options via the options flow.
CONF_LIVE_ACTIVITY_TARGETS = "live_activity_targets"
# Minimum Home Assistant core version for the iOS Live Activity token handshake
LIVE_ACTIVITY_MIN_HA = (2026, 7)
