# Translating Probe-ability

Probe-ability's user-facing text lives in **four** places. To fully translate the
integration into a new language you touch each one. English (`en`) is the source of
truth and the automatic fallback everywhere, so a partial translation is safe — any
missing string simply shows in English.

The examples below use Dutch (`nl`), which ships as a complete reference translation.
Replace `nl` / `xx` with your [HA language code](https://www.home-assistant.io/integrations/frontend/#change-the-language)
(the base code, e.g. `de`, `fr`, `pt` — not `pt-BR`).

## The four surfaces

| # | Surface | File(s) | Mechanism |
|---|---------|---------|-----------|
| 1 | Config flow, options, service descriptions, entity names, error toasts | `custom_components/probe_ability/translations/<lang>.json` | Home Assistant's built-in loader (automatic) |
| 2 | The Lovelace card UI | `custom_components/probe_ability/www/probe-ability-card.js` → the `I18N` table | Card-owned string table |
| 3 | Preset cut / doneness **display** names | `custom_components/probe_ability/www/cook_presets.json` → `labels` | Card-owned, display-only |
| 4 | Auto-stop persistent notification | `custom_components/probe_ability/__init__.py` | Currently English only (see note) |

`strings.json` is the English source; `translations/en.json` is a copy of it. Keep the
two in sync when you add or rename English keys.

## Adding a language

### 1. Backend (HA translations)

Copy the English file and translate every value (keep the keys unchanged):

```
cp custom_components/probe_ability/translations/en.json \
   custom_components/probe_ability/translations/xx.json
```

Translate the string values under `config`, `selector`, `entity`, `services`, and
`exceptions`. HA picks the file up automatically based on the user's language — no code
changes required.

### 2. The card

In `www/probe-ability-card.js`, find the `I18N` object and add a block for your
language by copying the `en` block and translating the values. Leave `{n}`, `{unit}`,
`{temp}`, `{eta}`, `{count}`, `{needed}`, `{time}`, `{rate}`, and `{entity}`
placeholders intact — they are filled in at runtime. Emoji in values (🔗 / ⚡) should be
kept; translate only the words.

```js
const I18N = {
  en: { /* … */ },
  nl: { /* … */ },
  xx: { start_cook: "…", /* copy every key from en and translate */ },
};
```

The card resolves the language from `hass.language` at render time and falls back to
`en` for any missing key or language.

### 3. Preset labels — mind the canonical key

Each category / cut / doneness in `cook_presets.json` has an English `label` plus an
optional `labels` map for translations:

```json
{ "id": "rib_eye", "label": "Rib Eye", "labels": { "nl": "Ribeye", "xx": "…" } }
```

Add your `xx` entry to the `labels` map. **Do not change the English `label`.**

> ⚠️ **Why `label` is load-bearing.** The card builds the cook name it sends to the
> backend from the English `label`s (`_makeCookName`), and `ml_predictor.py`'s
> `_COOK_NAME_MAP` looks the cook up by that exact English string. `labels` is
> **display-only**; the stored cook name and the ML feature lookup always stay English,
> so translations never break prediction accuracy or the exported/shared data.

### 4. The auto-stop notification (optional)

The "BBQ Cook Auto-Stopped" persistent notification in `__init__.py` is still English.
Home Assistant has no first-class translation path for `persistent_notification.create`
content, so it is intentionally left untranslated for now. The related start-cook error
toasts *are* translated (see the `exceptions` section of the translation files).

## Verifying a translation

1. Set your HA user's language and reload the integration.
2. **JSON validity:**
   ```
   python3 -c "import json,glob;[json.load(open(f)) for f in glob.glob('custom_components/probe_ability/translations/*.json')+['custom_components/probe_ability/strings.json','custom_components/probe_ability/www/cook_presets.json']]"
   ```
3. Add/reconfigure the integration and check the dialog, the temperature-unit dropdown,
   and the service descriptions under Developer Tools → Actions.
4. Load the card and walk an idle → cook → done cycle; confirm the buttons, ring labels,
   and preset selector are translated.
5. Start a cook from a preset and confirm the stored `cook_name` is still the canonical
   English string (e.g. `Beef Rib Eye Medium Rare`) — this proves the display/key
   separation is intact.
