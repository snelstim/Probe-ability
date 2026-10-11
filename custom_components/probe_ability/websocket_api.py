"""Websocket command feeding the card's graph view.

``probe_ability/history`` returns one probe's recorded readings (downsampled),
the target in force over time and the forecast trajectory.  It is read-only and
never calls ``CookPredictor.predict()`` (which mutates smoothing state).  The
series stays out of sensor attributes on purpose: a long cook is thousands of
points, far over the recorder's attribute size limit.

All temperatures are °C; the card converts to the display unit.

``combined: true`` (the card's combined mode) follows the probe that sets the
shared countdown — the slowest, as the time_remaining sensor does — instead of
the ``probe`` slot asked for; the reply says which probe that was.
"""

from __future__ import annotations

import time

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN, MAX_PROBES
from .predictor import CookPredictor

WS_HISTORY = f"{DOMAIN}/history"
MAX_POINTS = 300  # per series; a 16 h cook at 30 s is ~1900 raw readings
STALE_S = 300  # a probe silent this long no longer sets the combined countdown (as in sensor.py)


def downsample(
    readings: list[tuple[float, float, float]], max_points: int = MAX_POINTS
) -> list[list[float]]:
    """Bucket-mean ``readings`` down to at most ``max_points`` rows.

    The first and last readings are kept exactly, so the line starts where the
    cook started and ends on the live value.
    """
    n = len(readings)
    if n <= max_points:
        return [[round(t, 1), round(i, 2), round(a, 2)] for t, i, a in readings]
    out: list[list[float]] = [[round(readings[0][0], 1), round(readings[0][1], 2), round(readings[0][2], 2)]]
    inner = readings[1:-1]
    buckets = max_points - 2
    for b in range(buckets):
        chunk = inner[b * len(inner) // buckets:(b + 1) * len(inner) // buckets]
        if not chunk:
            continue
        m = len(chunk)
        out.append([
            round(sum(r[0] for r in chunk) / m, 1),
            round(sum(r[1] for r in chunk) / m, 2),
            round(sum(r[2] for r in chunk) / m, 2),
        ])
    last = readings[-1]
    out.append([round(last[0], 1), round(last[1], 2), round(last[2], 2)])
    return out


def slowest_probe(monitor, now: float | None = None) -> int:
    """Slot of the probe that sets the combined countdown.

    Mirrors the time_remaining sensor in combined mode: of the active probes
    that are not stale and still have an estimate, the one with the most time
    left.  Falls back to the first active probe (then slot 0) when none qualify.
    Pure — it reads published estimates and never calls predict().
    """
    now = time.time() if now is None else now
    last_ts = getattr(monitor, "_last_reading_ts", [])
    best, best_remaining, first_active = None, -1.0, None
    for i, (active, predictor) in enumerate(zip(monitor.probe_active, monitor.predictors)):
        if not active:
            continue
        if first_active is None:
            first_active = i
        if i < len(last_ts) and last_ts[i] > 0 and now - last_ts[i] > STALE_S:
            continue
        remaining = predictor.remaining_seconds()
        if remaining is not None and remaining > best_remaining:
            best, best_remaining = i, remaining
    if best is not None:
        return best
    return first_active if first_active is not None else 0


def build_history(predictor: CookPredictor, max_points: int = MAX_POINTS, probe: int = 0) -> dict:
    """The websocket payload for one probe (HA-free, so it can be tested alone)."""
    readings = predictor.readings
    return {
        "probe": probe,
        "start_ts": round(readings[0][0], 1) if readings else None,
        "now_ts": round(readings[-1][0], 1) if readings else None,
        "target_temp": predictor.target_temp,
        "target_history": predictor.target_history,
        "readings": downsample(readings, max_points),
        "forecast": predictor.forecast_curve(),
    }


def resolve_predictor(
    hass: HomeAssistant, entity_id: str, probe: int, combined: bool = False
) -> tuple[int, CookPredictor] | None:
    """(slot, predictor) behind a card's sensor entity, or None.

    With ``combined`` the slot is the one that sets the shared countdown
    (see slowest_probe) rather than ``probe``.
    """
    entry = er.async_get(hass).async_get(entity_id)
    if entry is None or entry.config_entry_id is None:
        return None
    monitor = hass.data.get(DOMAIN, {}).get(entry.config_entry_id)
    predictors = getattr(monitor, "predictors", None)
    if predictors is None:
        return None
    if combined:
        probe = slowest_probe(monitor)
    if not 0 <= probe < len(predictors):
        return None
    return probe, predictors[probe]


@websocket_api.websocket_command(
    {
        vol.Required("type"): WS_HISTORY,
        vol.Required("entity_id"): cv.entity_id,
        vol.Required("probe"): vol.All(int, vol.Range(min=0, max=MAX_PROBES - 1)),
        vol.Optional("combined", default=False): bool,
    }
)
@callback
def ws_history(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict) -> None:
    """Return recorded readings, target history and forecast for one probe."""
    found = resolve_predictor(hass, msg["entity_id"], msg["probe"], msg.get("combined", False))
    if found is None:
        connection.send_error(msg["id"], websocket_api.ERR_NOT_FOUND, "Unknown Probe-ability entity or probe")
        return
    probe, predictor = found
    connection.send_result(msg["id"], build_history(predictor, probe=probe))


def async_register(hass: HomeAssistant) -> None:
    """Register the websocket commands (once, from async_setup)."""
    websocket_api.async_register_command(hass, ws_history)
