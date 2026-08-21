# Bambu Studio / OrcaSlicer filament profile multi-way diff

`profile_diff.py` compares any number of filament profile JSON files and can recursively resolve `inherits` before comparing effective values.

## Automatic discovery

By default it searches common Bambu Studio and OrcaSlicer locations on macOS, Windows, and Linux, including user config trees and common bundled `resources/profiles` locations.

Typical user roots include:

| OS | Bambu Studio | OrcaSlicer |
|---|---|---|
| Windows | `%APPDATA%\\BambuStudio` | `%APPDATA%\\OrcaSlicer` |
| macOS | `~/Library/Application Support/BambuStudio` | `~/Library/Application Support/OrcaSlicer` |
| Linux | `~/.config/BambuStudio` | `~/.config/OrcaSlicer` |

Linux Flatpak locations and common application resource directories are also checked on a best-effort basis.

For custom/portable installs, add `--search-dir`, or set one of:

- `BAMBU_STUDIO_CONFIG_DIR`
- `BAMBUSTUDIO_CONFIG_DIR`
- `ORCASLICER_CONFIG_DIR`
- `ORCA_SLICER_CONFIG_DIR`

## Search for profiles

```bash
python profile_diff.py --find-profile "PETG HF"
```

Search is case-insensitive and accepts substrings. Results show the app/source classification and exact path.

To inspect discovered locations:

```bash
python profile_diff.py --list-search-paths
```

Limit auto-discovery to one application:

```bash
python profile_diff.py --app bambu --find-profile "PETG"
python profile_diff.py --app orca --find-profile "PETG"
```

## Compare profiles

```bash
python profile_diff.py \
  --select "My profile original" \
  --select "My profile retuned" \
  --select "Generic PETG @base" \
  --select "Bambu PETG HF @BBL H2C" \
  --select "Bambu PETG Basic @BBL H2C" \
  --only-different \
  --show-source
```

At least two `--select` values are required for `effective` and `raw` comparisons. Override reports accept one or more selections because each profile is compared with its own parent. When the same managed profile exists in both an application's `system` and bundled `resources/profiles` trees, automatic selection uses the system copy. If their parsed JSON differs, a warning on stderr shows both paths. Other exact-name ambiguities across apps or variants still print the matching files rather than silently picking one. An exact JSON path is always accepted.

## Effective vs raw diff

`--mode effective` is the default. It recursively follows `inherits`, so you see what the slicer effectively gets.

```bash
python profile_diff.py ... --mode effective --show-source
```

`--mode raw` compares only keys physically stored in each selected JSON file.

```bash
python profile_diff.py ... --mode raw
```

## Audit explicit overrides

`--mode overrides` produces a separate report for every selected profile. Each report contains only keys physically set on that profile and shows:

- the profile's explicit value
- the immediate parent's effective value after recursively resolving its inheritance
- whether the explicit value is `changed`, `same`, or `added`
- the ancestor profile that supplied the parent value

Unlike the multi-way modes, a single selection is enough:

```bash
python profile_diff.py \
  --select "My PETG retuned" \
  --mode overrides
```

Audit several profiles in one command and hide redundant overrides whose value is identical to the parent:

```bash
python profile_diff.py \
  --select "My PETG original;label=Original" \
  --select "My PETG retuned;label=Retuned" \
  --mode overrides \
  --only-different \
  --keys 'temperature|flow|counter_'
```

Sources are always included in override reports, so `--show-source` is unnecessary in this mode. Filters from `--keys`, `--group`, and `--include-meta` still apply. In override mode, `--only-different` removes only explicit values that equal the parent's effective value; added values remain visible.

A root profile is labeled `NO PARENT`. If a declared parent is missing or an inheritance cycle prevents resolution, the report remains usable: explicit child keys are still listed, the parent status names the problem, and the parent value, difference, and source are marked `unavailable`.

Override reports support the same file outputs:

```bash
python profile_diff.py --select "My PETG retuned" --mode overrides --csv overrides.csv
python profile_diff.py --select "My PETG retuned" --mode overrides --html overrides.html
```

## Filter parameters

```bash
python profile_diff.py ... \
  --keys '^(counter_|hole_|diameter_limit|circle_compensation_speed)' \
  --only-different \
  --show-source
```

## Output formats

```bash
python profile_diff.py ... --csv petg-diff.csv
python profile_diff.py ... --html petg-diff.html
```

The HTML viewer is self-contained and groups parameters by purpose. It includes:

- profile metadata and inheritance chains
- collapsible parameter groups
- a parameter/value search box
- sticky table headers and parameter names
- explicit/inherited value styling
- highlighting for values that differ from the first profile
- a source-profile visibility toggle (`--show-source` controls its initial state)

## Profile selectors

Each `--select` creates one comparison column and can include its own machine or nozzle filter:

```bash
python profile_diff.py \
  --select "Bambu PETG HF;machine=H2C;nozzle=0.4" \
  --select "Bambu PETG HF;machine=X1C;nozzle=0.4" \
  --select "Generic PETG;machine=H2C;nozzle=0.6" \
  --only-different \
  --show-source
```

The selector format is:

```text
PROFILE[;machine=MACHINE][;nozzle=DIAMETER][;label=DISPLAY NAME]
```

Quote the whole selector in the shell because semicolons otherwise separate commands. `machine`, `nozzle`, and `label` may appear in any order, but each may appear only once.

Machine matching is case-insensitive against effective `compatible_printers`. Nozzle diameter is parsed from compatibility strings such as `Bambu Lab H2C 0.4 nozzle`. Filament profiles generally do not distinguish nozzle material.

To compare one material across nozzle sizes, use one selector per column:

```bash
python profile_diff.py \
  --select "Bambu PETG HF;machine=H2C;nozzle=0.4;label=HF 0.4" \
  --select "Bambu PETG HF;machine=H2C;nozzle=0.6;label=HF 0.6" \
  --only-different
```

## Parameter groups

Use repeated `--group` to restrict terminal, CSV, and HTML output to semantic groups:

```bash
python profile_diff.py \
  --select "Generic PETG;machine=H2C;nozzle=0.4" \
  --select "Bambu PETG HF;machine=H2C;nozzle=0.4" \
  --group temperature \
  --group dimensional \
  --html petg-focused.html
```

List the available group slugs and labels with:

```bash
python profile_diff.py --list-groups
```

The groups are `identity`, `compatibility`, `temperature`, `flow`, `cooling`, `retraction`, `ams`, `dimensional`, `material`, `gcode`, and `other`. Metadata remains hidden unless `--include-meta` is supplied, even when `--group identity` is selected.

## Maintainer documentation

- [`AGENTS.md`](AGENTS.md) contains the repository-wide contribution rules and required checks.
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) explains profile indexing, inheritance resolution, diff-mode semantics, filtering, and renderer contracts.
- [`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md) covers the test strategy, fixture conventions, smoke commands, and change checklists.
- [`docs/BAMBU_PROFILE_DIFF_CODEX_HANDOFF.md`](docs/BAMBU_PROFILE_DIFF_CODEX_HANDOFF.md) is a historical research and design snapshot. It is retained for context but is not authoritative for current behavior.
