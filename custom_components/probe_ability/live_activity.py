"""Companion-app Live Activity support for Probe-ability.

Turns CookMonitor state into ``notify.mobile_app_*`` Live Activity payloads
(https://companion.home-assistant.io/docs/notifications/live-activities/).

A Live Activity is an ordinary mobile_app notification carrying
``live_update: true`` and a stable ``tag``.  Re-sending the same tag updates
the activity in place; sending ``clear_notification`` for the tag ends it.

This module has no Home Assistant imports so the payload and throttle logic
can be exercised standalone by ``test_live_activity.py``.  The manager only
touches ``hass.services`` and ``hass.async_create_task``.
"""

from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass

try:  # package import inside Home Assistant
    from .const import DEFAULT_COOK_NAME, PROBE_MODE_INDIVIDUAL
except ImportError:  # standalone (test_live_activity.py adds the package dir to sys.path)
    from const import DEFAULT_COOK_NAME, PROBE_MODE_INDIVIDUAL  # type: ignore[no-redef]

TAG_PREFIX = "probe_ability"
TAG_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

# Routine (temperature-driven) updates are pushed at most this often per tag.
MIN_PUSH_INTERVAL_S = 60
# Temperature movement (°C) that justifies a routine update.
TEMP_DELTA_C = 0.5
# Chronometer target movement (s) that justifies a routine update.
ETA_DELTA_S = 120
# iOS ends a Live Activity after 8 h; roll to a fresh tag a little before that.
ACTIVITY_MAX_AGE_S = 7 * 3600 + 50 * 60

CLEAR_MESSAGE = "clear_notification"
FALLBACK_TITLE = "Probe-ability"

# Phases in which a prediction exists and a device-side countdown makes sense.
CHRONOMETER_PHASES = ("heating", "stall", "finishing")

# Icon + colour per phase — mirrors the card's phaseIcon / phaseColor maps
# (HA default theme hex values so the phone matches the dashboard).
PHASE_STYLE: dict[str, tuple[str, str]] = {
    "collecting": ("mdi:thermometer", "#03A9F4"),
    "heating": ("mdi:fire", "#FF9800"),
    "stall": ("mdi:pause-circle-outline", "#DB4437"),
    "finishing": ("mdi:flag-checkered", "#43A047"),
    "done": ("mdi:check-circle", "#43A047"),
    "unreachable": ("mdi:fire-alert", "#DB4437"),
}

PHASE_LABEL: dict[str, str] = {
    "collecting": "Collecting data",
    "heating": "Heating",
    "stall": "Stall",
    "finishing": "Finishing",
    "done": "Target reached",
    "unreachable": "Target unreachable",
}


# ── Pure data ────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class SlotState:
    """Everything needed to render one Live Activity, extracted from the monitor."""

    tag: str
    title: str  # static for the life of the activity
    phase: str  # collecting | heating | stall | finishing | done | unreachable
    confidence: str  # low | medium | high
    current_c: float | None
    start_c: float | None
    target_c: float
    time_remaining_s: float | None
    eta_ts: float | None
    temp_unit: str  # "C" | "F"
    rest_peak_c: float | None = None   # highest temp reached while resting (after a pull)
    rest_short_c: float | None = None  # how far that peak fell short of target (None if not short)


@dataclass
class PushRecord:
    """What was last sent for a tag; drives the throttle in should_push()."""

    ts: float
    phase: str
    target_c: float
    current_c: float | None
    progress: int
    when: int | None  # chronometer timestamp, None when no chronometer was sent


# ── Pure functions ───────────────────────────────────────────────────────────


def format_temp(celsius: float, unit: str, *, with_unit: bool = False) -> str:
    """Format a °C value in the configured display unit (matches the card)."""
    if unit == "F":
        text = f"{round(celsius * 9 / 5 + 32)}°"
    else:
        text = f"{celsius:.1f}°"
    return f"{text}{unit}" if with_unit else text


def compute_progress(
    start_c: float | None, current_c: float | None, target_c: float, phase: str
) -> int:
    """Temperature progress 0–100 from start temp towards target."""
    if phase == "done":
        return 100
    if start_c is None or current_c is None or target_c <= start_c:
        return 0
    pct = (current_c - start_c) / (target_c - start_c) * 100
    return max(0, min(100, round(pct)))


def use_chronometer(state: SlotState) -> bool:
    """True when a device-side countdown to the ETA should be shown.

    Not gated on confidence: toggling the timer on every confidence flip would
    force a push each time.  Low confidence is noted in the message instead.
    """
    return state.phase in CHRONOMETER_PHASES and state.eta_ts is not None


def build_message(state: SlotState) -> str:
    """Body text.  On the iOS lock screen the chronometer replaces this line."""
    unit = state.temp_unit
    target = format_temp(state.target_c, unit)
    if state.phase == "done":
        if state.rest_short_c is not None and state.rest_peak_c is not None:
            short = state.rest_short_c * (9 / 5 if unit == "F" else 1)
            return (f"Rested · peaked {format_temp(state.rest_peak_c, unit)} · "
                    f"{short:.1f}° below target {target}")
        return f"Target reached · {target}"
    cur = format_temp(state.current_c, unit) if state.current_c is not None else "--"
    if state.phase == "unreachable":
        return f"Target unreachable · raise the heat · {cur} / {target}"
    label = PHASE_LABEL.get(state.phase, state.phase.capitalize())
    text = f"{label} · {cur} / {target}"
    if state.confidence == "low" and use_chronometer(state):
        text += " · low confidence"
    return text


def build_payload(state: SlotState, *, silent: bool, alert: bool = False) -> dict:
    """Full ``notify.mobile_app_*`` service data for one activity.

    ``alert_once`` is set on every update so Android (and a paired watch)
    only buzzes when the notification first appears — otherwise each
    temperature update would vibrate the phone again.  ``alert`` re-enables
    the sound/vibration for a single update (target reached / unreachable).
    """
    icon, color = PHASE_STYLE.get(state.phase, PHASE_STYLE["collecting"])
    data: dict = {
        "tag": state.tag,
        "live_update": True,
        "alert_once": not alert,
        "progress": compute_progress(
            state.start_c, state.current_c, state.target_c, state.phase
        ),
        "progress_max": 100,
        "progress_bar_direction": "increasing",
        "progress_bar_color": color,
        "notification_icon": icon,
        "notification_icon_color": color,
        "silent": silent,
    }
    if state.current_c is not None:
        data["critical_text"] = format_temp(state.current_c, state.temp_unit, with_unit=True)
    if use_chronometer(state):
        data["chronometer"] = True
        data["when"] = int(state.eta_ts)
    return {"title": state.title, "message": build_message(state), "data": data}


def build_clear_payload(tag: str) -> dict:
    """Service data that ends the activity with this tag."""
    return {"message": CLEAR_MESSAGE, "data": {"tag": tag}}


def make_tag(entry_id: str, slot: str, generation: int = 0) -> str:
    """Stable activity tag: ``probe_ability_<entry8>_<slot>[_g<n>]``."""
    tag = f"{TAG_PREFIX}_{entry_id[:8]}_{slot}"
    if generation > 0:
        tag += f"_g{generation}"
    return tag


def activity_generation(first_reading_ts: float | None, now: float) -> int:
    """How many times the 8 h iOS activity limit has rolled over for this cook."""
    if first_reading_ts is None or now <= first_reading_ts:
        return 0
    return int((now - first_reading_ts) // ACTIVITY_MAX_AGE_S)


def make_record(state: SlotState, now: float) -> PushRecord:
    """Snapshot the parts of a state that the throttle compares."""
    return PushRecord(
        ts=now,
        phase=state.phase,
        target_c=state.target_c,
        current_c=state.current_c,
        progress=compute_progress(
            state.start_c, state.current_c, state.target_c, state.phase
        ),
        when=int(state.eta_ts) if use_chronometer(state) else None,
    )


def should_push(prev: PushRecord | None, new: PushRecord, *, force: bool = False) -> bool:
    """Deterministic throttle: decide whether ``new`` is worth a push after ``prev``."""
    if prev is None or force:
        return True
    if new.phase != prev.phase or new.target_c != prev.target_c:
        return True
    if (new.when is None) != (prev.when is None):
        return True
    # First reading after start: show the temperature chip without waiting
    if (new.current_c is None) != (prev.current_c is None):
        return True
    if new.ts - prev.ts < MIN_PUSH_INTERVAL_S:
        return False
    if (
        new.current_c is not None
        and prev.current_c is not None
        and abs(new.current_c - prev.current_c) >= TEMP_DELTA_C
    ):
        return True
    if new.progress != prev.progress:
        return True
    if (
        new.when is not None
        and prev.when is not None
        and abs(new.when - prev.when) >= ETA_DELTA_S
    ):
        return True
    return False


def should_alert(prev: PushRecord | None, new: PushRecord) -> bool:
    """True for the one update that deserves a buzz: reaching (or losing) the target."""
    return (
        prev is not None
        and new.phase != prev.phase
        and new.phase in ("done", "unreachable")
    )


def is_silent(prev: PushRecord | None, new: PushRecord) -> bool:
    """Routine updates are low priority; start, done/unreachable and target changes are not."""
    if prev is None:
        return False
    if new.phase != prev.phase and new.phase in ("done", "unreachable"):
        return False
    if new.target_c != prev.target_c:
        return False
    return True


def activity_title(cook_name: str, probe_index: int | None = None) -> str:
    """Static title: the cook name (or a fallback), plus the probe in individual mode."""
    title = cook_name if cook_name and cook_name != DEFAULT_COOK_NAME else FALLBACK_TITLE
    if probe_index is not None:
        title += f" · Probe {probe_index + 1}"
    return title


# ── Manager ──────────────────────────────────────────────────────────────────


@dataclass
class _Send:
    tag: str
    payload: dict
    targets: list[str]


class LiveActivityManager:
    """Keeps the phone's Live Activities in sync with a CookMonitor.

    ``refresh()`` is synchronous and safe to call from HA callbacks: it
    decides what (if anything) changed and schedules the notify calls as a
    task.  Sends are serialised behind a lock so a clear-then-start pair
    (tag rollover, mode switch) reaches the phone in order.
    """

    def __init__(self, hass, entry_id: str, temp_unit: str, targets: list[str], logger) -> None:
        self._hass = hass
        self._entry_id = entry_id
        self._temp_unit = temp_unit
        self._targets: list[str] = [t for t in targets if t]
        self._sent: dict[str, PushRecord] = {}
        self._warned: set[str] = set()
        self._lock: asyncio.Lock | None = None  # created lazily on the event loop
        self._log = logger

    @property
    def enabled(self) -> bool:
        return bool(self._targets)

    @property
    def targets(self) -> list[str]:
        return list(self._targets)

    # ── Public API ───────────────────────────────────────────────────────

    def set_targets(self, targets: list[str], monitor, *, now: float | None = None) -> None:
        """Apply a new target list (options flow) without reloading the entry."""
        new = [t for t in targets if t]
        removed = [s for s in self._targets if s not in new]
        added = [s for s in new if s not in self._targets]
        self._targets = new
        self._warned.clear()

        if removed and self._sent:
            self._dispatch(
                [_Send(tag, build_clear_payload(tag), removed) for tag in self._sent]
            )
        if not new:
            self._sent.clear()
            return
        if added:
            # New phones need a start push — forget what was sent so every
            # desired tag goes out again (existing phones get a harmless update).
            self._sent.clear()
            self.refresh(monitor, force=True, now=now)

    def refresh(self, monitor, *, force: bool = False, now: float | None = None) -> None:
        """Reconcile the phone with the monitor: clear stale tags, push changed ones."""
        if not self._targets:
            return
        now = time.time() if now is None else now
        desired = self._desired_states(monitor, now)
        sends: list[_Send] = []

        for tag in [t for t in self._sent if t not in desired]:
            del self._sent[tag]
            sends.append(_Send(tag, build_clear_payload(tag), list(self._targets)))

        for tag, state in desired.items():
            prev = self._sent.get(tag)
            record = make_record(state, now)
            if not should_push(prev, record, force=force):
                continue
            payload = build_payload(
                state,
                silent=is_silent(prev, record),
                alert=should_alert(prev, record),
            )
            self._sent[tag] = record
            sends.append(_Send(tag, payload, list(self._targets)))

        self._dispatch(sends)

    def clear_all(self) -> None:
        """End every activity this manager has started."""
        sends = [
            _Send(tag, build_clear_payload(tag), list(self._targets)) for tag in self._sent
        ]
        self._sent.clear()
        self._dispatch(sends)

    # ── State extraction ─────────────────────────────────────────────────

    def _desired_states(self, monitor, now: float) -> dict[str, SlotState]:
        """One SlotState per activity that should currently exist."""
        predictors = monitor.predictors
        active = [i for i, is_active in enumerate(monitor.probe_active) if is_active]
        if not active:
            return {}

        states: dict[str, SlotState] = {}

        if monitor.probe_mode == PROBE_MODE_INDIVIDUAL:
            for i in active:
                pred = predictors[i]
                result = pred.predict()
                first_ts = pred.readings[0][0] if pred.readings else None
                tag = make_tag(self._entry_id, f"p{i + 1}", activity_generation(first_ts, now))
                states[tag] = SlotState(
                    tag=tag,
                    title=activity_title(
                        monitor.probe_name[i], i if len(predictors) > 1 else None
                    ),
                    phase=result.phase,
                    confidence=result.confidence,
                    current_c=pred.current_temp,
                    start_c=pred.start_temp,
                    target_c=pred.target_temp,
                    time_remaining_s=result.time_remaining_seconds,
                    eta_ts=result.eta_timestamp,
                    temp_unit=self._temp_unit,
                    rest_peak_c=pred.rest_peak_c,
                    rest_short_c=pred.rest_short_c,
                )
            return states

        # Combined mode: one activity driven by the slowest probe.  "done"
        # only when every active probe is done (unlike the probe-0 sensor,
        # which reads unknown at that point).
        results = {i: predictors[i].predict() for i in active}
        not_done = [i for i in active if results[i].phase != "done"]
        if not not_done:
            driver = active[0]
            phase = "done"
        else:
            with_eta = [
                i for i in not_done if results[i].time_remaining_seconds is not None
            ]
            if with_eta:
                driver = max(with_eta, key=lambda i: results[i].time_remaining_seconds)
            else:
                driver = min(
                    not_done,
                    key=lambda i: (
                        predictors[i].current_temp
                        if predictors[i].current_temp is not None
                        else float("inf")
                    ),
                )
            phase = results[driver].phase

        pred = predictors[driver]
        result = results[driver]
        first_ts = min(
            (predictors[i].readings[0][0] for i in active if predictors[i].readings),
            default=None,
        )
        tag = make_tag(self._entry_id, "c", activity_generation(first_ts, now))
        states[tag] = SlotState(
            tag=tag,
            title=activity_title(monitor.cook_name),
            phase=phase,
            confidence=result.confidence,
            current_c=pred.current_temp,
            start_c=pred.start_temp,
            target_c=pred.target_temp,
            time_remaining_s=result.time_remaining_seconds,
            eta_ts=result.eta_timestamp,
            temp_unit=self._temp_unit,
            rest_peak_c=pred.rest_peak_c,
            rest_short_c=pred.rest_short_c,
        )
        return states

    # ── Sending ──────────────────────────────────────────────────────────

    def _dispatch(self, sends: list[_Send]) -> None:
        if sends:
            self._hass.async_create_task(self._async_send(sends))

    async def _async_send(self, sends: list[_Send]) -> None:
        if self._lock is None:
            self._lock = asyncio.Lock()
        async with self._lock:
            for send in sends:
                for service in send.targets:
                    if not self._hass.services.has_service("notify", service):
                        if service not in self._warned:
                            self._warned.add(service)
                            self._log.warning(
                                "Live Activity target notify.%s is not available — "
                                "skipping (is the Companion app registered?)",
                                service,
                            )
                        continue
                    try:
                        await self._hass.services.async_call(
                            "notify", service, send.payload, blocking=True
                        )
                        self._log.debug(
                            "Live Activity push to notify.%s: %s", service, send.payload
                        )
                    except Exception:  # noqa: BLE001 — never let notify break the cook
                        self._log.warning(
                            "Live Activity push to notify.%s failed", service, exc_info=True
                        )
