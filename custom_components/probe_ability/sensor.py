"""Sensor entities for Probe-ability."""

from __future__ import annotations

from datetime import datetime, timezone

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_INTERNAL_SENSOR_2, CONF_INTERNAL_SENSOR_3, DOMAIN, PROBE_MODE_COMBINED


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up sensor entities — one pair (time remaining + ETA) per configured probe."""
    monitor = hass.data[DOMAIN][entry.entry_id]
    probe_count = len(monitor.predictors)

    entities: list[SensorEntity] = []
    for i in range(probe_count):
        tr = CookTimeRemainingSensor(monitor, entry, probe_index=i)
        eta = CookETASensor(monitor, entry, probe_index=i)
        entities.extend([tr, eta])
        monitor.register_entity(tr)
        monitor.register_entity(eta)

    async_add_entities(entities)


# Suffix used in unique_id / name for probes 1 and 2 (probe 0 has no suffix)
_PROBE_SUFFIX = {0: "", 1: "_2", 2: "_3"}
_PROBE_LABEL = {0: "", 1: " (probe 2)", 2: " (probe 3)"}

# Carryover cooking constants
_CARRYOVER_FACTOR = 5.0   # °C of carryover per °C/min of heating rate
_MIN_CARRYOVER = 3.0      # °C — minimum assumed carryover
_MAX_CARRYOVER = 10.0     # °C — maximum assumed carryover


def _pull_temp(target_temp: float, rate_per_minute: float | None) -> float | None:
    """Return the temperature at which meat should be pulled from heat.

    Based on the current heating rate, we estimate how much the internal
    temperature will continue to rise (carryover cooking) after the heat
    source is removed.  Pull the meat when it reaches target minus that
    estimated carryover so it coasts up to the intended serving temperature.
    """
    if rate_per_minute is None or rate_per_minute <= 0:
        return None
    carryover = min(max(rate_per_minute * _CARRYOVER_FACTOR, _MIN_CARRYOVER), _MAX_CARRYOVER)
    return round(target_temp - carryover, 1)


class CookPredictorSensorBase(SensorEntity):
    """Base class for cook predictor sensors."""

    _attr_has_entity_name = True

    def __init__(self, monitor, entry: ConfigEntry, probe_index: int = 0) -> None:
        self._monitor = monitor
        self._entry = entry
        self._probe_index = probe_index

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._entry.entry_id)},
            "name": "Probe-ability",
            "manufacturer": "Probe-ability",
            "model": "Predictive Thermometer",
        }

    @property
    def available(self) -> bool:
        """Available whenever this probe (or any probe, for probe 0) is active.

        The primary sensor (probe 0) carries ALL cross-probe attributes used by
        the Lovelace card.  It must stay available as long as ANY probe is
        running — otherwise HA strips its attributes and the card can't see the
        per-probe state of probes 1 and 2 after probe 0 has been stopped.

        Secondary sensors (probes 1/2) only need to be available while their
        own probe is active.
        """
        if self._probe_index >= len(self._monitor.predictors):
            return False
        if self._probe_index == 0:
            return self._monitor.active   # True if any probe is running
        return self._monitor.probe_active[self._probe_index]


class CookTimeRemainingSensor(CookPredictorSensorBase):
    """Sensor showing estimated minutes remaining for one probe."""

    _attr_native_unit_of_measurement = UnitOfTime.MINUTES
    _attr_suggested_display_precision = 0
    _attr_icon = "mdi:timer-outline"

    def __init__(self, monitor, entry: ConfigEntry, probe_index: int = 0) -> None:
        super().__init__(monitor, entry, probe_index)
        suffix = _PROBE_SUFFIX.get(probe_index, f"_{probe_index + 1}")
        label = _PROBE_LABEL.get(probe_index, f" (probe {probe_index + 1})")
        self._attr_unique_id = f"{entry.entry_id}_time_remaining{suffix}"
        self._attr_name = f"Time remaining{label}"

    @property
    def native_value(self) -> float | None:
        if self._probe_index >= len(self._monitor.predictors):
            return None
        if not self._monitor.probe_active[self._probe_index]:
            return None

        # In combined mode the primary sensor (probe 0) drives the shared timer.
        # Use the slowest active probe so the ETA reflects when *all* probes
        # will reach target, not just the fastest one.
        if self._probe_index == 0 and self._monitor.probe_mode == PROBE_MODE_COMBINED:
            return self._combined_time_remaining()

        result = self._monitor.predictors[self._probe_index].predict()
        if result.phase == "collecting":
            return None
        if result.time_remaining_seconds is not None:
            return round(result.time_remaining_seconds / 60, 1)
        return None

    def _combined_time_remaining(self) -> float | None:
        """Return the maximum time remaining across all active, non-stale probes.

        A probe is considered stale if no reading has been received in the last
        5 minutes — this prevents a frozen sensor from locking the combined ETA.
        """
        import time as _time
        now = _time.time()
        _STALE_THRESHOLD = 300  # seconds — 5 minutes

        values: list[float] = []
        for i, (active, predictor) in enumerate(
            zip(self._monitor.probe_active, self._monitor.predictors)
        ):
            if not active:
                continue
            last_ts = self._monitor._last_reading_ts[i]
            if last_ts > 0 and (now - last_ts) > _STALE_THRESHOLD:
                continue
            result = predictor.predict()
            if result.phase in ("collecting", "done"):
                continue
            if result.time_remaining_seconds is not None:
                values.append(result.time_remaining_seconds)

        if not values:
            return None
        return round(max(values) / 60, 1)

    @property
    def extra_state_attributes(self) -> dict:
        idx = self._probe_index
        predictors = self._monitor.predictors

        attrs: dict = {
            # For the primary sensor "active" reflects the whole session so
            # the card stays in the active/individual view even after probe 0
            # itself has been stopped while other probes are still running.
            "active": (
                self._monitor.active
                if idx == 0
                else (self._monitor.probe_active[idx] if idx < len(predictors) else False)
            ),
            "probe_index": idx,
            "probe_mode": self._monitor.probe_mode,
            "probe_count": len(predictors),
            "probe_active": list(self._monitor.probe_active),
        }

        if idx >= len(predictors):
            return attrs

        # Non-primary probes: return early when their own probe is inactive
        if idx > 0 and not self._monitor.probe_active[idx]:
            return attrs

        # Nothing active at all — nothing more to add
        if not self._monitor.active:
            return attrs

        # Add this probe's own prediction data (only when it's personally active)
        if self._monitor.probe_active[idx]:
            predictor = predictors[idx]
            result = predictor.predict()

            attrs.update(
                {
                    "phase": result.phase,
                    "confidence": result.confidence,
                    "target_temp": predictor.target_temp,
                    "readings_count": len(predictor.readings),
                }
            )
            if result.rate_per_minute is not None:
                attrs["rate_c_per_minute"] = round(result.rate_per_minute, 3)
            if result.message:
                attrs["message"] = result.message
            if predictor.current_temp is not None:
                attrs["current_temp"] = round(predictor.current_temp, 1)
            if predictor.current_ambient is not None:
                attrs["ambient_temp"] = round(predictor.current_ambient, 1)

            # Pull-from-heat temperature
            pull = _pull_temp(predictor.target_temp, result.rate_per_minute)
            if pull is not None:
                attrs["pull_temp"] = pull

        # For the primary sensor (probe 0), always include cross-probe data so
        # the card can render all probe slots regardless of probe 0's own state.
        if idx == 0:
            for extra_i in range(1, len(predictors)):
                n = extra_i + 1  # human-readable probe number (2 or 3)
                extra_pred = predictors[extra_i]
                extra_active = self._monitor.probe_active[extra_i]

                if extra_pred.current_temp is not None:
                    attrs[f"current_temp_{n}"] = round(extra_pred.current_temp, 1)
                attrs[f"target_temp_{n}"] = extra_pred.target_temp
                attrs[f"probe_{n}_active"] = extra_active

                if extra_active:
                    extra_result = extra_pred.predict()
                    attrs[f"probe_{n}_phase"] = extra_result.phase
                    attrs[f"probe_{n}_confidence"] = extra_result.confidence
                    attrs[f"probe_{n}_readings_count"] = len(extra_pred.readings)
                    if extra_result.rate_per_minute is not None:
                        attrs[f"probe_{n}_rate_c_per_minute"] = round(extra_result.rate_per_minute, 3)
                    if extra_result.time_remaining_seconds is not None:
                        attrs[f"probe_{n}_time_remaining"] = round(
                            extra_result.time_remaining_seconds / 60, 1
                        )
                    extra_pull = _pull_temp(extra_pred.target_temp, extra_result.rate_per_minute)
                    if extra_pull is not None:
                        attrs[f"probe_{n}_pull_temp"] = extra_pull

        return attrs


class CookETASensor(CookPredictorSensorBase):
    """Sensor showing estimated completion time for one probe."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:clock-check-outline"

    def __init__(self, monitor, entry: ConfigEntry, probe_index: int = 0) -> None:
        super().__init__(monitor, entry, probe_index)
        suffix = _PROBE_SUFFIX.get(probe_index, f"_{probe_index + 1}")
        label = _PROBE_LABEL.get(probe_index, f" (probe {probe_index + 1})")
        self._attr_unique_id = f"{entry.entry_id}_eta{suffix}"
        self._attr_name = f"Estimated completion{label}"

    @property
    def native_value(self) -> datetime | None:
        if self._probe_index >= len(self._monitor.predictors):
            return None
        if not self._monitor.probe_active[self._probe_index]:
            return None
        result = self._monitor.predictors[self._probe_index].predict()
        if result.phase == "collecting":
            return None
        if result.eta_timestamp is not None:
            return datetime.fromtimestamp(result.eta_timestamp, tz=timezone.utc)
        return None
