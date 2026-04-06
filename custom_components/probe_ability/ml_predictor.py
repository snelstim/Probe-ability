"""ML-based cook time predictor using a pre-trained GradientBoostingRegressor.

The model was trained on 178 cooks from a Meater device and achieves ~3.3 min
MAE vs ~35.9 min MAE for the physics-only exponential model.

The model predicts *minutes remaining* from 17 features:
  - 12 numeric: temperatures, rates, elapsed time, deceleration, stall flag
  - 5 categorical: meat category, animal, cut type, cut, doneness preset

The 5 categorical fields are an artefact of Meater's data model. Category and
animal are largely redundant, and cut_type is derivable from cut. Internally
all five are still passed to the model (it was trained that way), but the
user-facing API is simplified to just (cut, doneness) — see _COOK_NAME_MAP.

ml_model_code.py contains the compiled pure-Python GBT; no scikit-learn needed.
"""

from __future__ import annotations

import logging

_LOGGER = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Internal encodings (LabelEncoder alphabetical order, from training data)
# These are implementation details — users never need to touch them.
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
_DONENESS_ENC: dict[str, int] = {
    "rare": 6, "medium_rare": 3, "medium": 2, "medium_well": 4,
    "well_done": 7, "fall_apart": 0, "pulled": 5,
}

# ---------------------------------------------------------------------------
# Cut lookup: cut name → (category_enc, animal_enc, cut_type_enc, cut_enc)
# This derives the three redundant fields automatically from the cut alone.
# Add a new row here when adding cuts not listed below.
# ---------------------------------------------------------------------------

_CUT_LOOKUP: dict[str, tuple[int, int, int, int]] = {
    # Beef steaks
    "sirloin":   (0, 0, 7, _CUT_ENC["sirloin"]),
    "rib_eye":   (0, 0, 7, _CUT_ENC["rib_eye"]),
    "t_bone":    (0, 0, 7, _CUT_ENC["t_bone"]),
    "rump":      (0, 0, 7, _CUT_ENC["rump"]),
    "tomahawk":  (0, 0, 7, _CUT_ENC["tomahawk"]),
    "picanha":   (0, 0, 7, _CUT_ENC["picanha"]),
    "flank":     (0, 0, 7, _CUT_ENC["flank"]),
    "tenderloin":(0, 0, 7, _CUT_ENC["tenderloin"]),
    "steak":     (0, 0, 7, _CUT_ENC["steak"]),
    # Beef roasts / slow cooks
    "brisket":   (0, 0, 5, _CUT_ENC["brisket"]),
    "chuck":     (0, 0, 5, _CUT_ENC["chuck"]),
    "topside":   (0, 0, 5, _CUT_ENC["topside"]),
    "roast":     (0, 0, 5, _CUT_ENC["roast"]),
    # Beef other
    "ground":    (0, 0, 4, _CUT_ENC["ground"]),
    "burger":    (0, 0, 4, _CUT_ENC["burger"]),
    "meatloaf":  (0, 0, 4, _CUT_ENC["meatloaf"]),
    # Pork
    "loin":      (4, 6, 7, _CUT_ENC["loin"]),
    "belly":     (4, 6, 7, _CUT_ENC["belly"]),
    "rib_pork":  (4, 6, 7, _CUT_ENC["rib_pork"]),
    "rib_rack":  (4, 6, 5, _CUT_ENC["rib_rack"]),
    "shoulder":  (4, 6, 5, _CUT_ENC["shoulder"]),
    "butt":      (4, 6, 5, _CUT_ENC["butt"]),
    # Poultry
    "breast":      (5, 1, 0, _CUT_ENC["breast"]),   # chicken
    "duck_breast": (5, 3, 3, _CUT_ENC["breast"]),   # duck: animal=3, cut_type=3
    "thigh":       (5, 1, 0, _CUT_ENC["thigh"]),
    "whole":       (5, 1, 0, _CUT_ENC["whole"]),
    # Lamb
    "leg_lamb":  (2, 4, 5, _CUT_ENC["leg_lamb"]),
    # Fish
    "fillet":    (1, 7, 6, _CUT_ENC["fillet"]),
    # Generic fallback
    "other":     (0, 0, 4, _CUT_ENC["other"]),
}


def _encode(cut: str, doneness: str) -> tuple[int, int, int, int, int]:
    """Encode a (cut, doneness) pair into the 5-tuple the model expects."""
    cat, ani, ctt, cut_e = _CUT_LOOKUP.get(cut, _CUT_LOOKUP["other"])
    prs = _DONENESS_ENC.get(doneness, _DONENESS_ENC["medium"])
    return (cat, ani, ctt, cut_e, prs)


# ---------------------------------------------------------------------------
# Cook-name map — built dynamically from cook_presets.json so adding a new
# preset only requires editing that one JSON file.
# ---------------------------------------------------------------------------

def _build_cook_name_map() -> dict[str, tuple[int, int, int, int, int]]:
    """Load www/probe-ability/cook_presets.json and build the name → encoding map.

    The JSON is located two levels above the component directory:
        config/custom_components/probe_ability/  ← __file__
        config/custom_components/
        config/
        config/www/probe-ability/cook_presets.json

    Falls back to a minimal hardcoded set if the file is missing.
    """
    import json
    from pathlib import Path
    try:
        json_path = Path(__file__).parent.parent.parent / "www" / "probe-ability" / "cook_presets.json"
        data = json.loads(json_path.read_text())
        result: dict[str, tuple[int, int, int, int, int]] = {}
        for cat in data["categories"]:
            for cut in cat["cuts"]:
                for don in cut["doneness"]:
                    name = f"{cat['label']} {cut['label']} {don['label']}"
                    result[name] = _encode(cut["id"], don["id"])
        _LOGGER.debug("Probe-ability: loaded %d presets from cook_presets.json", len(result))
        return result
    except Exception as exc:  # noqa: BLE001
        _LOGGER.warning(
            "Probe-ability: could not load cook_presets.json (%s) — using built-in defaults", exc
        )
        return {
            "Beef Sirloin Medium Rare":        _encode("sirloin",  "medium_rare"),
            "Beef Sirloin Medium":             _encode("sirloin",  "medium"),
            "Beef Sirloin Well Done":          _encode("sirloin",  "well_done"),
            "Pork Loin / Chop Medium":         _encode("loin",     "medium"),
            "Poultry Chicken Breast Medium":   _encode("breast",   "medium"),
            "Lamb Leg Medium Rare":            _encode("leg_lamb", "medium_rare"),
            "Lamb Leg Medium":                 _encode("leg_lamb", "medium"),
            "Beef Brisket Fall Apart":         _encode("brisket",  "fall_apart"),
            "Pork Shoulder Pulled":            _encode("shoulder", "pulled"),
        }


_COOK_NAME_MAP: dict[str, tuple[int, int, int, int, int]] = _build_cook_name_map()

# Fallback encoding for "Custom" or any unrecognised cook name.
_DEFAULT_MEAT: tuple[int, int, int, int, int] = _encode("steak", "medium")

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

    # Ambient statistics.
    # T_ambient_mean_so_far was trained as the whole-cook mean, but a whole-cook
    # mean lags badly when the user changes the oven/smoker temperature mid-cook.
    # We substitute the mean of the most recent 10 readings so the feature
    # reflects the *current* cooking environment while retaining enough history
    # to smooth out single-reading noise.  The model was trained with the
    # whole-cook mean, so this is a pragmatic approximation rather than a true
    # retraining fix — but since the recent mean converges to the whole-cook
    # mean during stable cooks, it degrades gracefully.
    window_amb = ambien[-10:] if len(ambien) >= 10 else ambien
    amb_mean   = sum(window_amb) / len(window_amb)
    # Std is computed over the same recent window for consistency.
    amb_std    = (sum((a - amb_mean) ** 2 for a in window_amb) / len(window_amb)) ** 0.5 if len(window_amb) > 1 else 0.0

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
# MLPredictor — pure-Python inference, no scikit-learn required
# ---------------------------------------------------------------------------

class MLPredictor:
    """Runs cook-time predictions using a pure-Python GBT implementation.

    The model is compiled into ml_model_code.py (base64-encoded struct data +
    a tiny traversal function) so no scikit-learn or other ML library is needed.
    """

    def __init__(self) -> None:
        self._score_fn = None
        self._load_attempted = False

    def _load(self) -> bool:
        if self._score_fn is not None:
            return True
        if self._load_attempted:
            return False
        self._load_attempted = True
        try:
            from .ml_model_code import score  # noqa: PLC0415
            self._score_fn = score
            _LOGGER.info("Probe-ability: ML model loaded (pure-Python, no scikit-learn required)")
            return True
        except Exception as exc:  # noqa: BLE001
            _LOGGER.warning("Probe-ability: ML model unavailable (%s) — using physics model", exc)
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
            row = [feats[k] for k in _FEATURE_ORDER]
            return max(0.0, float(self._score_fn(row)))
        except Exception as exc:  # noqa: BLE001
            _LOGGER.debug("Probe-ability: ML predict error (%s)", exc)
            return None


# Module-level singleton shared across all CookPredictor instances.
ml_predictor = MLPredictor()
