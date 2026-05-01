#!/usr/bin/env python3
"""Retrain the Probe-ability ML model from cook exports.

Usage
-----
    python retrain.py [--pa-exports PATH] [--output-dir PATH] [--supabase-key KEY]

    --pa-exports PATH    probe_ability CSV exports directory
                         (default: ./probe_ability_exports)
    --output-dir PATH    where to write artefacts
                         (default: ./retrain_output)
    --supabase-key KEY   Supabase service role key to pull shared cooks
                         (or set SUPABASE_SERVICE_KEY env var)

What it does
------------
1. Loads original Meater exports from   meater_exports/
2. Loads probe_ability exports from     probe_ability_exports/  (or --pa-exports)
3. Loads anonymously shared cooks from  Supabase  (if SUPABASE_SERVICE_KEY is set)
4. Re-engineers features with corrected definitions that now match inference:
     in_stall            : 40–80 °C  (was 60–80 °C)
     T_ambient_mean_so_far: last 10 readings  (was whole-cook mean)
5. Trains a GradientBoostingRegressor with GroupKFold cross-validation
6. Compiles the model to   custom_components/probe_ability/ml_model_code.py
7. Writes a short accuracy report to   retrain_output/retrain_report.txt

Copying probe_ability exports from Home Assistant
-------------------------------------------------
    scp homeassistant:/config/probe_ability_exports/*.csv ./probe_ability_exports/

Using shared Supabase data
--------------------------
    export SUPABASE_SERVICE_KEY="eyJ..."   # service_role key from Supabase dashboard
    python retrain.py

Requirements
------------
    pip install scikit-learn numpy requests
"""

from __future__ import annotations

import argparse
import base64
import csv
import glob
import json
import math
import os
import re
import struct
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

# ── Encoding maps — must match ml_predictor.py exactly ───────────────────────

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
_CUT_LOOKUP: dict[str, tuple[int, int, int, int]] = {
    "sirloin":    (0, 0, 7, _CUT_ENC["sirloin"]),
    "rib_eye":    (0, 0, 7, _CUT_ENC["rib_eye"]),
    "t_bone":     (0, 0, 7, _CUT_ENC["t_bone"]),
    "rump":       (0, 0, 7, _CUT_ENC["rump"]),
    "tomahawk":   (0, 0, 7, _CUT_ENC["tomahawk"]),
    "picanha":    (0, 0, 7, _CUT_ENC["picanha"]),
    "flank":      (0, 0, 7, _CUT_ENC["flank"]),
    "tenderloin": (0, 0, 7, _CUT_ENC["tenderloin"]),
    "steak":      (0, 0, 7, _CUT_ENC["steak"]),
    "brisket":    (0, 0, 5, _CUT_ENC["brisket"]),
    "chuck":      (0, 0, 5, _CUT_ENC["chuck"]),
    "topside":    (0, 0, 5, _CUT_ENC["topside"]),
    "roast":      (0, 0, 5, _CUT_ENC["roast"]),
    "ground":     (0, 0, 4, _CUT_ENC["ground"]),
    "burger":     (0, 0, 4, _CUT_ENC["burger"]),
    "meatloaf":   (0, 0, 4, _CUT_ENC["meatloaf"]),
    "loin":       (4, 6, 7, _CUT_ENC["loin"]),
    "belly":      (4, 6, 7, _CUT_ENC["belly"]),
    "rib_pork":   (4, 6, 7, _CUT_ENC["rib_pork"]),
    "rib_rack":   (4, 6, 5, _CUT_ENC["rib_rack"]),
    "shoulder":   (4, 6, 5, _CUT_ENC["shoulder"]),
    "butt":       (4, 6, 5, _CUT_ENC["butt"]),
    "breast":     (5, 1, 0, _CUT_ENC["breast"]),
    "duck_breast":(5, 3, 3, _CUT_ENC["breast"]),
    "thigh":      (5, 1, 0, _CUT_ENC["thigh"]),
    "whole":      (5, 1, 0, _CUT_ENC["whole"]),
    "leg_lamb":   (2, 4, 5, _CUT_ENC["leg_lamb"]),
    "fillet":     (1, 7, 6, _CUT_ENC["fillet"]),
    "other":      (3, 5, 4, _CUT_ENC["other"]),
}
_MEAT_FALLBACK = (3, 5, 4, _CUT_ENC["other"], _DONENESS_ENC["medium"])

# ── Preset → target internal temperature ──────────────────────────────────────
# Matches cook_presets.json values so T_remaining is consistent with inference.
# "meater_recommends" falls back to a safe per-category default.

_PRESET_TARGETS: dict[str, dict[str, float]] = {
    "beef":    {"rare": 50.0, "medium_rare": 54.0, "medium": 60.0,
                "medium_well": 65.0, "well_done": 71.0,
                "pulled": 96.0, "fall_apart": 96.0, "meater_recommends": 60.0},
    "pork":    {"rare": 63.0, "medium_rare": 63.0, "medium": 63.0,
                "medium_well": 67.0, "well_done": 71.0,
                "pulled": 96.0, "fall_apart": 93.0, "meater_recommends": 71.0},
    "poultry": {"rare": 74.0, "medium_rare": 74.0, "medium": 74.0,
                "medium_well": 74.0, "well_done": 82.0,
                "pulled": 82.0, "fall_apart": 82.0, "meater_recommends": 74.0},
    "lamb":    {"rare": 52.0, "medium_rare": 57.0, "medium": 63.0,
                "medium_well": 68.0, "well_done": 74.0,
                "pulled": 85.0, "fall_apart": 85.0, "meater_recommends": 63.0},
    "fish":    {"rare": 50.0, "medium_rare": 52.0, "medium": 60.0,
                "medium_well": 65.0, "well_done": 68.0,
                "pulled": 60.0, "fall_apart": 60.0, "meater_recommends": 60.0},
    "other":   {"rare": 60.0, "medium_rare": 63.0, "medium": 70.0,
                "medium_well": 72.0, "well_done": 77.0,
                "pulled": 96.0, "fall_apart": 96.0, "meater_recommends": 70.0},
}
_PRESET_TARGET_DEFAULT = 70.0


def _preset_to_target(category: str, preset: str) -> float:
    """Return the target internal temperature for a given (category, preset) pair."""
    return _PRESET_TARGETS.get(category, {}).get(preset, _PRESET_TARGET_DEFAULT)
_FEATURE_ORDER = [
    "T_internal_current", "T_ambient_current", "rate_initial", "rate_recent",
    "deceleration", "T_internal_start", "T_remaining", "elapsed_min",
    "T_ambient_mean_so_far", "T_ambient_std_so_far", "in_stall", "T_gap",
    "category_enc", "animal_enc", "cut_type_enc", "cut_enc", "preset_enc",
]


# ── Meat encoding helpers ─────────────────────────────────────────────────────

def meater_strings_to_meat(category: str, animal: str, cut_type: str,
                            cut: str, preset: str) -> tuple[int, ...]:
    """Convert raw Meater export string columns to a 5-int encoding tuple."""
    return (
        _CATEGORY_ENC.get(category, 3),
        _ANIMAL_ENC.get(animal,   5),
        _CUT_TYPE_ENC.get(cut_type, 4),
        _CUT_ENC.get(cut,          12),
        _DONENESS_ENC.get(preset,  2),
    )


def cook_name_to_meat(cook_name: str, presets: dict | None) -> tuple[int, ...]:
    """Resolve a probe_ability cook_name like 'Beef Sirloin Rare' to a meat tuple."""
    if presets:
        for cat in presets.get("categories", []):
            for cut in cat.get("cuts", []):
                for don in cut.get("doneness", []):
                    name = f"{cat['label']} {cut['label']} {don['label']}"
                    if name == cook_name:
                        cat_e, ani_e, ctt_e, cut_e = _CUT_LOOKUP.get(
                            cut["id"], _CUT_LOOKUP["other"]
                        )
                        prs_e = _DONENESS_ENC.get(don["id"], 2)
                        return (cat_e, ani_e, ctt_e, cut_e, prs_e)
    return _MEAT_FALLBACK


# ── Feature engineering ───────────────────────────────────────────────────────

def _rate(times_s: list[float], temps: list[float], window_s: float) -> float:
    if len(times_s) < 2:
        return 0.0
    cutoff = times_s[-1] - window_s
    idx = [i for i, t in enumerate(times_s) if t >= cutoff]
    if len(idx) < 2:
        idx = list(range(len(times_s)))
    dt = times_s[idx[-1]] - times_s[idx[0]]
    if dt <= 0:
        return 0.0
    return (temps[idx[-1]] - temps[idx[0]]) / (dt / 60.0)


def extract_features(
    elapsed_s: list[float],
    internal:  list[float],
    ambient:   list[float],
    sample_idx: int,
    target_temp: float,
    start_temp: float,
    meat: tuple[int, ...],
) -> dict | None:
    """Build the 17-feature dict at a given sample index.

    Feature definitions match ml_predictor.py inference exactly:
      - in_stall           : rate < 0.2 °C/min AND 40 ≤ T ≤ 80 °C
      - T_ambient_mean_so_far: mean of last 10 ambient readings
    """
    if sample_idx < 1:
        return None

    se = elapsed_s[: sample_idx + 1]
    si = internal[: sample_idx + 1]
    sa = ambient[: sample_idx + 1]

    rate_initial = _rate(se, si, 600.0)   # first 10 min
    rate_recent  = _rate(se, si, 300.0)   # last 5 min
    decel = rate_recent / rate_initial if abs(rate_initial) > 0.01 else 1.0

    T_current  = si[-1]
    amb_recent = sum(sa[-3:]) / min(len(sa), 3)

    # in_stall: widened to 40–80 °C (was 60–80 °C in the original training data)
    in_stall = 1.0 if (abs(rate_recent) < 0.2 and 40.0 <= T_current <= 80.0) else 0.0

    # T_ambient_mean_so_far: last 10 readings (was full-cook mean)
    win = sa[-10:] if len(sa) >= 10 else sa
    amb_mean = sum(win) / len(win)
    amb_std  = (sum((a - amb_mean) ** 2 for a in win) / len(win)) ** 0.5 if len(win) > 1 else 0.0

    cat_e, ani_e, ctt_e, cut_e, prs_e = meat

    return {
        "T_internal_current":    T_current,
        "T_ambient_current":     amb_recent,
        "rate_initial":          rate_initial,
        "rate_recent":           rate_recent,
        "deceleration":          decel,
        "T_internal_start":      float(start_temp),
        "T_remaining":           target_temp - T_current,
        "elapsed_min":           se[-1] / 60.0,
        "T_ambient_mean_so_far": amb_mean,
        "T_ambient_std_so_far":  amb_std,
        "in_stall":              in_stall,
        "T_gap":                 amb_recent - T_current,
        "category_enc":          float(cat_e),
        "animal_enc":            float(ani_e),
        "cut_type_enc":          float(ctt_e),
        "cut_enc":               float(cut_e),
        "preset_enc":            float(prs_e),
    }


def sample_cook(
    cook_id: str,
    elapsed_s: list[float],
    internal: list[float],
    ambient: list[float],
    endpoint_idx: int,
    target_temp: float,
    meat: tuple[int, ...],
) -> list[dict]:
    """Sample a cook at 10%, 20%, …, 90% of its active duration.

    Returns a list of dicts, each with feature values and 'remaining_min'.
    """
    if endpoint_idx < 5:
        return []

    active_dur_s = elapsed_s[endpoint_idx] - elapsed_s[0]
    if active_dur_s < 300:   # less than 5 min of usable data
        return []

    start_temp = internal[0]
    rows: list[dict] = []

    for frac in (0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9):
        target_elapsed = elapsed_s[0] + active_dur_s * frac
        idx = min(
            range(endpoint_idx + 1),
            key=lambda i: abs(elapsed_s[i] - target_elapsed),
        )
        if idx < 2:
            continue

        feats = extract_features(
            elapsed_s, internal, ambient,
            idx, target_temp, start_temp, meat,
        )
        if feats is None:
            continue

        remaining_min = (elapsed_s[endpoint_idx] - elapsed_s[idx]) / 60.0
        feats["remaining_min"] = remaining_min
        feats["cook_id"]       = cook_id
        rows.append(feats)

    return rows


# ── Meater export loader ──────────────────────────────────────────────────────

def _detect_active_endpoint(elapsed_s: list[float],
                             internal: list[float],
                             ambient:  list[float]) -> int:
    """Return index of the last active cooking sample (before rest/removal)."""
    n = len(internal)
    if n < 5:
        return n - 1

    peak_idx = max(range(n), key=lambda i: internal[i])

    # Rapid internal-temp drop (>5 °C/min)
    for i in range(peak_idx, n - 1):
        dt = elapsed_s[i + 1] - elapsed_s[i]
        if dt <= 0:
            continue
        drop = (internal[i] - internal[i + 1]) / (dt / 60.0)
        if drop > 5.0:
            return i

    # Ambient collapses below internal for 3+ consecutive samples
    for i in range(peak_idx, n - 2):
        if all(ambient[i + j] < internal[i + j] for j in range(3)):
            return i

    # Large ambient step down (oven/smoker turned off)
    for i in range(peak_idx, n - 1):
        if ambient[i] - ambient[i + 1] > 30:
            return i

    return peak_idx if peak_idx > n * 0.5 else n - 1


def load_meater_exports(data_dir: str) -> list[dict]:
    """Load all Meater-format cook CSVs from data_dir.

    Expected columns: timestamp, internal_temp_c, ambient_temp_c,
                      category, animal, cut_type, cut, preset
    """
    pattern = os.path.join(data_dir, "cook_*.csv")
    files = sorted(glob.glob(pattern))
    if not files:
        return []

    cooks: list[dict] = []
    skipped = 0

    for path in files:
        cook_id = Path(path).stem
        try:
            with open(path, newline="", encoding="utf-8") as fh:
                reader = csv.DictReader(fh)
                rows = list(reader)
        except Exception:
            skipped += 1
            continue

        if len(rows) < 10:
            skipped += 1
            continue

        try:
            ts       = [float(r["timestamp"])        for r in rows]
            internal = [float(r["internal_temp_c"])  for r in rows]
            ambient  = [float(r["ambient_temp_c"])   for r in rows]
        except (KeyError, ValueError):
            skipped += 1
            continue

        # Convert absolute timestamps to elapsed seconds
        elapsed_s = [t - ts[0] for t in ts]

        # Read meat metadata from first row
        r0 = rows[0]
        category_str = r0.get("category", "other").strip() or "other"
        preset_str   = r0.get("preset",   "medium").strip() or "medium"
        meat = meater_strings_to_meat(
            category_str,
            r0.get("animal",    "other"),
            r0.get("cut_type",  "other"),
            r0.get("cut",       "other"),
            preset_str,
        )

        # Derive the true doneness target from the preset column so that
        # T_remaining matches what probe_ability sends at inference time.
        # The Meater probe stays in the meat well past the target (often
        # reaching 100-120 °C), so peak_temp is a terrible target proxy.
        target_temp = _preset_to_target(category_str, preset_str)

        # endpoint = first reading at or above target (meat is done here)
        endpoint_idx = next(
            (i for i, t in enumerate(internal) if t >= target_temp),
            None,
        )
        if endpoint_idx is None or endpoint_idx < 5:
            # Meat never reached target in the recording — skip
            skipped += 1
            continue

        cooks.append({
            "cook_id":      cook_id,
            "elapsed_s":    elapsed_s,
            "internal":     internal,
            "ambient":      ambient,
            "endpoint_idx": endpoint_idx,
            "target_temp":  target_temp,
            "meat":         meat,
            "source":       "meater",
        })

    print(f"  Meater exports: loaded {len(cooks)}, skipped {skipped}")
    return cooks


# ── Probe-ability export loader ───────────────────────────────────────────────

def load_pa_exports(data_dir: str, presets: dict | None) -> list[dict]:
    """Load all probe_ability-format cook CSVs from data_dir.

    Expected format:
        # probe_ability_export_version: 3
        # cook_name: Beef Sirloin Rare
        # target_temp_c: 50.0
        # reached_target: true
        elapsed_s,internal_temp_c,ambient_temp_c,predicted_remaining_s,confidence
    """
    pattern = os.path.join(data_dir, "cook_*.csv")
    files = sorted(glob.glob(pattern))
    if not files:
        return []

    cooks: list[dict] = []
    skipped = 0
    skip_reasons: dict[str, int] = {}

    for path in files:
        cook_id = Path(path).stem
        meta: dict[str, str] = {}
        data_rows: list[list[str]] = []
        header: list[str] = []

        try:
            with open(path, encoding="utf-8") as fh:
                for line in fh:
                    if line.startswith("#"):
                        m = re.match(r"#\s*(\w+):\s*(.+)", line.strip())
                        if m:
                            meta[m.group(1)] = m.group(2).strip()
                    elif not header:
                        header = [c.strip() for c in line.split(",")]
                    else:
                        data_rows.append(line.strip().split(","))
        except Exception:
            skipped += 1
            skip_reasons["read_error"] = skip_reasons.get("read_error", 0) + 1
            continue

        # Only train on successfully completed cooks
        if meta.get("reached_target", "").lower() != "true":
            skipped += 1
            skip_reasons["not_completed"] = skip_reasons.get("not_completed", 0) + 1
            continue

        try:
            target_temp = float(meta.get("target_temp_c", "0"))
        except ValueError:
            skipped += 1
            continue

        if target_temp <= 0:
            skipped += 1
            continue

        # Parse rows
        try:
            col = {c: i for i, c in enumerate(header)}
            elapsed_s = []
            internal  = []
            ambient   = []
            for row in data_rows:
                if len(row) < 3:
                    continue
                t_int = float(row[col["internal_temp_c"]])
                if t_int <= 0:  # probe removed / disconnected
                    continue
                elapsed_s.append(float(row[col["elapsed_s"]]))
                internal.append(t_int)
                ambient.append(float(row[col["ambient_temp_c"]]))
        except (KeyError, ValueError, IndexError):
            skipped += 1
            skip_reasons["parse_error"] = skip_reasons.get("parse_error", 0) + 1
            continue

        if len(elapsed_s) < 10:
            skipped += 1
            skip_reasons["too_short"] = skip_reasons.get("too_short", 0) + 1
            continue

        # Find the endpoint: first reading at or above target temp
        endpoint_idx = len(elapsed_s) - 1
        for i, t in enumerate(internal):
            if t >= target_temp:
                endpoint_idx = i
                break

        if endpoint_idx < 5:
            skipped += 1
            skip_reasons["endpoint_too_early"] = skip_reasons.get("endpoint_too_early", 0) + 1
            continue

        cook_name = meta.get("cook_name", "")
        meat = cook_name_to_meat(cook_name, presets)

        cooks.append({
            "cook_id":      cook_id,
            "elapsed_s":    elapsed_s,
            "internal":     internal,
            "ambient":      ambient,
            "endpoint_idx": endpoint_idx,
            "target_temp":  target_temp,
            "meat":         meat,
            "source":       "probe_ability",
        })

    print(f"  probe_ability exports: loaded {len(cooks)}, skipped {skipped}", end="")
    if skip_reasons:
        print(f" ({', '.join(f'{v} {k}' for k, v in skip_reasons.items())})", end="")
    print()
    return cooks


def load_supabase_exports(
    url: str,
    service_key: str,
    presets: dict | None = None,
) -> list[dict]:
    """Load shared cooks from the Supabase REST API.

    Requires the project service role key (bypasses Row Level Security).
    Pass the key via --supabase-key or set SUPABASE_SERVICE_KEY env var.

    Only cooks where the peak internal temp is within 12°C of the target
    are included — matching the threshold used by the HA sharing logic
    (covers carryover cooks where a wired probe is pulled before target).
    """
    try:
        import requests as _requests
    except ImportError:
        print("  [supabase] 'requests' not installed — skipping (pip install requests)")
        return []

    endpoint = f"{url}/rest/v1/cooks"
    headers = {
        "apikey":        service_key,
        "Authorization": f"Bearer {service_key}",
    }
    params = {
        "select":    "*",
        "cook_name": "not.like.Test *",   # exclude smoke-test rows
        "order":     "created_at",
    }

    try:
        resp = _requests.get(endpoint, headers=headers, params=params, timeout=30)
        resp.raise_for_status()
        rows = resp.json()
    except Exception as exc:
        print(f"  [supabase] fetch failed: {exc}")
        return []

    loaded, skipped = 0, 0
    cooks: list[dict] = []

    for row in rows:
        cook_name    = row.get("cook_name") or ""
        target_temp  = float(row.get("target_temp_c") or 0)
        readings_raw = row.get("readings") or []

        if not readings_raw or target_temp <= 0:
            skipped += 1
            continue

        # readings = [[elapsed_s, internal_c, ambient_c], ...]
        try:
            triples = [(float(r[0]), float(r[1]), float(r[2])) for r in readings_raw]
        except (TypeError, IndexError, ValueError):
            skipped += 1
            continue

        # Filter out zero / invalid probe readings
        valid = [(e, i, a) for e, i, a in triples if i > 0]
        if len(valid) < 5:
            skipped += 1
            continue

        elapsed_s = [v[0] for v in valid]
        internal  = [v[1] for v in valid]
        ambient   = [v[2] for v in valid]

        # Skip if the probe never got close to target (bad / abandoned cook)
        peak_temp = max(internal)
        if peak_temp < target_temp - 12:
            skipped += 1
            continue

        # endpoint = first reading >= target, else last reading (carryover)
        endpoint_idx = next(
            (i for i, t in enumerate(internal) if t >= target_temp),
            len(internal) - 1,
        )
        if endpoint_idx < 5:
            skipped += 1
            continue

        meat = cook_name_to_meat(cook_name, presets)

        cooks.append({
            "cook_id":      f"supabase_{row['id']}",
            "elapsed_s":    elapsed_s[:endpoint_idx + 1],
            "internal":     internal[:endpoint_idx + 1],
            "ambient":      ambient[:endpoint_idx + 1],
            "endpoint_idx": endpoint_idx,
            "target_temp":  target_temp,
            "meat":         meat,
            "source":       "supabase",
        })
        loaded += 1

    print(f"  Supabase exports:      loaded {loaded}, skipped {skipped}")
    return cooks


# ── Model compilation ─────────────────────────────────────────────────────────

_NODE_FMT  = ">hfhhf"   # feat(h), thresh(f), left(h), right(h), val(f)
_NODE_SIZE = struct.calcsize(_NODE_FMT)   # 14 bytes


def _compile_tree(tree_) -> bytes:
    """Serialise one sklearn decision tree to the packed binary format."""
    parts = []
    for i in range(tree_.node_count):
        feat   = int(tree_.feature[i])         # -2 at leaf (TREE_UNDEFINED)
        thresh = float(tree_.threshold[i])
        left   = int(tree_.children_left[i])   # -1 at leaf (TREE_LEAF)
        right  = int(tree_.children_right[i])
        val    = float(tree_.value[i, 0, 0])
        parts.append(struct.pack(_NODE_FMT, feat, thresh, left, right, val))
    return b"".join(parts)


def compile_model(model, out_path: str) -> None:
    """Write ml_model_code.py from a trained GradientBoostingRegressor."""
    all_bytes = bytearray()
    offsets: list[tuple[int, int]] = []

    for stage in model.estimators_:
        tree_ = stage[0].tree_           # single output
        start = len(all_bytes)
        chunk = _compile_tree(tree_)
        offsets.append((start, tree_.node_count))
        all_bytes += chunk

    # Initial prediction: mean of training targets (DummyRegressor constant)
    init_val = float(model.init_.constant_[0, 0])
    lr       = float(model.learning_rate)

    # Base64-encode in 76-char lines (PEM-style)
    b64 = base64.b64encode(bytes(all_bytes)).decode("ascii")
    chunks = [b64[i: i + 76] for i in range(0, len(b64), 76)]

    lines = [
        '"""Pure-Python GradientBoosting inference — no sklearn required.',
        'Auto-generated from model.pkl by retrain.py. Do not edit manually.',
        '"""',
        "import struct, base64",
        "",
        f"_INIT = {init_val!r}",
        f"_LR   = {lr!r}",
        f'_FMT  = "{_NODE_FMT}"',
        f"_NS   = {_NODE_SIZE}",
        "",
        "_OFFSETS = (",
    ]
    for start, count in offsets:
        lines.append(f"  ({start},{count}),")
    lines.append(")")
    lines.append("")
    lines.append("_DATA = base64.b64decode(")
    for chunk in chunks:
        lines.append(f'  "{chunk}"')
    lines.append(")")
    lines.append("")
    lines.append("def score(x):")
    lines.append('    """Return predicted minutes remaining for feature vector x (list of 17 floats)."""')
    lines.append("    total = _INIT")
    lines.append("    unpack = struct.unpack_from")
    lines.append("    for start, count in _OFFSETS:")
    lines.append("        node = 0")
    lines.append("        while True:")
    lines.append("            off = start + node * _NS")
    lines.append("            feat, thresh, left, right, val = unpack(_FMT, _DATA, off)")
    lines.append("            if left == -1:  # leaf")
    lines.append("                total += _LR * val")
    lines.append("                break")
    lines.append("            node = left if x[feat] <= thresh else right")
    lines.append("    return total")
    lines.append("")

    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))

    kb = len(all_bytes) / 1024
    print(f"  Compiled {len(offsets)} trees, {len(all_bytes):,} bytes ({kb:.1f} KB) → {out_path}")


# ── Training ──────────────────────────────────────────────────────────────────

def train(all_rows: list[dict], output_dir: str) -> object:
    """Train GBT model and return it."""
    try:
        import numpy as np
        from sklearn.ensemble import GradientBoostingRegressor
        from sklearn.model_selection import GroupKFold, cross_val_score
        from sklearn.metrics import mean_absolute_error
    except ImportError as exc:
        sys.exit(f"\nMissing dependency: {exc}\n  pip install scikit-learn numpy")

    X = np.array([[r[f] for f in _FEATURE_ORDER] for r in all_rows])
    y = np.array([r["remaining_min"] for r in all_rows])
    groups = np.array([r["cook_id"] for r in all_rows])

    print(f"  Training on {len(y)} samples from {len(set(groups))} cooks")
    print(f"  Target remaining-time: mean={y.mean():.1f} min, std={y.std():.1f} min")

    model = GradientBoostingRegressor(
        n_estimators=500,
        max_depth=4,
        learning_rate=0.05,
        subsample=0.8,
        random_state=42,
    )

    # GroupKFold so no cook leaks from train to val
    gkf = GroupKFold(n_splits=min(5, len(set(groups))))
    group_ids = {g: i for i, g in enumerate(sorted(set(groups)))}
    g_ints = np.array([group_ids[g] for g in groups])
    scores = cross_val_score(model, X, y, cv=gkf, groups=g_ints,
                             scoring="neg_mean_absolute_error")
    cv_mae = -scores.mean()

    model.fit(X, y)
    train_mae = mean_absolute_error(y, model.predict(X))

    print(f"  CV MAE: {cv_mae:.1f} min  |  Train MAE: {train_mae:.1f} min")

    # Per-source MAE breakdown
    sources = [r.get("source", "?") for r in all_rows]
    for src in sorted(set(sources)):
        idx = [i for i, s in enumerate(sources) if s == src]
        if idx:
            src_mae = mean_absolute_error(y[idx], model.predict(X[idx]))
            print(f"    {src:20s}: {src_mae:.1f} min MAE  ({len(idx)} samples)")

    # Fraction-of-cook breakdown
    print("  Accuracy by fraction of cook seen:")
    fracs = np.array([r["elapsed_min"] / (r["elapsed_min"] + r["remaining_min"])
                      for r in all_rows])
    for lo, hi in ((0.0, 0.3), (0.3, 0.6), (0.6, 0.9), (0.9, 1.0)):
        idx = np.where((fracs >= lo) & (fracs < hi))[0]
        if len(idx):
            src_mae = mean_absolute_error(y[idx], model.predict(X[idx]))
            print(f"    {lo*100:.0f}–{hi*100:.0f}% seen: {src_mae:.1f} min MAE  (n={len(idx)})")

    # Save report
    report_path = os.path.join(output_dir, "retrain_report.txt")
    with open(report_path, "w") as fh:
        fh.write(f"Retrain report\n{'='*40}\n")
        fh.write(f"Total samples:  {len(y)}\n")
        fh.write(f"Total cooks:    {len(set(groups))}\n")
        for src in sorted(set(sources)):
            n = sources.count(src)
            fh.write(f"  {src}: {n} samples\n")
        fh.write(f"\nCV MAE:         {cv_mae:.2f} min\n")
        fh.write(f"Train MAE:      {train_mae:.2f} min\n")
    print(f"  Report written to {report_path}")

    return model, cv_mae


# ── Analysis plots ────────────────────────────────────────────────────────────

def generate_plots(
    model,
    all_rows: list[dict],
    all_cooks: list[dict],
    output_dir: str,
    cv_mae: float,
) -> None:
    """Save three diagnostic PNG files to output_dir after a training run."""
    try:
        import numpy as np
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError as _e:
        print(f"  Skipping plots — missing dependency: {_e}  (pip install matplotlib numpy)")
        return

    from sklearn.metrics import mean_absolute_error as _mae

    PALETTE = {
        "meater":        "#2196F3",
        "probe_ability": "#FF9800",
        "supabase":      "#4CAF50",
    }
    DEFAULT_C = "#9E9E9E"

    def src_color(src: str) -> str:
        return PALETTE.get(src, DEFAULT_C)

    # ── shared arrays ─────────────────────────────────────────────────────────
    X         = np.array([[row[f] for f in _FEATURE_ORDER] for row in all_rows])
    y_actual  = np.array([row["remaining_min"] for row in all_rows])
    y_pred    = model.predict(X)
    residuals = y_pred - y_actual

    sources   = [row.get("source", "?") for row in all_rows]
    T_amb     = np.array([row["T_ambient_current"] for row in all_rows])
    el_min    = np.array([row["elapsed_min"]       for row in all_rows])
    fracs     = el_min / np.where(el_min + y_actual > 0, el_min + y_actual, 1)

    all_src = sorted(set(sources))

    # ── Figure 1 : Prediction Accuracy ────────────────────────────────────────
    fig, axes = plt.subplots(2, 2, figsize=(14, 11))
    fig.suptitle(
        f"Prediction Accuracy   (CV MAE = {cv_mae:.1f} min)",
        fontsize=14, fontweight="bold",
    )

    # [0,0] Predicted vs Actual scatter
    ax = axes[0, 0]
    for src in all_src:
        idx = [i for i, s in enumerate(sources) if s == src]
        ax.scatter(y_actual[idx], y_pred[idx],
                   alpha=0.45, s=14, color=src_color(src), label=src)
    lim = max(y_actual.max(), y_pred.max()) * 1.05
    ax.plot([0, lim], [0, lim], "r--", lw=1.2, alpha=0.7, label="perfect")
    ax.set_xlim(0, lim); ax.set_ylim(0, lim)
    ax.set_xlabel("Actual remaining (min)")
    ax.set_ylabel("Predicted remaining (min)")
    ax.set_title("Predicted vs Actual")
    ax.legend(fontsize=8)

    # [0,1] MAE by fraction of cook seen
    ax = axes[0, 1]
    brackets = [(0.0, 0.3, "0–30%"), (0.3, 0.6, "30–60%"),
                (0.6, 0.9, "60–90%"), (0.9, 1.0, "90–100%")]
    b_labels, b_maes = [], []
    for lo, hi, label in brackets:
        idx = np.where((fracs >= lo) & (fracs < hi))[0]
        if len(idx):
            b_maes.append(_mae(y_actual[idx], y_pred[idx]))
            b_labels.append(f"{label}\n(n={len(idx)})")
    bars = ax.bar(range(len(b_maes)), b_maes, color="#5C6BC0", alpha=0.85)
    for bar, mae in zip(bars, b_maes):
        ax.text(bar.get_x() + bar.get_width() / 2,
                bar.get_height() + 0.1, f"{mae:.1f}",
                ha="center", va="bottom", fontsize=9)
    ax.set_xticks(range(len(b_labels))); ax.set_xticklabels(b_labels, fontsize=9)
    ax.set_ylabel("MAE (min)")
    ax.set_title("MAE by Fraction of Cook Seen")
    ax.axhline(cv_mae, color="red", ls="--", lw=1.2,
               label=f"CV MAE = {cv_mae:.1f} min")
    ax.legend(fontsize=8)

    # [1,0] Residual distribution
    ax = axes[1, 0]
    ax.hist(residuals, bins=40, color="#5C6BC0", alpha=0.75, edgecolor="white")
    ax.axvline(0, color="red", ls="--", lw=1.5)
    ax.axvline(float(np.median(residuals)), color="orange", ls="--", lw=1.2,
               label=f"median = {float(np.median(residuals)):.1f} min")
    ax.set_xlabel("Residual: predicted − actual (min)")
    ax.set_ylabel("Count")
    ax.set_title("Residual Distribution")
    ax.legend(fontsize=8)

    # [1,1] Residuals vs ambient temperature
    ax = axes[1, 1]
    for src in all_src:
        mask = np.array([s == src for s in sources])
        ax.scatter(T_amb[mask], residuals[mask],
                   alpha=0.35, s=12, color=src_color(src), label=src)
    ax.axhline(0, color="red", ls="--", lw=1.2)
    ax.set_xlabel("Ambient temperature (°C)")
    ax.set_ylabel("Residual: predicted − actual (min)")
    ax.set_title("Residuals vs Ambient Temp")
    ax.legend(fontsize=8)

    plt.tight_layout()
    p = os.path.join(output_dir, "accuracy.png")
    plt.savefig(p, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"  Plot: {p}")

    # ── Figure 2 : Training Data Overview ────────────────────────────────────
    fig, axes = plt.subplots(2, 2, figsize=(14, 11))
    fig.suptitle("Training Data Overview", fontsize=14, fontweight="bold")

    cook_srcs = sorted(set(c["source"] for c in all_cooks))

    # [0,0] Cook count by source
    ax = axes[0, 0]
    src_counts = {s: sum(1 for c in all_cooks if c["source"] == s) for s in cook_srcs}
    bars = ax.bar(src_counts.keys(), src_counts.values(),
                  color=[src_color(s) for s in src_counts])
    for bar, (src, n) in zip(bars, src_counts.items()):
        ax.text(bar.get_x() + bar.get_width() / 2,
                bar.get_height() + 0.2, str(n),
                ha="center", va="bottom", fontsize=11, fontweight="bold")
    ax.set_ylabel("Number of cooks")
    ax.set_title(f"Cooks by Source  (total = {len(all_cooks)})")

    # [0,1] Mean ambient temperature per cook
    ax = axes[0, 1]
    for src in cook_srcs:
        ambs = [float(np.mean(c["ambient"])) for c in all_cooks if c["source"] == src]
        ax.hist(ambs, bins=20, alpha=0.65, color=src_color(src), label=f"{src} ({len(ambs)})")
    ax.set_xlabel("Mean ambient temperature (°C)")
    ax.set_ylabel("Count")
    ax.set_title("Ambient Temperature Distribution")
    ax.legend(fontsize=8)

    # [1,0] Cook duration to target
    ax = axes[1, 0]
    for src in cook_srcs:
        durs = [c["elapsed_s"][c["endpoint_idx"]] / 60.0
                for c in all_cooks if c["source"] == src]
        ax.hist(durs, bins=20, alpha=0.65, color=src_color(src), label=src)
    ax.set_xlabel("Active cook duration (min)")
    ax.set_ylabel("Count")
    ax.set_title("Cook Duration Distribution")
    ax.legend(fontsize=8)

    # [1,1] Internal temp rise (start → target crossing)
    ax = axes[1, 1]
    for src in cook_srcs:
        rises = [c["internal"][c["endpoint_idx"]] - c["internal"][0]
                 for c in all_cooks if c["source"] == src]
        ax.hist(rises, bins=20, alpha=0.65, color=src_color(src), label=src)
    ax.set_xlabel("Temperature rise to target (°C)")
    ax.set_ylabel("Count")
    ax.set_title("Internal Temp Rise Distribution")
    ax.legend(fontsize=8)

    plt.tight_layout()
    p = os.path.join(output_dir, "training_data.png")
    plt.savefig(p, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"  Plot: {p}")

    # ── Figure 3 : Sample Cook Curves ─────────────────────────────────────────
    import random as _random
    rng = _random.Random(42)

    selected: list[dict] = []
    for src in cook_srcs:
        pool = [c for c in all_cooks if c["source"] == src]
        selected.extend(rng.sample(pool, min(3, len(pool))))

    ncols = 3
    nrows = max(1, (len(selected) + ncols - 1) // ncols)
    fig, axes_grid = plt.subplots(nrows, ncols, figsize=(15, 4.5 * nrows))
    # normalise axes to 2-D array
    if nrows == 1 and ncols == 1:
        axes_grid = np.array([[axes_grid]])
    elif nrows == 1:
        axes_grid = np.array([axes_grid])
    elif ncols == 1:
        axes_grid = axes_grid.reshape(-1, 1)

    fig.suptitle("Sample Cook Temperature Profiles", fontsize=14, fontweight="bold")

    for k, cook in enumerate(selected):
        ax = axes_grid[k // ncols][k % ncols]
        ep  = cook["endpoint_idx"]
        el  = [e / 60.0 for e in cook["elapsed_s"][:ep + 1]]
        tin = cook["internal"][:ep + 1]
        tam = cook["ambient"][:ep + 1]
        col = src_color(cook["source"])

        ax.plot(el, tin, color=col, lw=1.8, label="Internal")
        ax2 = ax.twinx()
        ax2.plot(el, tam, color="gray", lw=1.0, ls="--", alpha=0.55, label="Ambient")
        ax2.set_ylabel("Ambient (°C)", fontsize=7, color="gray")
        ax2.tick_params(axis="y", labelsize=7, colors="gray")

        ax.axhline(cook["target_temp"], color="red", ls=":", lw=1.2, alpha=0.7)
        ax.set_xlabel("Elapsed (min)", fontsize=8)
        ax.set_ylabel("Internal (°C)", fontsize=8)
        title = cook["cook_id"]
        if len(title) > 28:
            title = "…" + title[-25:]
        ax.set_title(f"{title}  [{cook['source']}]", fontsize=7)

    for k in range(len(selected), nrows * ncols):
        axes_grid[k // ncols][k % ncols].set_visible(False)

    plt.tight_layout()
    p = os.path.join(output_dir, "cook_curves.png")
    plt.savefig(p, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"  Plot: {p}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    here = Path(__file__).parent

    parser = argparse.ArgumentParser(description="Retrain Probe-ability ML model")
    parser.add_argument(
        "--pa-exports", default=str(here / "probe_ability_exports"),
        help="Directory containing probe_ability CSV exports (default: ./probe_ability_exports)",
    )
    parser.add_argument(
        "--output-dir", default=str(here / "retrain_output"),
        help="Output directory for model and report (default: ./retrain_output)",
    )
    parser.add_argument(
        "--supabase-key", default="",
        help="Supabase service role key to pull shared cooks "
             "(or set SUPABASE_SERVICE_KEY env var)",
    )
    parser.add_argument(
        "--no-plots", action="store_true",
        help="Skip generating analysis PNG files after training",
    )
    args = parser.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)

    # Load cook_presets.json for cook_name → meat mapping
    # Check new HACS location first, fall back to legacy www/probe-ability/ path
    presets_path = here / "custom_components" / "probe_ability" / "www" / "cook_presets.json"
    if not presets_path.exists():
        presets_path = here / "www" / "probe-ability" / "cook_presets.json"
    presets: dict | None = None
    if presets_path.exists():
        try:
            presets = json.loads(presets_path.read_text())
            print(f"Loaded cook_presets.json ({sum(len(c['cuts']) for c in presets['categories'])} cuts)")
        except Exception as exc:
            print(f"Warning: could not load cook_presets.json ({exc})")
    else:
        print(f"Warning: cook_presets.json not found at {presets_path}")

    # ── Load cooks ──
    print("\nLoading cook data…")
    meater_dir = str(here / "meater_exports")
    all_cooks  = load_meater_exports(meater_dir)
    # Also pick up any probe_ability-format exports that landed in meater_exports/
    all_cooks += load_pa_exports(meater_dir, presets)
    all_cooks += load_pa_exports(args.pa_exports, presets)

    supabase_key = args.supabase_key or os.environ.get("SUPABASE_SERVICE_KEY", "")
    if supabase_key:
        all_cooks += load_supabase_exports(
            "https://hlsfrqvfhtauoyhugyou.supabase.co",
            supabase_key,
            presets,
        )
    else:
        print("  Supabase:              skipped (set SUPABASE_SERVICE_KEY or --supabase-key)")

    if not all_cooks:
        sys.exit("No cook data found. Check meater_exports/ and --pa-exports path.")

    source_counts = {}
    for c in all_cooks:
        source_counts[c["source"]] = source_counts.get(c["source"], 0) + 1
    print(f"  Total: {len(all_cooks)} cooks  "
          + "  ".join(f"({v} {k})" for k, v in source_counts.items()))

    # ── Build training samples ──
    print("\nBuilding training samples…")
    all_rows: list[dict] = []
    for cook in all_cooks:
        rows = sample_cook(
            cook["cook_id"],
            cook["elapsed_s"], cook["internal"], cook["ambient"],
            cook["endpoint_idx"], cook["target_temp"], cook["meat"],
        )
        for row in rows:
            row["source"] = cook["source"]
        all_rows.extend(rows)

    if not all_rows:
        sys.exit("No training samples produced. Are the cooks long enough?")
    print(f"  {len(all_rows)} training samples")

    # ── Train ──
    print("\nTraining model…")
    model, cv_mae = train(all_rows, args.output_dir)

    # ── Plots ──
    if not args.no_plots:
        print("\nGenerating analysis plots…")
        generate_plots(model, all_rows, all_cooks, args.output_dir, cv_mae)

    # ── Compile ──
    print("\nCompiling model…")
    compiled_path = str(here / "custom_components" / "probe_ability" / "ml_model_code.py")
    compile_model(model, compiled_path)

    # Save sklearn model for inspection
    try:
        import pickle
        pkl_path = os.path.join(args.output_dir, "model.pkl")
        with open(pkl_path, "wb") as fh:
            pickle.dump(model, fh)
        print(f"  sklearn model saved to {pkl_path}")
    except Exception as exc:
        print(f"  Warning: could not save model.pkl ({exc})")

    print("\nDone. Deploy by copying ml_model_code.py to your HA instance and restarting.")
    print(f"  {compiled_path}")


if __name__ == "__main__":
    main()
