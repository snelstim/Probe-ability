# Translating Probe-ability

Every piece of user-facing text in Probe-ability lives in **one file per language**:
`custom_components/probe_ability/translations/<lang>.json`. That covers the config flow and options,
entity names, service descriptions, error toasts, the Lovelace card, the preset names, the Live
Activity text and the auto-stop notification.

English (`en.json`) is the source of truth. Home Assistant fills any key missing from another
language with its English text, so a partial translation is safe.

[![Translation status per language](https://hosted.weblate.org/widget/probe-ability/multi-auto.svg)](https://hosted.weblate.org/engage/probe-ability/)

## Contributing a translation

Translations are managed on **[Hosted Weblate](https://hosted.weblate.org/engage/probe-ability/)**.
You can add a new language, fix a string or fill gaps in an existing language right in the
browser, with no git or JSON editing. Sign in, pick a language (or **Start new translation**) and
translate. Anything you leave out simply shows in English.

Weblate collects the changes and opens a pull request here. The **Translations** check runs on
it, and the maintainer merges it like any other PR.

Tips:

- Read the **Explanation** Weblate shows next to a string when there is one. Short UI labels like
  `remaining` or `tap_for_temp` are easiest to get right with the card in front of you.
- Weblate refuses to save a string whose `{placeholders}` don't match English (see
  [Placeholders](#placeholders)).
- Questions about a string? Use the comment box in Weblate or open an issue.

> **Please don't open pull requests that edit `translations/<lang>.json` for languages other than
> English.** Weblate owns those files, and a direct edit conflicts with its next pull request. If
> you'd rather work offline, download the file from Weblate, then upload it back there.

## How it works (maintainers)

- **English lives in git.** Edit `en.json` in a normal commit. A GitHub webhook tells Weblate to
  pull the change.
- **New English key:** it appears as untranslated in every language, and shows in English until
  someone translates it. CI keeps passing and lists the gap as a warning.
- **Reworded English string:** Weblate marks existing translations **Needs editing**, so they get
  revisited.
- **Removed English key:** Weblate's *Cleanup translation files* add-on removes it from the other
  languages in its next pull request. CI warns about leftovers until then.
- **Adding a preset:** add it to `cook_presets.json` and its English name to `en.json`
  (see [Preset names](#preset-names-and-the-canonical-label)). Weblate picks it up from there.
- **CI** (`.github/workflows/translations.yml`) runs `python3 test_translations.py` on every
  push and PR. It fails on real problems (a changed `{placeholder}`, an empty string, leading or
  trailing spaces, HTML) and prints warnings plus a completeness table for untranslated keys.
- **Language codes** follow Home Assistant (`pt-BR`, `zh-Hans`). Weblate is set to the hyphenated
  BCP style, so it creates files with the right names.

### Languages

For live completeness per language, see the chart above or the Weblate project page.

| Language | Notes |
|----------|-------|
| English (`en`) | Source |
| Dutch (`nl`) | — |
| Romanian (`ro`) | Machine-assisted. Review by a native speaker welcome |

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
`"<id>": "<name>"` under the matching `selector.preset_*` section of `en.json`. The name must equal
the `label`. Translators then see the new name in Weblate.

### Language used

- **The card and dialogs** follow each user's own language (their HA profile).
- **Live Activities and the auto-stop notification** use the server language
  (Settings → System → General), because they go to every target at once. Changing the server
  language takes effect without a restart.

## Verifying a translation

1. `python3 test_translations.py` checks that placeholders match English, that values pass
   hassfest's rules (no empty strings, leading/trailing spaces, HTML or URLs), and that every string the card,
   presets and backend ask for exists. It warns about untranslated keys, and about keys English
   no longer has, then prints a completeness table.
2. Set your HA user's language and reload the integration.
3. Add or reconfigure the integration and check the dialog, the temperature-unit dropdown and the
   service descriptions under Developer Tools → Actions. Open **⋮ → Configure** on the integration
   card and confirm the Live Activities dialog is translated.
4. Reload the dashboard and walk the card through idle → cook → done. Confirm the buttons, ring
   labels, preset selector and card editor are translated.
5. Start a cook from a preset and confirm the stored `cook_name` is still the canonical English
   string (e.g. `Beef Rib Eye Medium Rare`). This proves the display/key separation is intact.
