"""Probe-ability - Predictive meat thermometer for Home Assistant."""

from __future__ import annotations

__version__ = "1.0.0"

import logging
import time

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STOP, Platform
from homeassistant.core import Event, HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.storage import Store

from .const import (
    ATTR_COOK_NAME,
    ATTR_TARGET_TEMP,
    CONF_AMBIENT_SENSOR,
    CONF_EXPORT_DATA,
    CONF_INTERNAL_SENSOR,
    CONF_INTERNAL_SENSOR_2,
    CONF_INTERNAL_SENSOR_3,
    DEFAULT_COOK_NAME,
    DEFAULT_TARGET_TEMP,
    DOMAIN,
    EXPORT_SUBDIR,
    MIN_READING_INTERVAL,
    PROBE_MODE_COMBINED,
    PROBE_MODE_INDIVIDUAL,
    SERVICE_SET_TARGET,
    SERVICE_START_COOK,
    SERVICE_STOP_COOK,
    STORAGE_VERSION,
)
from .predictor import CookPredictor

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Probe-ability from a config entry."""
    monitor = CookMonitor(hass, entry)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = monitor

    await monitor.async_load()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_on_unload(
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, monitor.async_save)
    )

    # Register services (once for the domain)
    if not hass.services.has_service(DOMAIN, SERVICE_START_COOK):
        _register_services(hass)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    monitor: CookMonitor = hass.data[DOMAIN].pop(entry.entry_id)
    await monitor.async_save()
    monitor.async_stop()

    # Unregister services if no entries left
    if not hass.data.get(DOMAIN):
        for service in (SERVICE_START_COOK, SERVICE_STOP_COOK, SERVICE_SET_TARGET):
            hass.services.async_remove(DOMAIN, service)

    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


def _get_monitor(hass: HomeAssistant, entry_id: str) -> CookMonitor | None:
    """Look up a monitor by entry_id."""
    return hass.data.get(DOMAIN, {}).get(entry_id)


def _get_first_monitor(hass: HomeAssistant) -> CookMonitor | None:
    """Get the first (or only) monitor — convenience for single-instance setups."""
    monitors = hass.data.get(DOMAIN, {})
    if monitors:
        return next(iter(monitors.values()))
    return None


def _register_services(hass: HomeAssistant) -> None:
    """Register domain services."""

    async def handle_start_cook(call: ServiceCall) -> None:
        entry_id = call.data.get("entry_id")
        monitor = (
            _get_monitor(hass, entry_id) if entry_id else _get_first_monitor(hass)
        )
        if not monitor:
            _LOGGER.error("No Probe-ability instance found")
            return

        target = call.data.get(ATTR_TARGET_TEMP, DEFAULT_TARGET_TEMP)
        cook_name = call.data.get(ATTR_COOK_NAME, DEFAULT_COOK_NAME)
        probe_index = call.data.get("probe_index")
        probe_mode = call.data.get("probe_mode", PROBE_MODE_COMBINED)
        monitor.start_cook(
            target_temp=target,
            cook_name=cook_name,
            probe_index=probe_index,
            probe_mode=probe_mode,
        )

    async def handle_stop_cook(call: ServiceCall) -> None:
        entry_id = call.data.get("entry_id")
        monitor = (
            _get_monitor(hass, entry_id) if entry_id else _get_first_monitor(hass)
        )
        if not monitor:
            return
        probe_index = call.data.get("probe_index")
        monitor.stop_cook(probe_index=probe_index)

    async def handle_set_target(call: ServiceCall) -> None:
        entry_id = call.data.get("entry_id")
        monitor = (
            _get_monitor(hass, entry_id) if entry_id else _get_first_monitor(hass)
        )
        if not monitor:
            return
        probe_index = call.data.get("probe_index")
        monitor.set_target(call.data[ATTR_TARGET_TEMP], probe_index=probe_index)

    hass.services.async_register(
        DOMAIN,
        SERVICE_START_COOK,
        handle_start_cook,
        schema=vol.Schema(
            {
                vol.Optional("entry_id"): cv.string,
                vol.Optional(ATTR_TARGET_TEMP, default=DEFAULT_TARGET_TEMP): vol.Coerce(
                    float
                ),
                vol.Optional(ATTR_COOK_NAME, default=DEFAULT_COOK_NAME): cv.string,
                vol.Optional("probe_index"): vol.All(
                    vol.Coerce(int), vol.Range(min=0, max=2)
                ),
                vol.Optional("probe_mode", default=PROBE_MODE_COMBINED): vol.In(
                    [PROBE_MODE_INDIVIDUAL, PROBE_MODE_COMBINED]
                ),
            }
        ),
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_STOP_COOK,
        handle_stop_cook,
        schema=vol.Schema(
            {
                vol.Optional("entry_id"): cv.string,
                vol.Optional("probe_index"): vol.All(
                    vol.Coerce(int), vol.Range(min=0, max=2)
                ),
            }
        ),
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_TARGET,
        handle_set_target,
        schema=vol.Schema(
            {
                vol.Optional("entry_id"): cv.string,
                vol.Required(ATTR_TARGET_TEMP): vol.Coerce(float),
                vol.Optional("probe_index"): vol.All(
                    vol.Coerce(int), vol.Range(min=0, max=2)
                ),
            }
        ),
    )


class CookMonitor:
    """Bridges HA sensor entities to the CookPredictor engine.

    Supports 1–3 internal temperature probes and two usage modes:
      - combined:    all probes track the same cook (e.g. brisket with probes
                     in different spots), sharing a single target temperature.
      - individual:  each probe is independent (e.g. 3 steaks at different
                     doneness levels), each with its own target and timer.
    """

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry

        # Determine how many probes are wired up in this config entry
        probe_count = self._probe_count()

        # Per-probe state (lists indexed 0–2)
        self.predictors: list[CookPredictor] = [
            CookPredictor(target_temp=DEFAULT_TARGET_TEMP)
            for _ in range(probe_count)
        ]
        self.probe_active: list[bool] = [False] * probe_count
        self.probe_target: list[float] = [DEFAULT_TARGET_TEMP] * probe_count
        self.probe_name: list[str] = [DEFAULT_COOK_NAME] * probe_count
        self._last_reading_ts: list[float] = [0.0] * probe_count

        # Runtime mode — set when a cook is started
        self.probe_mode: str = PROBE_MODE_COMBINED

        self._entities: list = []
        self._unsub_listeners: list = []
        self._store = Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}")

    # ── Public properties ────────────────────────────────────────────────

    @property
    def active(self) -> bool:
        """True if any probe is currently active."""
        return any(self.probe_active)

    @property
    def cook_name(self) -> str:
        """Return name of the first active probe (or first probe)."""
        for i, active in enumerate(self.probe_active):
            if active:
                return self.probe_name[i]
        return self.probe_name[0]

    # Kept for backward compat — sensors that only know about probe 0
    @property
    def predictor(self) -> CookPredictor:
        return self.predictors[0]

    # ── Configuration helpers ────────────────────────────────────────────

    def _probe_count(self) -> int:
        """Number of internal probes configured for this entry."""
        count = 1
        if self.entry.data.get(CONF_INTERNAL_SENSOR_2):
            count += 1
        if self.entry.data.get(CONF_INTERNAL_SENSOR_3):
            count += 1
        return count

    def _probe_sensors(self) -> list[str]:
        """Return entity_ids for all configured internal sensors."""
        sensors = [self.entry.data[CONF_INTERNAL_SENSOR]]
        if s2 := self.entry.data.get(CONF_INTERNAL_SENSOR_2):
            sensors.append(s2)
        if s3 := self.entry.data.get(CONF_INTERNAL_SENSOR_3):
            sensors.append(s3)
        return sensors

    def _probe_sensor_ok(self, probe_index: int) -> bool:
        """True if the sensor for this probe exists and is reporting a non-zero numeric value.

        A reading of exactly 0.0 is treated as invalid — disconnected probes
        report a static 0 rather than "unavailable". Real probes never settle
        permanently at 0; frozen meat reads negative and room-temp reads positive.
        """
        sensors = self._probe_sensors()
        if probe_index >= len(sensors):
            return False
        state = self.hass.states.get(sensors[probe_index])
        if not state or state.state in ("unavailable", "unknown"):
            return False
        try:
            return float(state.state) != 0.0
        except (ValueError, TypeError):
            return False

    def _ambient_sensor_ok(self) -> bool:
        """True if the ambient sensor exists and is reporting a non-zero numeric value."""
        state = self.hass.states.get(self.entry.data[CONF_AMBIENT_SENSOR])
        if not state or state.state in ("unavailable", "unknown"):
            return False
        try:
            return float(state.state) != 0.0
        except (ValueError, TypeError):
            return False

    # ── Lifecycle ────────────────────────────────────────────────────────

    async def async_load(self) -> None:
        """Load persisted state."""
        data = await self._store.async_load()
        if not data or not data.get("active"):
            return

        try:
            self.probe_mode = data.get("probe_mode", PROBE_MODE_COMBINED)

            # New format: list of per-probe dicts
            if "probes" in data:
                probe_count = self._probe_count()
                probes = data["probes"][:probe_count]  # guard against shrunk config
                self.predictors = [
                    CookPredictor.from_dict(p["predictor"]) for p in probes
                ]
                self.probe_active = [p.get("active", False) for p in probes]
                self.probe_target = [p.get("target", DEFAULT_TARGET_TEMP) for p in probes]
                self.probe_name = [p.get("name", DEFAULT_COOK_NAME) for p in probes]
                self._last_reading_ts = [0.0] * len(self.predictors)

            # Legacy format: single predictor (v1 saves)
            elif "predictor" in data:
                self.predictors[0] = CookPredictor.from_dict(data["predictor"])
                self.probe_active[0] = True
                self.probe_target[0] = self.predictors[0].target_temp
                self.probe_name[0] = data.get("cook_name", DEFAULT_COOK_NAME)
                self.predictors[0].cook_name = self.probe_name[0]

            if self.active:
                self._start_listening()
                _LOGGER.info(
                    "Restored active cook (mode=%s, probes=%s)",
                    self.probe_mode,
                    sum(self.probe_active),
                )
        except (KeyError, TypeError, ValueError):
            _LOGGER.warning("Could not restore cook state; starting idle")

    def register_entity(self, entity) -> None:
        """Register a sensor entity for state updates."""
        self._entities.append(entity)

    # ── Cook control ─────────────────────────────────────────────────────

    def start_cook(
        self,
        target_temp: float,
        cook_name: str = DEFAULT_COOK_NAME,
        probe_index: int | None = None,
        probe_mode: str = PROBE_MODE_COMBINED,
    ) -> None:
        """Start a cook.

        Combined mode (probe_index=None): activate all probes with the same target.
        Individual mode (probe_index given): activate only that one probe.
        """
        # Pre-flight validation — raise before any state mutation so the
        # HA frontend shows a red notification toast to the user.
        if not self._ambient_sensor_ok():
            raise HomeAssistantError(
                "Cannot start cook: ambient sensor is not available"
            )

        indices: list[int]
        if probe_mode == PROBE_MODE_INDIVIDUAL and probe_index is not None:
            if not self._probe_sensor_ok(probe_index):
                sensor_id = self._probe_sensors()[probe_index]
                raise HomeAssistantError(
                    f"Cannot start cook: probe {probe_index + 1} sensor"
                    f" ({sensor_id}) is not available"
                )
            indices = [probe_index]
        else:
            # Combined: only start probes that are currently reachable
            indices = [
                i for i in range(len(self.predictors)) if self._probe_sensor_ok(i)
            ]
            if not indices:
                raise HomeAssistantError(
                    "Cannot start cook: no probe sensors are currently available"
                )
            for skipped in set(range(len(self.predictors))) - set(indices):
                _LOGGER.warning(
                    "Probe %d sensor unavailable — skipping for this cook",
                    skipped + 1,
                )

        self.probe_mode = probe_mode

        for i in indices:
            if i >= len(self.predictors):
                continue
            self.predictors[i] = CookPredictor(target_temp=target_temp)
            self.predictors[i].cook_name = cook_name
            self.predictors[i]._start_temp = None
            self.probe_active[i] = True
            self.probe_target[i] = target_temp
            self.probe_name[i] = cook_name
            self._last_reading_ts[i] = 0.0

        self._start_listening()
        self._notify_entities()
        self.hass.async_create_task(self.async_save())

    def stop_cook(self, probe_index: int | None = None) -> None:
        """Stop a cook.

        probe_index=None: stop all probes.
        probe_index=0/1/2: stop only that probe (individual mode).
        """
        indices = (
            list(range(len(self.predictors)))
            if probe_index is None
            else [probe_index]
        )

        # Snapshot readings BEFORE resetting predictors so the export task
        # (scheduled below) still has the data when it actually runs.
        if self.entry.data.get(CONF_EXPORT_DATA):
            for i in indices:
                if i >= len(self.predictors):
                    continue
                if not self.probe_active[i] or not self.predictors[i].readings:
                    continue
                pred = self.predictors[i]
                # Use the peak temperature across all readings rather than
                # the current reading.  If the probe was physically removed
                # before stop_cook was called the current reading drops to 0,
                # which would incorrectly mark the cook as not having reached
                # target even when it clearly did earlier in the session.
                peak_temp = max(
                    (ti for _, ti, _ in pred.readings if ti > 0),
                    default=0.0,
                )
                reached = peak_temp >= pred.target_temp
                self.hass.async_create_task(
                    self._async_export_csv(
                        probe_index=i,
                        readings=list(pred.readings),   # snapshot
                        target_temp=pred.target_temp,
                        reached_target=reached,
                        cook_name=self.probe_name[i],
                    )
                )

        for i in indices:
            if i >= len(self.predictors):
                continue
            self.probe_active[i] = False
            self.predictors[i].reset()
            self.probe_name[i] = DEFAULT_COOK_NAME
            self._last_reading_ts[i] = 0.0

        # Stop listening only when all probes are idle
        if not self.active:
            self._stop_listening()

        self._notify_entities()
        self.hass.async_create_task(self.async_save())

    async def _async_export_csv(
        self,
        probe_index: int,
        readings: list[tuple[float, float, float]],
        target_temp: float,
        reached_target: bool,
        cook_name: str = DEFAULT_COOK_NAME,
    ) -> None:
        """Write cook readings to a CSV file for model fine-tuning.

        The file lands in <config_dir>/probe_ability_exports/ with a
        timestamp + probe number in the name so runs never overwrite each other.

        Format
        ------
        Lines beginning with ``#`` are metadata and can be skipped by most
        tools (pandas: ``comment='#'``, Excel: ignore manually).
        Data columns: elapsed_s, internal_temp_c, ambient_temp_c, predicted_remaining_s, confidence.

        predicted_remaining_s and confidence are generated by replaying the cook
        through a fresh predictor instance — they reproduce the exact estimates
        shown live on the card (empty during the initial collecting phase).
        """
        import csv
        import os
        from datetime import datetime

        if not readings:
            return

        export_dir = os.path.join(self.hass.config.config_dir, EXPORT_SUBDIR)
        now_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"cook_{now_str}_probe{probe_index + 1}.csv"
        filepath = os.path.join(export_dir, filename)

        probe_mode = self.probe_mode
        t0 = readings[0][0]

        # Replay predictions: feed readings one-by-one into a fresh predictor
        # to reproduce the live estimates shown on the card.
        replay = CookPredictor(target_temp=target_temp)
        predicted: list[tuple[float | None, str | None]] = []
        for ts, internal, ambient in readings:
            replay.add_reading(ts, internal, ambient)
            result = replay.predict()
            predicted.append((
                round(result.time_remaining_seconds, 1)
                if result.time_remaining_seconds is not None
                else None,
                result.confidence,
            ))

        def _write() -> None:
            os.makedirs(export_dir, exist_ok=True)
            with open(filepath, "w", newline="", encoding="utf-8") as fh:
                fh.write("# probe_ability_export_version: 3\n")
                fh.write(f"# probe_index: {probe_index}\n")
                fh.write(f"# probe_mode: {probe_mode}\n")
                fh.write(f"# cook_name: {cook_name}\n")
                fh.write(f"# target_temp_c: {target_temp}\n")
                fh.write(f"# reached_target: {str(reached_target).lower()}\n")
                fh.write(f"# total_readings: {len(readings)}\n")
                fh.write(f"# export_timestamp: {datetime.now().isoformat()}\n")
                writer = csv.writer(fh)
                writer.writerow(["elapsed_s", "internal_temp_c", "ambient_temp_c", "predicted_remaining_s", "confidence"])
                for (ts, internal, ambient), (remaining, confidence) in zip(readings, predicted):
                    writer.writerow([
                        round(ts - t0, 1),
                        round(internal, 2),
                        round(ambient, 2),
                        remaining if remaining is not None else "",
                        confidence if confidence is not None else "",
                    ])

        await self.hass.async_add_executor_job(_write)
        _LOGGER.info(
            "Cook data exported: %s (%d readings, reached_target=%s)",
            filename, len(readings), reached_target,
        )

    def set_target(self, target_temp: float, probe_index: int | None = None) -> None:
        """Update target temperature mid-cook."""
        indices = (
            list(range(len(self.predictors)))
            if probe_index is None
            else [probe_index]
        )
        for i in indices:
            if i < len(self.predictors):
                self.predictors[i].target_temp = target_temp
                self.probe_target[i] = target_temp
        self._notify_entities()

    # ── Internal state management ────────────────────────────────────────

    @callback
    def _notify_entities(self) -> None:
        """Tell sensor entities to refresh."""
        for entity in self._entities:
            entity.async_write_ha_state()

    def _start_listening(self) -> None:
        """Subscribe to sensor state changes for all probes + ambient."""
        self._stop_listening()
        watched = self._probe_sensors() + [self.entry.data[CONF_AMBIENT_SENSOR]]
        self._unsub_listeners.append(
            async_track_state_change_event(
                self.hass, watched, self._async_on_state_change
            )
        )

    @callback
    def _stop_listening(self) -> None:
        """Remove state listeners."""
        for unsub in self._unsub_listeners:
            unsub()
        self._unsub_listeners.clear()

    @callback
    def async_stop(self) -> None:
        """Clean up on unload."""
        self._stop_listening()

    @callback
    def _async_on_state_change(self, event: Event) -> None:
        """Handle sensor state change — route readings to the correct probe."""
        if not self.active:
            return

        now = time.time()
        probe_sensors = self._probe_sensors()
        ambient_state = self.hass.states.get(self.entry.data[CONF_AMBIENT_SENSOR])
        if not ambient_state:
            return

        try:
            ambient = float(ambient_state.state)
        except (ValueError, TypeError):
            return

        # Update each active probe that has passed its debounce threshold
        for i, sensor_id in enumerate(probe_sensors):
            if not self.probe_active[i]:
                continue
            if now - self._last_reading_ts[i] < MIN_READING_INTERVAL:
                continue

            internal_state = self.hass.states.get(sensor_id)
            if not internal_state:
                continue

            try:
                internal = float(internal_state.state)
            except (ValueError, TypeError):
                continue

            self.predictors[i].add_reading(now, internal, ambient)
            self._last_reading_ts[i] = now

        self._notify_entities()

    async def async_save(self, _event: Event | None = None) -> None:
        """Persist state to disk."""
        await self._store.async_save(
            {
                "active": self.active,
                "probe_mode": self.probe_mode,
                "probes": [
                    {
                        "active": active,
                        "target": target,
                        "name": name,
                        "predictor": pred.to_dict(),
                    }
                    for active, target, name, pred in zip(
                        self.probe_active,
                        self.probe_target,
                        self.probe_name,
                        self.predictors,
                    )
                ],
            }
        )
