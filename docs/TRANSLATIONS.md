# Translating Probe-ability

Every piece of user-facing text in Probe-ability lives in **one file per language**:
`custom_components/probe_ability/translations/<lang>.json`. That covers the config flow and options,
entity names, service descriptions, error toasts, the Lovelace card, the preset names, the Live
Activity text and the auto-stop notification.

English (`en.json`) is the source of truth. Home Assistant fills any key missing from another
language with its English text, so a partial translation is safe.

## Adding a language

1. Copy the English file, naming the copy after your
   [HA language code](https://www.home-assistant.io/integrations/frontend/#change-the-language)
   exactly as Home Assistant spells it (`de`, `fr`, `nl`, `pt-BR`, `zh-Hans`, …):

   ```
   cp custom_components/probe_ability/translations/en.json \
      custom_components/probe_ability/translations/xx.json
   ```

2. Translate every **value**. Never change a key.
3. Run `python3 test_translations.py` (see [Verifying](#verifying-a-translation)).

No code changes are needed. `nl.json` is a complete reference translation.

### Placeholders

Leave `{name}`, `{unit}`, `{temp}`, `{eta}`, `{n}`, `{target}`, etc. exactly as they are. You can move
them within the sentence. Home Assistant **discards** a translated string whose placeholders differ
from the English one, logs an error, and shows the English text instead. Keep emoji in values
(🔗 / ⚡) and translate only the words.

## What's in the file

| Section | Used by |
|---------|---------|
| `config`, `options` | Setup, Reconfigure, and the Live Activities options dialog |
| `entity`, `services`, `exceptions` | Entity names, action descriptions, start-cook error toasts |
| `selector.temp_unit` | The temperature-unit dropdown |
| `selector.card` | The Lovelace card and its visual editor |
| `selector.preset_category` / `preset_cut` / `preset_doneness` | Preset names shown in the card, keyed by the `id` in `www/cook_presets.json` |
| `selector.backend` | Live Activity text, the auto-stop notification, and "Probe N" |

> **Why is the card under `selector`?** hassfest only allows Home Assistant's own top-level
> sections, but a selector's `options` map takes any keys. The card loads its strings with the
> `frontend/get_translations` websocket command. The backend loads them with
> `async_get_translations`. Both come from the same file.

### Preset names and the canonical `label`

`www/cook_presets.json` still has an English `label` for each category, cut and doneness. **That
`label` is a key, not display text, so don't translate it there.** The card builds the cook name it
sends to the backend from these English labels (`_makeCookName`), and `ml_predictor.py`'s
`_COOK_NAME_MAP` looks the cook up by that exact string. Translations in `selector.preset_*` only
change what's shown, so stored cook names, ML features and shared data always stay English.

To add a preset: add it to `cook_presets.json` with an `id` and English `label`, then add
`"<id>": "<name>"` under the matching `selector.preset_*` section in **every** language file.
In `en.json` the name must equal the `label`.

### Language used

- **The card and dialogs** follow each user's own language (their HA profile).
- **Live Activities and the auto-stop notification** use the server language
  (Settings → System → General), because they go to every target at once. Changing the server
  language takes effect without a restart.

## Verifying a translation

1. `python3 test_translations.py` checks that every language has the same keys and placeholders
   as English, that values pass hassfest's rules (no leading/trailing spaces, HTML or URLs), and
   that every string the card, presets and backend ask for exists.
2. Set your HA user's language and reload the integration.
3. Add or reconfigure the integration and check the dialog, the temperature-unit dropdown and the
   service descriptions under Developer Tools → Actions. Open **⋮ → Configure** on the integration
   card and confirm the Live Activities dialog is translated.
4. Reload the dashboard and walk the card through idle → cook → done. Confirm the buttons, ring
   labels, preset selector and card editor are translated.
5. Start a cook from a preset and confirm the stored `cook_name` is still the canonical English
   string (e.g. `Beef Rib Eye Medium Rare`). This proves the display/key separation is intact.
