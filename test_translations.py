#!/usr/bin/env python3
"""Test the translation files — the single source of every user-facing string.

Run standalone — no Home Assistant required:

    python3 test_translations.py

Checks that every language's {placeholders} match en.json (Home Assistant
drops a translated string whose placeholders differ from English), that values
pass hassfest's rules, and that every string the card, the presets and the
Python code ask for actually exists.

Missing keys in a translation are only a warning — Home Assistant shows the
English text for them — so adding an English string never breaks CI for the
other languages.  The completeness table at the end shows what is left to
translate; in GitHub Actions it is also written to the job summary.
"""

from __future__ import annotations

import json
import os
import re
import string
import sys
from pathlib import Path

ROOT = Path(__file__).parent
PKG = ROOT / "custom_components" / "probe_ability"
TRANSLATIONS = PKG / "translations"
CARD = PKG / "www" / "probe-ability-card.js"
PRESETS = PKG / "www" / "cook_presets.json"

# hassfest: script/hassfest/translations.py
KEY_RE = re.compile(r"^(?!.+[_-]{2})(?![_-])[a-z0-9-_]+(?<![_-])$")
URL_RE = re.compile(r"\w+://")

PASSED = 0
FAILED = 0
WARNINGS: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    global PASSED, FAILED
    if ok:
        PASSED += 1
        print(f"  ok  {name}")
    else:
        FAILED += 1
        print(f"  FAIL {name}" + (f": {detail}" if detail else ""))


def warn(message: str) -> None:
    WARNINGS.append(message)
    print(f"  warn {message}")


def flatten(tree: dict, prefix: str = "") -> dict[str, str]:
    out: dict[str, str] = {}
    for key, value in tree.items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            out.update(flatten(value, path))
        else:
            out[path] = value
    return out


def placeholders(value: str) -> set[str]:
    return {field for _, field, _, _ in string.Formatter().parse(value) if field}


def options(data: dict, section: str) -> dict[str, str]:
    return data.get("selector", {}).get(section, {}).get("options", {})


en = json.loads((TRANSLATIONS / "en.json").read_text(encoding="utf-8"))
en_flat = flatten(en)
languages = {
    p.stem: json.loads(p.read_text(encoding="utf-8"))
    for p in sorted(TRANSLATIONS.glob("*.json"))
}

# ── 1. One source ────────────────────────────────────────────────────────────

print("single source")
check("strings.json is gone (translations/en.json is the English source)",
      not (PKG / "strings.json").exists())
presets = json.loads(PRESETS.read_text(encoding="utf-8"))
check("cook_presets.json has no per-language labels", '"labels"' not in PRESETS.read_text())
card_src = CARD.read_text(encoding="utf-8")
check("the card has no string table of its own", "const I18N" not in card_src)

# ── 2. Every language mirrors English ────────────────────────────────────────

print("languages vs en.json")
completeness: dict[str, tuple[int, list[str], list[str]]] = {}
for lang, data in languages.items():
    if lang == "en":
        continue
    flat = flatten(data)
    missing = sorted(set(en_flat) - set(flat))
    extra = sorted(set(flat) - set(en_flat))
    completeness[lang] = (len(en_flat) - len(missing), missing, extra)
    if missing:
        warn(f"{lang}: {len(missing)} untranslated (shown in English): " + ", ".join(missing[:5])
             + (" …" if len(missing) > 5 else ""))
    if extra:
        warn(f"{lang}: {len(extra)} keys no longer in en.json (safe to delete): " + ", ".join(extra[:5])
             + (" …" if len(extra) > 5 else ""))
    bad = [k for k in flat if k in en_flat and placeholders(flat[k]) != placeholders(en_flat[k])]
    check(f"{lang}: placeholders match English", not bad, ", ".join(bad[:10]))

# ── 3. hassfest value rules ──────────────────────────────────────────────────

print("hassfest rules")
for lang, data in languages.items():
    flat = flatten(data)
    bad_keys = sorted({
        part
        for path in flat
        for part in path.split(".")
        if not KEY_RE.match(part)
    })
    check(f"{lang}: keys are lowercase slugs", not bad_keys, ", ".join(bad_keys[:10]))
    problems = []
    for key, value in flat.items():
        if not isinstance(value, str):
            problems.append(f"{key} (not a string)")
        elif not value.strip():
            # Home Assistant would show an empty label, not the English fallback
            # (a translation tool may write untranslated strings as "").
            problems.append(f"{key} (empty)")
        elif value != value.strip():
            problems.append(f"{key} (leading/trailing space)")
        elif "<" in value:
            problems.append(f"{key} (HTML)")
        elif URL_RE.search(value):
            problems.append(f"{key} (URL)")
        elif re.search(r"'\{\w*\}'", value):
            problems.append(f"{key} (single-quoted placeholder)")
        elif not all(p.isidentifier() for p in placeholders(value)):
            problems.append(f"{key} (placeholder not an identifier)")
    check(f"{lang}: values pass hassfest", not problems, ", ".join(problems[:10]))

# ── 4. Everything that is asked for exists in English ────────────────────────

print("coverage")
card = options(en, "card")
used = set(re.findall(r"\bt\(\s*\"(\w+)\"", card_src)) | set(re.findall(r"tkey:\s*\"(\w+)\"", card_src))
# Keys the card builds at runtime, e.g. t(`mode_${probeMode}`): the prefix and
# every value it can take.  A new dynamic key fails below until it is listed here.
DYNAMIC_KEYS = {"mode_": ("combined", "individual")}
dynamic = set(re.findall(r"\bt\(\s*`(\w+)\$\{", card_src))
check("card: every runtime-built key prefix is known", dynamic <= set(DYNAMIC_KEYS),
      ", ".join(sorted(dynamic - set(DYNAMIC_KEYS))))
used |= {prefix + value for prefix, values in DYNAMIC_KEYS.items() for value in values}
check(f"card: {len(used)} used keys all in selector.card", used <= set(card),
      ", ".join(sorted(used - set(card))))

for level in ("category", "cut", "doneness"):
    names = options(en, f"preset_{level}")
    objs = []
    for cat in presets["categories"]:
        if level == "category":
            objs.append(cat)
        for cut in cat["cuts"]:
            if level == "cut":
                objs.append(cut)
            if level == "doneness":
                objs.extend(cut.get("doneness", []))
    missing = sorted({o["id"] for o in objs} - set(names))
    check(f"preset_{level}: every id has a name", not missing, ", ".join(missing))
    differ = sorted({o["id"] for o in objs if o["id"] in names and names[o["id"]] != o["label"]})
    check(f"preset_{level}: English name equals the canonical label", not differ, ", ".join(differ))

backend = options(en, "backend")
py_src = "\n".join(p.read_text(encoding="utf-8") for p in PKG.glob("*.py"))
used = set(re.findall(r"\btexts\(\s*[\"'](\w+)[\"']", py_src))
used |= {f"phase_{p}" for p in ("collecting", "heating", "stall", "finishing")}
check(f"backend: {len(used)} used keys all in selector.backend", used <= set(backend),
      ", ".join(sorted(used - set(backend))))

# ── 5. Completeness table ────────────────────────────────────────────────────

rows = [
    (lang, done, len(en_flat), missing)
    for lang, (done, missing, _extra) in sorted(completeness.items())
]
table = ["| Language | Translated | Missing |", "|---|---|---|",
         f"| en (source) | {len(en_flat)}/{len(en_flat)} | — |"]
table += [
    f"| {lang} | {done}/{total} ({100 * done // total}%) | {len(missing) or '—'} |"
    for lang, done, total, missing in rows
]
print()
print("\n".join(table))
summary = os.environ.get("GITHUB_STEP_SUMMARY")
if summary:
    with open(summary, "a", encoding="utf-8") as fh:
        fh.write("## Translations\n\n" + "\n".join(table) + "\n")
        if WARNINGS:
            fh.write("\n" + "\n".join(f"- ⚠️ {w}" for w in WARNINGS) + "\n")

print()
if FAILED:
    print(f"{FAILED} of {PASSED + FAILED} checks FAILED")
    sys.exit(1)
print(f"All {PASSED} checks passed" + (f" ({len(WARNINGS)} warnings)." if WARNINGS else "."))
