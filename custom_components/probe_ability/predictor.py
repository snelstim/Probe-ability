"""Standalone cook prediction engine using Newton's Law of Heating.

This module has no Home Assistant dependencies and can be tested independently.
Feed it (timestamp, internal_temp, ambient_temp) readings and it predicts
when a target temperature will be reached.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass
class PredictionResult:
    """Result of a cook prediction."""

    time_remaining_seconds: float | None = None
    eta_timestamp: float | None = None
    rate_per_minute: float | None = None
    phase: str = "collecting"  # collecting | heating | stall | finishing | done
    confidence: str = "low"  # low | medium | high
    message: str = ""


class CookPredictor:
    """Predicts cook completion using exponential curve fitting.

    Uses Newton's Law of Heating: dT/dt = k * (T_ambient - T_internal)
    Linearised as: ln(T_ambient - T_internal) = a - k*t
    Fitted via least-squares regression on a sliding window of readings.
    Falls back to linear extrapolation during stalls or when ambient is
    too close to target.
    """

    def __init__(self, target_temp: float) -> None:
        self._target_temp = target_temp
        self.readings: list[tuple[float, float, float]] = []  # (ts, internal, ambient)

        # Smoothed time-remaining (seconds) — updated via EMA on every valid
        # prediction so short-term rate noise doesn't cause large display swings.
        # Also served back during stalls / zero-rate moments.
        self._last_stable_remaining: float | None = None

        # EMA smoothing factor: lower = more stable, slower to react to real
        # changes.  0.15 → a sudden step is ~50% reflected after 4–5 updates
        # (≈2 min at 30 s/reading).
        self._ema_alpha: float = 0.15

        # Tuning constants
        self._min_readings = 10
        self._min_data_seconds = 600  # 10 min before first prediction
        self._window_seconds = 2400  # 40 min sliding window for fit
        self._rate_window_seconds = 300  # 5 min window for instantaneous rate
        self._stall_threshold_c = 0.5  # <0.5°C change over stall window = stall
        self._stall_check_seconds = 600  # 10 min sustained = stall

    @property
    def target_temp(self) -> float:
        return self._target_temp

    @target_temp.setter
    def target_temp(self, value: float) -> None:
        self._target_temp = value

    @property
    def current_temp(self) -> float | None:
        return self.readings[-1][1] if self.readings else None

    @property
    def current_ambient(self) -> float | None:
        return self.readings[-1][2] if self.readings else None

    def add_reading(
        self, timestamp: float, internal_temp: float, ambient_temp: float
    ) -> None:
        """Add a temperature reading."""
        self.readings.append((timestamp, internal_temp, ambient_temp))

    def reset(self) -> None:
        """Clear all readings for a new cook."""
        self.readings.clear()

    def to_dict(self) -> dict:
        """Serialise state for persistence."""
        return {
            "target_temp": self._target_temp,
            "readings": self.readings,
            "last_stable_remaining": self._last_stable_remaining,
        }

    @classmethod
    def from_dict(cls, data: dict) -> CookPredictor:
        """Restore from serialised state."""
        predictor = cls(target_temp=data["target_temp"])
        predictor.readings = [tuple(r) for r in data.get("readings", [])]
        predictor._last_stable_remaining = data.get("last_stable_remaining")
        return predictor

    def predict(self) -> PredictionResult:
        """Run prediction based on collected readings."""
        if len(self.readings) < self._min_readings:
            return PredictionResult(
                phase="collecting",
                message=(
                    f"Collecting data ({len(self.readings)}/{self._min_readings} readings)"
                ),
            )

        now_ts, current_temp, _ = self.readings[-1]

        # Already done?
        if current_temp >= self._target_temp:
            return PredictionResult(
                time_remaining_seconds=0,
                eta_timestamp=now_ts,
                phase="done",
                confidence="high",
                message="Target temperature reached",
            )

        # Build sliding window
        windowed = self._windowed_readings()
        data_span = windowed[-1][0] - windowed[0][0]

        if data_span < self._min_data_seconds:
            elapsed = data_span / 60
            needed = self._min_data_seconds / 60
            return PredictionResult(
                phase="collecting",
                message=f"Need more data ({elapsed:.0f}/{needed:.0f} min)",
            )

        rate = self._calculate_rate(windowed)
        phase = self._detect_phase(windowed, rate)
        avg_ambient = sum(ta for _, _, ta in windowed) / len(windowed)
        confidence = self._assess_confidence(windowed, data_span)

        # Target above ambient — exponential model won't work, linear only
        if self._target_temp >= avg_ambient - 1.0:
            return self._linear_estimate(
                now_ts, current_temp, rate, phase,
                message="Ambient temp near/below target; linear estimate only",
                confidence=confidence,
            )

        # Stall — exponential breaks down; serve the last stable estimate so
        # the display never falls back to 0 or unknown.
        if phase == "stall":
            result = self._linear_estimate(
                now_ts, current_temp, rate, "stall",
                message="Stall detected; estimate may be inaccurate",
                confidence=confidence,
            )
            if result.time_remaining_seconds is not None and result.time_remaining_seconds > 0:
                smoothed = self._smooth(result.time_remaining_seconds)
                self._last_stable_remaining = smoothed
                result.time_remaining_seconds = smoothed
                result.eta_timestamp = now_ts + smoothed
            elif result.time_remaining_seconds is None and self._last_stable_remaining is not None:
                result.time_remaining_seconds = self._last_stable_remaining
                result.eta_timestamp = now_ts + self._last_stable_remaining
            return result

        # Primary: exponential fit
        remaining = self._exponential_estimate(windowed, avg_ambient, current_temp)

        if remaining is not None and remaining > 0:
            remaining = self._smooth(remaining)
            self._last_stable_remaining = remaining
            return PredictionResult(
                time_remaining_seconds=remaining,
                eta_timestamp=now_ts + remaining,
                rate_per_minute=rate,
                phase=phase,
                confidence=confidence,
            )

        # Fallback: linear
        result = self._linear_estimate(
            now_ts, current_temp, rate, phase,
            message="Exponential fit failed; using linear estimate",
            confidence=confidence,
        )
        if result.time_remaining_seconds is not None and result.time_remaining_seconds > 0:
            smoothed = self._smooth(result.time_remaining_seconds)
            self._last_stable_remaining = smoothed
            result.time_remaining_seconds = smoothed
            result.eta_timestamp = now_ts + smoothed
        elif result.time_remaining_seconds is None and self._last_stable_remaining is not None:
            # Rate is too low / direction reversed to compute a fresh estimate.
            # Serve the last known-good value so the display never shows 0 or
            # "unknown" during a momentary flat spot that hasn't yet been
            # classified as a full stall.
            result.time_remaining_seconds = self._last_stable_remaining
            result.eta_timestamp = now_ts + self._last_stable_remaining
        return result

    def _smooth(self, new_value: float) -> float:
        """Blend a new estimate with the previous one via EMA.

        First call (no previous value) returns the raw value so we don't
        start with a biased estimate.
        """
        if self._last_stable_remaining is None:
            return new_value
        return self._ema_alpha * new_value + (1 - self._ema_alpha) * self._last_stable_remaining

    # ── Internal helpers ────────────────────────────────────────────────

    def _windowed_readings(self) -> list[tuple[float, float, float]]:
        now_ts = self.readings[-1][0]
        window_start = now_ts - self._window_seconds
        windowed = [(t, ti, ta) for t, ti, ta in self.readings if t >= window_start]
        if len(windowed) < self._min_readings:
            windowed = self.readings[-self._min_readings :]
        return windowed

    def _calculate_rate(
        self, readings: list[tuple[float, float, float]]
    ) -> float | None:
        """Rate in °C/minute over recent readings."""
        if len(readings) < 2:
            return None
        cutoff = readings[-1][0] - self._rate_window_seconds
        recent = [r for r in readings if r[0] >= cutoff]
        if len(recent) < 2:
            recent = readings[-2:]
        dt = recent[-1][0] - recent[0][0]
        if dt < 1:
            return None
        return (recent[-1][1] - recent[0][1]) / dt * 60

    def _detect_phase(
        self,
        readings: list[tuple[float, float, float]],
        rate: float | None,
    ) -> str:
        if rate is None:
            return "collecting"

        # Check for stall: minimal temp change over stall window
        stall_cutoff = readings[-1][0] - self._stall_check_seconds
        stall_readings = [r for r in readings if r[0] >= stall_cutoff]
        if len(stall_readings) >= 2:
            temp_change = abs(stall_readings[-1][1] - stall_readings[0][1])
            time_span = stall_readings[-1][0] - stall_readings[0][0]
            if time_span >= self._stall_check_seconds * 0.8 and temp_change < self._stall_threshold_c:
                return "stall"

        # Close to target = finishing
        temp_range = self._target_temp - readings[0][1]
        if temp_range > 0:
            progress = (readings[-1][1] - readings[0][1]) / temp_range
            if progress > 0.85:
                return "finishing"

        return "heating"

    def _assess_confidence(
        self,
        readings: list[tuple[float, float, float]],
        data_span: float,
    ) -> str:
        if data_span > 1800 and len(readings) > 30:
            return "high"
        if data_span > 900:
            return "medium"
        return "low"

    def _exponential_estimate(
        self,
        readings: list[tuple[float, float, float]],
        avg_ambient: float,
        current_temp: float,
    ) -> float | None:
        """Fit linearised exponential and extrapolate to target."""
        t0 = readings[0][0]
        xs: list[float] = []
        ys: list[float] = []

        for ts, ti, _ in readings:
            diff = avg_ambient - ti
            if diff <= 0.5:
                continue
            xs.append(ts - t0)
            ys.append(math.log(diff))

        if len(xs) < self._min_readings:
            return None

        # Least-squares linear regression: y = a + b*x
        n = len(xs)
        sum_x = sum(xs)
        sum_y = sum(ys)
        sum_xy = sum(x * y for x, y in zip(xs, ys))
        sum_x2 = sum(x * x for x in xs)

        denom = n * sum_x2 - sum_x * sum_x
        if abs(denom) < 1e-10:
            return None

        b = (n * sum_xy - sum_x * sum_y) / denom
        k = -b  # b should be negative (temp rising), so k > 0

        if k <= 0:
            return None

        diff_current = avg_ambient - current_temp
        diff_target = avg_ambient - self._target_temp

        if diff_target <= 0 or diff_current <= 0:
            return None

        remaining = -(1.0 / k) * math.log(diff_target / diff_current)
        return remaining if remaining > 0 else None

    def _linear_estimate(
        self,
        now_ts: float,
        current_temp: float,
        rate: float | None,
        phase: str,
        message: str = "",
        confidence: str = "low",
    ) -> PredictionResult:
        """Fallback linear extrapolation."""
        if rate is not None and rate > 0.001:
            remaining = (self._target_temp - current_temp) / rate * 60
            return PredictionResult(
                time_remaining_seconds=remaining,
                eta_timestamp=now_ts + remaining,
                rate_per_minute=rate,
                phase=phase,
                confidence=confidence,
                message=message,
            )
        return PredictionResult(
            phase=phase,
            rate_per_minute=rate,
            confidence=confidence,
            message=message or "Insufficient trend to estimate",
        )
