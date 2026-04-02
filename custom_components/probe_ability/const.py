"""Constants for Probe-ability integration."""

DOMAIN = "probe_ability"

CONF_INTERNAL_SENSOR = "internal_sensor"
CONF_INTERNAL_SENSOR_2 = "internal_sensor_2"
CONF_INTERNAL_SENSOR_3 = "internal_sensor_3"
CONF_AMBIENT_SENSOR = "ambient_sensor"

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

# Storage
STORAGE_VERSION = 1

# Data export (fine-tuning / analysis)
CONF_EXPORT_DATA = "export_cook_data"
EXPORT_SUBDIR = "probe_ability_exports"
