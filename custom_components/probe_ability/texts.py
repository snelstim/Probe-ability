"""Backend user-facing strings, read from translations/<lang>.json.

The texts live under ``selector.backend.options`` — hassfest rejects unknown
top-level sections, and a selector's ``options`` map is free-form — next to
the card's strings (``selector.card``) and the preset names
(``selector.preset_*``), so each language is a single file.

Deliberately HA-free (like live_activity.py) so the standalone tests can
import it; __init__.py fills it from HA's translation cache, which already
falls back to English for missing keys.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from pathlib import Path

SECTION = "backend"

_PLACEHOLDER = re.compile(r"\{(\w+)\}")


class Texts:
    """Flat ``{key: template}`` lookup with ``{name}`` substitution."""

    def __init__(self, resources: Mapping[str, str] | None = None) -> None:
        self._resources = dict(resources or {})

    def __call__(self, key: str, **values: object) -> str:
        """Translate ``key``; a missing key returns the key itself, never raises.

        Placeholders are replaced with a regex rather than str.format so a
        stray brace in a translation can't break a notification.
        """
        template = self._resources.get(key, key)
        if not values:
            return template
        return _PLACEHOLDER.sub(
            lambda m: str(values[m.group(1)]) if m.group(1) in values else m.group(0),
            template,
        )

    @classmethod
    def from_resources(cls, resources: Mapping[str, str], domain: str) -> Texts:
        """Build from HA's flattened translations (``async_get_translations``)."""
        prefix = f"component.{domain}.selector.{SECTION}.options."
        return cls(
            {k[len(prefix):]: v for k, v in resources.items() if k.startswith(prefix)}
        )

    @classmethod
    def from_translation_file(cls, path: str | Path) -> Texts:
        """Build straight from a translations/<lang>.json file (tests)."""
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(data.get("selector", {}).get(SECTION, {}).get("options", {}))
