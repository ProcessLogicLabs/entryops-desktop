# ISF web-UI selector recording

The ISF Filing tab pre-fills the e2open ISF web form using selectors stored in
`field_map.json`. This document tells you how to (re)build that file using
Playwright's codegen recorder.

You only need to do this once — and again any time e2open changes their UI in
a way that breaks one of the selectors. The runner reports the failing field
name in the log, which tells you which entry in `field_map.json` to update.

## Prerequisites (one-time setup on a workstation with e2open access)

1. Verify **Google Chrome** is installed (corp policy normally already pushes
   it). The runner uses `channel="chrome"` against the system Chrome with a
   fresh ephemeral profile, so your daily Chrome session — extensions,
   cookies, saved logins — is untouched.
2. Install Python 3.11 (matches the DocHopper build) and Playwright. Note
   that you do **not** need to run `playwright install chromium` — the
   bundled Chromium download (~150 MB) is unnecessary because the runner
   uses your existing Chrome:

       pip install playwright

3. Have valid e2open ISF credentials ready. **You will type them into the
   real ISF login page during the recording — Playwright captures the
   session, not your password.**

## Recording session (~30 minutes)

1. Open a terminal and run (the `--channel=chrome` flag matches what the
   runner uses, so the selectors you record against your installed Chrome
   are the same ones the runner will hit):

       python -m playwright codegen --channel=chrome --target python --output isf_recording.py https://isf.e2open.com/kc/app/isf

2. A Chrome window opens at the e2open login page **and** an "Inspector"
   window opens beside it.
3. Log in normally. Codegen writes Python lines to `isf_recording.py` for
   every action you take.
4. Click whatever link/button starts a **new ISF filing**.
5. Fill **every relevant field** with a value that's easy to grep later —
   ideally the field's payload key from `field_map.json`. For example:

   - In the ETD field, type `isf_etd_token`
   - In the Vessel field, type `isf_vessel_token`
   - In the Importer Name field, type `isf_importer_name_token`
   - …and so on through every field listed in `field_map.json`.

6. For dropdowns (e.g. Country of Origin), pick any sane value — the
   `select_option` action will reveal the form's option-value format
   (often a 2-letter ISO code; sometimes a full name). Note the format you
   see and update the `value_map` in `field_map.json` if pre-mapping is
   needed.
7. For the **HTSUS codes** field, click whatever "add row" button the form
   uses, then enter codes in two rows so the recorder captures both the
   row-add button and the per-row input selector.
8. **Stop before clicking Submit.** We want the script to capture the
   pre-submit state only.
9. Close the Chromium window. The Inspector window will leave you with a
   complete `isf_recording.py`.

## Translating the recording into `field_map.json`

Open `isf_recording.py` in a text editor. You'll see lines like:

```python
page.get_by_label("ETD").fill("isf_etd_token")
page.get_by_label("Vessel name").fill("isf_vessel_token")
page.get_by_role("combobox", name="Country of origin").select_option("CN")
```

For each line, copy the locator into the matching entry in `field_map.json`:

```jsonc
{
  "fields": {
    "isf_etd": {
      "selector": "internal:label=ETD",
      "type": "fill",
      "format": "MM/DD/YYYY"
    },
    "isf_vessel": {
      "selector": "internal:label=Vessel name",
      "type": "fill"
    },
    "isf_country_of_origin": {
      "selector": "internal:role=combobox[name='Country of origin']",
      "type": "select_option"
    }
  }
}
```

Selector formats Playwright accepts:

| Recording call | JSON `selector` |
|---|---|
| `page.locator("#etd")` | `"#etd"` |
| `page.get_by_label("ETD")` | `"label=ETD"` *or any unique CSS that wraps the input* |
| `page.get_by_role("textbox", name="Vessel")` | `"role=textbox[name='Vessel']"` |
| `page.get_by_test_id("vessel-input")` | `"[data-testid='vessel-input']"` |

If you're unsure, plain CSS / XPath always works — open browser DevTools,
right-click the field, and copy a stable selector (`id`, `name`, or
`[name='...']`).

## Action keys to populate

In the `actions` block:

- `new_isf` — the button or link that starts a new ISF filing from the
  e2open landing page **after** login. The runner clicks this once before
  starting the field fill.

If your account lands on a "create new" form by default, you can leave
`new_isf.selector` empty and the runner will skip that click.

## Field-map version stamping

Bump `version` to today's date plus a counter (e.g. `2026-04-29.1`) every
time you save. The runner logs a warning when the field map's version
changes, which helps when debugging.

## Handing the file off

The default location DocHopper loads is:

    Dochopper/isf_filing/field_map.json

Power users can override via the `isf_field_map_path` setting in
`billing_settings`, which lets you point a deployed install at a shared
network copy without redeploying.
