"""Cook prediction engine with ML primary model and physics fallback.

Primary: GradientBoostingRegressor (ml_predictor.py / model.pkl).
Fallback: Newton's Law of Heating exponential curve fit.

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
    phase: str = "collecting"  # collecting | heating | stall | finishing | done | unreachable
    confidence: str = "low"  # low | medium | high
    message: str = ""
    prediction_model: str = ""  # "ml" | "physics" | "" during collecting


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

        # Cook name — used by the ML model to select the meat taxonomy encoding.
        # Set by CookMonitor when a cook starts; defaults to "" (triggers fallback).
        self.cook_name: str = ""

        # Internal temperature at the very first reading — ML feature T_internal_start.
        self._start_temp: float | None = None

        # Smoothed time-remaining (seconds) — updated via EMA on every valid
        # prediction so short-term rate noise doesn't cause large display swings.
        # Also served back during stalls / zero-rate moments.
        self._last_stable_remaining: float | None = None

        # Timestamp of the reading that produced _last_stable_remaining.
        # Used to (a) decay the served value so a stale estimate counts down
        # instead of freezing, and (b) stop serving it entirely once it is
        # older than _stale_max_seconds.
        self._last_stable_ts: float | None = None

        # Recent fresh ETA estimates (ts, eta) — confidence is derived from
        # how much these agree.  Stale-served values are deliberately NOT
        # recorded: serving holds the ETA constant by construction, which
        # would fake perfect stability.
        self._recent_etas: list[tuple[float, float]] = []

        # Once the target is reached the cook stays done: meat doesn't
        # un-cook, and without the latch a 0.1°C probe dip below the
        # tolerance line resurrects a large ETA at the cook's peak.
        self._done_latched: bool = False

        # EMA smoothing factor: lower = more stable, slower to react to real
        # changes.  0.15 → a sudden step is ~50% reflected after 4–5 updates
        # (≈2 min at 30 s/reading).
        # When ambient changes significantly (user cranks smoker/oven), the alpha
        # is boosted automatically by _adaptive_alpha() so predictions catch up
        # faster without making normal stable-ambient cooks jumpy.
        self._ema_alpha: float = 0.15

        # Tuning constants
        self._min_readings = 10
        self._min_data_seconds = 600  # 10 min before first prediction
        self._window_seconds = 2400  # 40 min sliding window for fit
        self._rate_window_seconds = 300  # 5 min window for instantaneous rate
        self._stall_threshold_c = 0.5  # <0.5°C change over stall window = stall
        self._stall_check_seconds = 600  # 10 min sustained = stall
        self._stale_max_seconds = 300  # serve a stale estimate for max 5 min
        self._done_tolerance_c = 0.5  # probe accuracy; within this of target = done
        self._unreachable_window_seconds = 180  # ambient < target this long = unreachable
        self._unreachable_rise_rate = 0.5  # °C/min ambient rise that still counts as preheating
        self._eta_history_seconds = 600  # confidence looks at ETA agreement over this window
        self._eta_history_min = 4  # need this many fresh ETAs before confidence can rise
        self._eta_std_high = 90.0  # ETA std-dev (s) below which confidence may be high
        self._eta_std_medium = 420.0  # ...below which confidence may be medium
        self._linear_max_seconds = 4 * 3600  # linear ETA beyond this = rate is noise
        self._jump_reject_limit = 4  # consecutive implausible jumps before accepting
        self._jump_rejects = 0
        self._last_reject_ts: float | None = None

    @property
    def target_temp(self) -> float:
        return self._target_temp

    @target_temp.setter
    def target_temp(self, value: float) -> None:
        if value == self._target_temp:
            return
        self._target_temp = value
        # Re-evaluate the done latch against the new target: raising the
        # target mid-cook must un-latch, lowering it below the peak latches.
        peak = max((ti for _, ti, _ in self.readings), default=None)
        self._done_latched = (
            peak is not None and peak >= value - self._done_tolerance_c
        )

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
        if self._start_temp is None:
            self._start_temp = internal_temp

    def reset(self) -> None:
        """Clear all readings and derived state for a new cook."""
        self.readings.clear()
        self._start_temp = None
        self._last_stable_remaining = None
        self._last_stable_ts = None
        self._recent_etas.clear()
        self._done_latched = False

    def to_dict(self) -> dict:
        """Serialise state for persistence."""
        return {
            "target_temp": self._target_temp,
            "readings": self.readings,
            "last_stable_remaining": self._last_stable_remaining,
            "last_stable_ts": self._last_stable_ts,
            "cook_name": self.cook_name,
            "start_temp": self._start_temp,
            "done_latched": self._done_latched,
        }

    @classmethod
    def from_dict(cls, data: dict) -> CookPredictor:
        """Restore from serialised state."""
        predictor = cls(target_temp=data["target_temp"])
        predictor.readings = [tuple(r) for r in data.get("readings", [])]
        predictor._last_stable_remaining = data.get("last_stable_remaining")
        predictor._last_stable_ts = data.get("last_stable_ts")
        predictor.cook_name = data.get("cook_name", "")
        predictor._start_temp = data.get("start_temp")
        predictor._done_latched = data.get("done_latched", False)
        return predictor

    def predict(self) -> PredictionResult:
        """Run prediction based on collected readings."""
        # Done?  Within probe accuracy of target counts — holding out for the
        # exact reading keeps the countdown alive on a cook that is finished
        # for every practical purpose.  Latched: once reached, the cook stays
        # done even if the reading dips afterwards (meat doesn't un-cook).
        if self.readings:
            now_ts, current_temp, _ = self.readings[-1]
            if self._done_latched or current_temp >= self._target_temp - self._done_tolerance_c:
                self._done_latched = True
                return PredictionResult(
                    time_remaining_seconds=0,
                    eta_timestamp=now_ts,
                    phase="done",
                    confidence="high",
                    message="Target temperature reached",
                )

        if len(self.readings) < self._min_readings:
            return PredictionResult(
                phase="collecting",
                message=(
                    f"Collecting data ({len(self.readings)}/{self._min_readings} readings)"
                ),
            )

        now_ts, current_temp, _ = self.readings[-1]

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

        # Target thermodynamically unreachable: ambient has been below the
        # target for a sustained period and isn't rising, so the meat cannot
        # get there.  An honest "won't finish at this heat" beats fabricating
        # an ETA (fire died, lid open, cooker turned off...).
        if self._target_unreachable():
            return PredictionResult(
                phase="unreachable",
                confidence="high",
                message=(
                    "Ambient temperature is below the target — the target "
                    "cannot be reached unless the heat is increased"
                ),
            )

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
            if result.time_remaining_seconds is not None:
                result.time_remaining_seconds = self._gate_fresh(
                    result.time_remaining_seconds, now_ts
                )
            if result.time_remaining_seconds is not None and result.time_remaining_seconds > 0:
                smoothed = self._smooth(result.time_remaining_seconds)
                self._last_stable_remaining = smoothed
                self._last_stable_ts = now_ts
                self._record_eta(now_ts, smoothed)
                result.time_remaining_seconds = smoothed
                result.eta_timestamp = now_ts + smoothed
            elif result.time_remaining_seconds is None:
                stale = self._serve_stale(now_ts)
                if stale is not None:
                    result.time_remaining_seconds = stale
                    result.eta_timestamp = now_ts + stale
                    result.confidence = "low"  # served, not computed
            return result

        # Primary: ML model (falls back to physics if model unavailable)
        ml_remaining = self._ml_estimate()
        if ml_remaining is not None:
            remaining = ml_remaining
            used_model = "ml"
        else:
            remaining = self._exponential_estimate(windowed, avg_ambient, current_temp)
            used_model = "physics"

        if remaining is not None:
            remaining = self._gate_fresh(remaining, now_ts)
        if remaining is not None and remaining > 0:
            remaining = self._smooth(remaining)
            self._last_stable_remaining = remaining
            self._last_stable_ts = now_ts
            self._record_eta(now_ts, remaining)
            return PredictionResult(
                time_remaining_seconds=remaining,
                eta_timestamp=now_ts + remaining,
                rate_per_minute=rate,
                phase=phase,
                confidence=confidence,
                prediction_model=used_model,
            )

        # Fallback: linear
        result = self._linear_estimate(
            now_ts, current_temp, rate, phase,
            message="Exponential fit failed; using linear estimate",
            confidence=confidence,
        )
        if result.time_remaining_seconds is not None:
            result.time_remaining_seconds = self._gate_fresh(
                result.time_remaining_seconds, now_ts
            )
        if result.time_remaining_seconds is not None and result.time_remaining_seconds > 0:
            smoothed = self._smooth(result.time_remaining_seconds)
            self._last_stable_remaining = smoothed
            self._last_stable_ts = now_ts
            self._record_eta(now_ts, smoothed)
            result.time_remaining_seconds = smoothed
            result.eta_timestamp = now_ts + smoothed
        elif result.time_remaining_seconds is None:
            # Rate is too low / direction reversed to compute a fresh estimate.
            # Serve a decayed version of the last known-good value so the
            # display doesn't blank out during a momentary flat spot — but
            # only briefly (see _serve_stale); a long gap means the estimate
            # is genuinely unknown and pretending otherwise misleads.
            stale = self._serve_stale(now_ts)
            if stale is not None:
                result.time_remaining_seconds = stale
                result.eta_timestamp = now_ts + stale
                result.confidence = "low"  # served, not computed
        return result

    def _ml_estimate(self) -> float | None:
        """Return ML-predicted seconds remaining, or None if unavailable.

        Imports ml_predictor lazily so the module works without scikit-learn
        installed (HA will log a warning and fall back to the physics model).
        """
        try:
            from .ml_predictor import ml_predictor  # noqa: PLC0415
        except Exception:  # noqa: BLE001
            return None
        if len(self.readings) < self._min_readings:
            return None
        result = ml_predictor.predict(
            readings=self.readings,
            target_temp=self._target_temp,
            cook_name=self.cook_name,
            start_temp=self._start_temp if self._start_temp is not None else self.readings[0][1],
        )
        return result * 60.0 if result is not None else None

    def _adaptive_alpha(self) -> float:
        """EMA weight for the current update.

        Normally returns the base alpha (0.15) for stable, noise-free smoothing.
        When the ambient temperature has recently jumped (user cranked the smoker
        or oven mid-cook), we boost alpha so predictions respond within 2–3
        readings rather than 20+, then let it decay back once things stabilise.

        Formula: compare the mean of the last 5 ambient readings against the
        mean of all earlier readings.  Each extra 10 °C of step adds 0.1 to
        alpha, capped at 0.7.
        """
        n = len(self.readings)
        if n < 10:
            return self._ema_alpha
        recent = [r[2] for r in self.readings[-5:]]
        prior  = [r[2] for r in self.readings[:-5]]
        recent_mean = sum(recent) / len(recent)
        prior_mean  = sum(prior)  / len(prior)
        delta = abs(recent_mean - prior_mean)
        boost = delta / 10.0 * 0.1          # +0.1 per 10 °C step
        return min(0.7, self._ema_alpha + boost)

    def _smooth(self, new_value: float) -> float:
        """Blend a new estimate with the previous one via EMA.

        First call (no previous value) returns the raw value so we don't
        start with a biased estimate.  Uses _adaptive_alpha() so the smoothing
        automatically reacts faster when the ambient temperature has changed.
        """
        if self._last_stable_remaining is None:
            return new_value
        # Don't blend against an estimate that has gone stale (e.g. after a
        # long stall) — it would drag fresh estimates toward outdated history.
        if (
            self._last_stable_ts is not None
            and self.readings
            and self.readings[-1][0] - self._last_stable_ts > self._stale_max_seconds
        ):
            return new_value
        alpha = self._adaptive_alpha()
        return alpha * new_value + (1 - alpha) * self._last_stable_remaining

    def _target_unreachable(self) -> bool:
        """True when ambient has stayed below target long enough that the
        internal temperature physically cannot reach it.

        Two conditions, both over the last _unreachable_window_seconds:
          1. Every ambient reading is below the target temperature.
          2. Ambient is not meaningfully rising (rules out an actively
             preheating cooker, where "below target" is temporary).
        """
        now_ts = self.readings[-1][0]
        cutoff = now_ts - self._unreachable_window_seconds
        window = [r for r in self.readings if r[0] >= cutoff]
        # Sparse data (probe dropouts, long reading gaps) can leave too few
        # readings inside the window — include the newest reading before the
        # cutoff so the window genuinely spans the check period.
        bound_idx = len(self.readings) - len(window) - 1
        if bound_idx >= 0:
            window.insert(0, self.readings[bound_idx])
        if len(window) < 2 or window[-1][0] - window[0][0] < self._unreachable_window_seconds * 0.8:
            return False
        if any(ta >= self._target_temp for _, _, ta in window):
            return False
        dt_min = (window[-1][0] - window[0][0]) / 60.0
        ambient_rise_rate = (window[-1][2] - window[0][2]) / dt_min
        return ambient_rise_rate <= self._unreachable_rise_rate

    def _gate_fresh(self, fresh: float, now_ts: float) -> float | None:
        """Reject a fresh estimate that leaps implausibly above the last one.

        Stall exits produce near-zero heating rates whose extrapolations can
        claim many extra hours in a single step; accepting one such value
        poisons the EMA and the stale-serving baseline for minutes afterwards.
        A genuine slowdown re-asserts itself on every subsequent reading, so
        after _jump_reject_limit consecutive rejected readings the new level
        is accepted as real.
        """
        base = self._last_stable_remaining
        if base is None:
            self._jump_rejects = 0
            return fresh
        cap = max(base * 2.0, base + 1800.0)
        if fresh > cap:
            if self._last_reject_ts != now_ts:  # count once per reading
                self._jump_rejects += 1
                self._last_reject_ts = now_ts
            if self._jump_rejects <= self._jump_reject_limit:
                return None
        self._jump_rejects = 0
        return fresh

    def _serve_stale(self, now_ts: float) -> float | None:
        """Return a decayed version of the last stable estimate, or None.

        Holds the original ETA fixed: if we said N seconds remaining at time
        T0, at time T we serve N - (T - T0) so the countdown keeps moving
        instead of freezing.  Returns None once the estimate is older than
        _stale_max_seconds or its ETA has already passed — at that point an
        honest "no estimate" beats a fabricated number.
        """
        if self._last_stable_remaining is None or self._last_stable_ts is None:
            return None
        age = now_ts - self._last_stable_ts
        if age > self._stale_max_seconds:
            return None
        remaining = self._last_stable_remaining - age
        return remaining if remaining > 0 else None

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

    def _record_eta(self, now_ts: float, remaining: float) -> None:
        """Record a freshly computed ETA for confidence assessment."""
        self._recent_etas.append((now_ts, now_ts + remaining))
        cutoff = now_ts - self._eta_history_seconds
        self._recent_etas = [(t, e) for t, e in self._recent_etas if t >= cutoff]

    def _assess_confidence(
        self,
        readings: list[tuple[float, float, float]],
        data_span: float,
    ) -> str:
        """Confidence = data quantity cap ∧ ETA stability.

        Elapsed time alone says nothing about whether the estimate is any
        good — a cook can run for hours while predictions swing wildly.  So
        the old clock-based tiers only *cap* confidence; to actually reach a
        tier, the recent fresh ETAs must agree with each other (low std-dev
        of predicted finish times).
        """
        # Data-quantity cap (the old behaviour, demoted to an upper bound)
        if data_span > 1800 and len(readings) > 30:
            cap = 3
        elif data_span > 900:
            cap = 2
        else:
            cap = 1

        now_ts = self.readings[-1][0]
        cutoff = now_ts - self._eta_history_seconds
        etas = [e for t, e in self._recent_etas if t >= cutoff]
        if len(etas) < self._eta_history_min:
            stability = 1
        else:
            mean = sum(etas) / len(etas)
            std = (sum((e - mean) ** 2 for e in etas) / len(etas)) ** 0.5
            if std < self._eta_std_high:
                stability = 3
            elif std < self._eta_std_medium:
                stability = 2
            else:
                stability = 1

        return ("low", "medium", "high")[min(cap, stability) - 1]

    def _exponential_estimate(
        self,
        readings: list[tuple[float, float, float]],
        avg_ambient: float,  # kept for API compatibility but not used for k fit
        current_temp: float,
    ) -> float | None:
        """Estimate remaining time using Newton's Law of Heating.

        The classic linearised fit (ln(T_amb - T_int) vs time) assumes constant
        ambient, which breaks badly when the user cranks the smoker mid-cook.

        Instead we estimate the heat-transfer coefficient k directly from
        consecutive reading pairs:

            k  =  (dT_internal / dt)  /  (T_ambient(t) - T_internal(t))

        This is valid even when T_ambient changes over time.  We then project
        remaining time using the *current* ambient so an immediate oven-temp
        change is reflected in the very next prediction rather than waiting for
        the window average to catch up.
        """
        k_values: list[float] = []
        for i in range(1, len(readings)):
            t0r, ti0, ta0 = readings[i - 1]
            t1r, ti1, ta1 = readings[i]
            dt = t1r - t0r
            if dt < 5:
                continue
            # Average conditions across the interval
            avg_gap = ((ta0 - ti0) + (ta1 - ti1)) / 2.0
            if avg_gap < 1.0:
                continue
            k = ((ti1 - ti0) / dt) / avg_gap   # in s⁻¹
            if 1e-6 < k < 0.1:                 # sanity bounds
                k_values.append(k)

        if len(k_values) < 3:
            return None

        # Robust mean: drop values more than 2 std-devs from the median to
        # reduce the influence of noisy readings (probe contact, lid opening).
        k_values.sort()
        mid = len(k_values) // 2
        k_med = k_values[mid]
        variance = sum((v - k_med) ** 2 for v in k_values) / len(k_values)
        k_std = variance ** 0.5
        filtered = [v for v in k_values if abs(v - k_med) <= 2 * k_std] if k_std > 0 else k_values
        k = sum(filtered) / len(filtered)

        if k <= 0:
            return None

        # Project using the *current* ambient so a mid-cook temperature change
        # is immediately reflected — not damped by the window history.
        current_amb = readings[-1][2]
        diff_current = current_amb - current_temp
        diff_target  = current_amb - self._target_temp

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
        """Fallback linear extrapolation.

        A projection beyond _linear_max_seconds means the rate is noise
        relative to the remaining gap (typical at stall entry/exit) — no
        estimate is more honest than a many-hour extrapolation.
        """
        if rate is not None and rate > 0.001:
            remaining = (self._target_temp - current_temp) / rate * 60
            if remaining > self._linear_max_seconds:
                return PredictionResult(
                    phase=phase,
                    rate_per_minute=rate,
                    confidence=confidence,
                    prediction_model="physics",
                    message=message or "Insufficient trend to estimate",
                )
            return PredictionResult(
                time_remaining_seconds=remaining,
                eta_timestamp=now_ts + remaining,
                rate_per_minute=rate,
                phase=phase,
                confidence=confidence,
                message=message,
                prediction_model="physics",
            )
        return PredictionResult(
            phase=phase,
            rate_per_minute=rate,
            confidence=confidence,
            prediction_model="physics",
            message=message or "Insufficient trend to estimate",
        )
