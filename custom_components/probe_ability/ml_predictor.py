"""ML-based cook time predictor using a pre-trained GradientBoostingRegressor.

The model was trained on 178 cooks from a Meater device and achieves ~3.3 min
MAE vs ~35.9 min MAE for the physics-only exponential model.

The model predicts *minutes remaining* from 17 features:
  - 12 numeric: temperatures, rates, elapsed time, deceleration, stall flag
  - 5 categorical: meat category, animal, cut type, cut, doneness preset

If model.pkl is not present or scikit-learn is unavailable, this module
returns None from predict() and the caller falls back to the physics model.
"""

from __future__ import annotations

import logging
import os

_LOGGER = logging.getLogger(__name__)

_MODEL_PATH = os.path.join(os.path.dirname(__file__), "model.pkl")

# ---------------------------------------------------------------------------
# Categorical encodings
# Reconstructed from cook_summaries.csv unique values; LabelEncoder sorts
# alphabetically and assigns integer codes 0, 1, 2, …
# ---------------------------------------------------------------------------

_CATEGORY_ENC: dict[str, int] = {
    "beef": 0, "fish": 1, "lamb": 2, "other": 3, "pork": 4, "poultry": 5,
}
_ANIMAL_ENC: dict[str, int] = {
    "beef": 0, "chicken": 1, "cod": 2, "duck": 3, "lamb": 4,
    "other": 5, "pork": 6, "salmon": 7, "venison": 8, "wild_salmon": 9,
}
_CUT_TYPE_ENC: dict[str, int] = {
    "chicken": 0, "chop": 1, "cod": 2, "duck": 3, "other": 4,
    "roast": 5, "salmon": 6, "steak": 7, "venison": 8, "wild_salmon": 9,
}
_CUT_ENC: dict[str, int] = {
    "belly": 0, "breast": 1, "brisket": 2, "burger": 3, "butt": 4,
    "chuck": 5, "fillet": 6, "flank": 7, "ground": 8, "leg_lamb": 9,
    "loin": 10, "meatloaf": 11, "other": 12, "picanha": 13, "rib": 14,
    "rib_eye": 15, "rib_pork": 16, "rib_rack": 17, "roast": 18, "rump": 19,
    "shoulder": 20, "sirloin": 21, "steak": 22, "t_bone": 23,
    "tenderloin": 24, "thigh": 25, "tomahawk": 26, "topside": 27, "whole": 28,
}
_PRESET_ENC: dict[str, int] = {
    "fall_apart": 0, "meater_recommends": 1, "medium": 2, "medium_rare": 3,
    "medium_well": 4, "pulled": 5, "rare": 6, "well_done": 7,
}

# Probe-ability preset name → (category, animal, cut_type, cut, preset) encoded
# tuple using the dicts above.
_COOK_NAME_MAP: dict[str, tuple[int, int, int, int, int]] = {
    "Beef (Medium Rare)": (_CATEGORY_ENC["beef"],    _ANIMAL_ENC["beef"],    _CUT_TYPE_ENC["steak"], _CUT_ENC["steak"],    _PRESET_ENC["medium_rare"]),
    "Beef (Medium)":      (_CATEGORY_ENC["beef"],    _ANIMAL_ENC["beef"],    _CUT_TYPE_ENC["steak"], _CUT_ENC["steak"],    _PRESET_ENC["medium"]),
    "Beef (Well Done)":   (_CATEGORY_ENC["beef"],    _ANIMAL_ENC["beef"],    _CUT_TYPE_ENC["steak"], _CUT_ENC["steak"],    _PRESET_ENC["well_done"]),
    "Pork":               (_CATEGORY_ENC["pork"],    _ANIMAL_ENC["pork"],    _CUT_TYPE_ENC["steak"], _CUT_ENC["loin"],     _PRESET_ENC["meater_recommends"]),
    "Chicken / Poultry":  (_CATEGORY_ENC["poultry"], _ANIMAL_ENC["chicken"], _CUT_TYPE_ENC["chicken"],_CUT_ENC["breast"],  _PRESET_ENC["meater_recommends"]),
    "Lamb (Medium Rare)": (_CATEGORY_ENC["lamb"],    _ANIMAL_ENC["lamb"],    _CUT_TYPE_ENC["steak"], _CUT_ENC["other"],    _PRESET_ENC["medium_rare"]),
    "Lamb (Medium)":      (_CATEGORY_ENC["lamb"],    _ANIMAL_ENC["lamb"],    _CUT_TYPE_ENC["steak"], _CUT_ENC["other"],    _PRESET_ENC["medium"]),
    "Brisket":            (_CATEGORY_ENC["beef"],    _ANIMAL_ENC["beef"],    _CUT_TYPE_ENC["roast"], _CUT_ENC["brisket"],  _PRESET_ENC["fall_apart"]),
    "Pulled Pork":        (_CATEGORY_ENC["pork"],    _ANIMAL_ENC["pork"],    _CUT_TYPE_ENC["roast"], _CUT_ENC["shoulder"], _PRESET_ENC["pulled"]),
}
# Default when cook_name is "Custom" or not in the map: beef steak medium
_DEFAULT_MEAT: tuple[int, int, int, int, int] = (
    _CATEGORY_ENC["beef"], _ANIMAL_ENC["beef"],
    _CUT_TYPE_ENC["steak"], _CUT_ENC["other"],
    _PRESET_ENC["medium"],
)

# Feature order must match the column order used during training exactly.
_FEATURE_ORDER: list[str] = [
    "T_internal_current", "T_ambient_current", "rate_initial", "rate_recent",
    "deceleration", "T_internal_start", "T_remaining", "elapsed_min",
    "T_ambient_mean_so_far", "T_ambient_std_so_far", "in_stall", "T_gap",
    "category_enc", "animal_enc", "cut_type_enc", "cut_enc", "preset_enc",
]


# ---------------------------------------------------------------------------
# Feature engineering
# ---------------------------------------------------------------------------

def _compute_rate(times_s: list[float], temps: list[float], window_s: float) -> float:
    """Rate of temperature change in °C/min over the most recent ``window_s`` seconds."""
    if len(times_s) < 2:
        return 0.0
    cutoff = times_s[-1] - window_s
    # Keep readings in the window; fall back to all readings if fewer than 2 qualify.
    idx = [i for i, t in enumerate(times_s) if t >= cutoff]
    if len(idx) < 2:
        idx = list(range(len(times_s)))
    t0, t1 = times_s[idx[0]], times_s[idx[-1]]
    T0, T1 = temps[idx[0]], temps[idx[-1]]
    dt = t1 - t0
    return 0.0 if dt <= 0 else (T1 - T0) / (dt / 60.0)


def _build_features(
    readings: list[tuple[float, float, float]],
    target_temp: float,
    cook_name: str,
    start_temp: float,
) -> dict[str, float]:
    """Build the 17-feature dict expected by the model."""
    times_abs = [r[0] for r in readings]
    intern    = [r[1] for r in readings]
    ambien    = [r[2] for r in readings]

    t0 = times_abs[0]
    times_rel = [t - t0 for t in times_abs]

    rate_initial = _compute_rate(times_rel, intern, 600.0)   # first 10 min
    rate_recent  = _compute_rate(times_rel, intern, 300.0)   # last 5 min
    decel = rate_recent / rate_initial if abs(rate_initial) > 0.01 else 1.0

    T_current  = intern[-1]
    amb_recent = sum(ambien[-3:]) / min(len(ambien), 3)

    # Training definition of in_stall: rate < 0.2°C/min AND in the 60-80°C zone
    in_stall = 1.0 if (abs(rate_recent) < 0.2 and 60 <= T_current <= 80) else 0.0

    # Ambient statistics across the whole cook so far
    amb_mean = sum(ambien) / len(ambien)
    amb_std  = (sum((a - amb_mean) ** 2 for a in ambien) / len(ambien)) ** 0.5 if len(ambien) > 1 else 0.0

    cat, ani, ctt, cut, prs = _COOK_NAME_MAP.get(cook_name, _DEFAULT_MEAT)

    return {
        "T_internal_current":    T_current,
        "T_ambient_current":     amb_recent,
        "rate_initial":          rate_initial,
        "rate_recent":           rate_recent,
        "deceleration":          decel,
        "T_internal_start":      float(start_temp),
        "T_remaining":           target_temp - T_current,
        "elapsed_min":           float(times_rel[-1]) / 60.0,
        "T_ambient_mean_so_far": amb_mean,
        "T_ambient_std_so_far":  amb_std,
        "in_stall":              in_stall,
        "T_gap":                 amb_recent - T_current,
        "category_enc":          float(cat),
        "animal_enc":            float(ani),
        "cut_type_enc":          float(ctt),
        "cut_enc":               float(cut),
        "preset_enc":            float(prs),
    }


# ---------------------------------------------------------------------------
# MLPredictor — lazy-loading singleton
# ---------------------------------------------------------------------------

class MLPredictor:
    """Wraps the pre-trained GradientBoostingRegressor for cook-time prediction."""

    def __init__(self) -> None:
        self._model = None
        self._load_attempted = False

    def _load(self) -> bool:
        if self._model is not None:
            return True
        if self._load_attempted:
            return False
        self._load_attempted = True
        if not os.path.exists(_MODEL_PATH):
            _LOGGER.debug("Probe-ability: model.pkl not found at %s — using physics model", _MODEL_PATH)
            return False
        try:
            import pickle  # noqa: PLC0415
            with open(_MODEL_PATH, "rb") as fh:
                self._model = pickle.load(fh)  # noqa: S301
            _LOGGER.info("Probe-ability: ML model loaded from %s", _MODEL_PATH)
            return True
        except Exception as exc:  # noqa: BLE001
            _LOGGER.warning("Probe-ability: ML model failed to load (%s) — using physics model", exc)
            return False

    def predict(
        self,
        readings: list[tuple[float, float, float]],
        target_temp: float,
        cook_name: str,
        start_temp: float,
    ) -> float | None:
        """Return predicted minutes remaining, or None if unavailable.

        ``readings`` is the full list of (timestamp, internal_temp, ambient_temp)
        tuples collected so far for this cook.
        """
        if not self._load():
            return None
        try:
            feats = _build_features(readings, target_temp, cook_name, start_temp)
            row = [[feats[k] for k in _FEATURE_ORDER]]
            result = self._model.predict(row)[0]
            return max(0.0, float(result))
        except Exception as exc:  # noqa: BLE001
            _LOGGER.debug("Probe-ability: ML predict error (%s)", exc)
            return None


# Module-level singleton shared across all CookPredictor instances.
ml_predictor = MLPredictor()
