# Bambu / Orca Filament Profile Diff — Codex Handoff

## Project goal

Build a practical multi-way diff tool for Bambu Studio and OrcaSlicer filament profiles.

The tool should make it easy to compare profiles such as:

- `My profile original`
- `My profile retuned`
- `Generic PETG`
- `Bambu PETG HF`
- `Bambu PETG Basic`

The key requirement is that comparisons must be **inheritance-aware**. A normal JSON diff is misleading because Bambu/Orca filament presets are often sparse child/diff presets that inherit most settings from a base profile.

The tool should support both:

1. **Raw comparison** — compare only keys physically present in each JSON file.
2. **Effective comparison** — recursively resolve `inherits` and compare the values the slicer effectively sees.

For effective comparisons, it is useful to show the **source profile** that supplied each value.

---

## Current files

Latest implementation:

- `profile_diff.py`
- `readme.md`

The latest script was functionally tested after the selector-only CLI cleanup.

Verified SHA-256 of `profile_diff.py` after that cleanup:

```text
0d8eea6baa79d86c9335b889391bfe4152486481eabff537b9844794148a1113
```

---

## Current CLI capabilities

### Multi-way profile comparison

Any number of profiles can be compared:

```bash
python profile_diff.py \
  --select "My profile original" \
  --select "My profile retuned" \
  --select "Generic PETG @base" \
  --select "Bambu PETG HF @BBL H2C" \
  --only-different \
  --show-source
```

### Effective vs raw mode

Default:

```bash
--mode effective
```

This recursively resolves inheritance.

Raw mode:

```bash
--mode raw
```

This compares only keys directly present in each JSON file.

### Difference filtering

```bash
--only-different
```

Hides rows where all compared profiles have the same value.

### Source provenance

```bash
--show-source
```

Shows which profile in the inheritance chain supplied each effective value.

### Parameter filtering

Regex filter:

```bash
--keys 'counter_|hole_|temperature'
```

Example for dimensional compensation:

```bash
--keys '^(counter_|hole_|diameter_limit|circle_compensation_speed)'
```

### Output formats

Terminal output is default.

Also supports:

```bash
--csv output.csv
--html output.html
```

HTML output is self-contained.

---

## Automatic profile discovery

The tool can search for profiles by name without requiring the user to know exact JSON paths.

### Search by profile name

```bash
python profile_diff.py --find-profile "PETG HF"
```

Search is case-insensitive and allows substring matches.

### Show discovered locations

```bash
python profile_diff.py --list-search-paths
```

### Restrict by slicer

```bash
--app bambu
--app orca
--app both
```

Default is `both`.

### Manual additional search roots

```bash
--search-dir /some/custom/profile/tree
```

### Disable automatic discovery

```bash
--no-auto-discover
```

---

## Platform discovery targets

The script attempts to find both **user profile directories** and **bundled/system profile directories**.

### macOS

Typical user roots:

```text
~/Library/Application Support/BambuStudio
~/Library/Application Support/OrcaSlicer
```

Typical bundled resources:

```text
/Applications/BambuStudio.app/Contents/Resources
/Applications/Bambu Studio.app/Contents/Resources
/Applications/OrcaSlicer.app/Contents/Resources
```

It also checks user-local `~/Applications/...` app bundles.

### Windows

Typical user roots:

```text
%APPDATA%\BambuStudio
%APPDATA%\OrcaSlicer
```

It also checks `%LOCALAPPDATA%` and common `Program Files` / local Programs resource locations.

### Linux

Typical user roots:

```text
~/.config/BambuStudio
~/.config/OrcaSlicer
```

Flatpak candidates include:

```text
~/.var/app/com.bambulab.BambuStudio/config/BambuStudio
~/.var/app/com.orcaslicer.OrcaSlicer/config/OrcaSlicer
```

Common system/shared-data locations under `/usr/share`, `/usr/local/share`, and `~/.local/share` are also searched.

### Portable/custom installs

Best-effort support for `data_dir` near detected executables.

Optional environment-variable overrides:

```text
BAMBU_STUDIO_CONFIG_DIR
BAMBUSTUDIO_CONFIG_DIR
ORCASLICER_CONFIG_DIR
ORCA_SLICER_CONFIG_DIR
```

---

## Selector-based machine / nozzle filtering

Each comparison column is specified with one `--select` value:

```text
PROFILE[;machine=MACHINE][;nozzle=DIAMETER][;label=DISPLAY NAME]
```

Machine matching is case-insensitive against effective `compatible_printers`.
Nozzle matching parses the diameter from strings such as:

```text
Bambu Lab H2C 0.4 nozzle
Bambu Lab H2C 0.6 nozzle
```

### Compare Generic PETG vs Bambu PETG HF for H2C / 0.4

```bash
python profile_diff.py \
  --select "Generic PETG;machine=H2C;nozzle=0.4" \
  --select "Bambu PETG HF;machine=H2C;nozzle=0.4" \
  --only-different \
  --show-source
```

### Compare one material across nozzle sizes

Use one selector for each comparison column:

```bash
python profile_diff.py \
  --select "Bambu PETG HF;machine=H2C;nozzle=0.4" \
  --select "Bambu PETG HF;machine=H2C;nozzle=0.6" \
  --only-different \
  --show-source
```

### Compare multiple materials across multiple nozzle sizes

List each desired material/nozzle combination explicitly:

```bash
python profile_diff.py \
  --select "Generic PETG;machine=H2C;nozzle=0.4" \
  --select "Generic PETG;machine=H2C;nozzle=0.6" \
  --select "Bambu PETG HF;machine=H2C;nozzle=0.4" \
  --select "Bambu PETG HF;machine=H2C;nozzle=0.6" \
  --only-different
```

This produces four effective comparison columns.

---

## Important Bambu profile naming quirk

Do **not** assume filename/profile-name text alone fully identifies nozzle compatibility.

Example from current Bambu Studio profiles:

```text
Generic PETG @BBL H2C.json
```

is compatible with:

```text
Bambu Lab H2C 0.6 nozzle
Bambu Lab H2C 0.8 nozzle
```

while the 0.4 version is a separate file:

```text
Generic PETG @BBL H2C 0.4 nozzle.json
```

Therefore machine/nozzle selection should be based primarily on the effective:

```json
"compatible_printers": [...]
```

rather than filename conventions.

This was one of the reasons machine/nozzle filtering was added.

---

## Nozzle material caveat

The selector's `nozzle=...` option filters **diameter**, not nozzle material.

Filament profiles generally express compatibility as printer + diameter:

```text
Bambu Lab H2C 0.4 nozzle
```

They do not normally distinguish:

- hardened steel
- stainless steel

inside the filament profile `compatible_printers` field.

If nozzle-material-aware comparison is desired later, it likely needs to use printer/nozzle hardware configuration metadata rather than filament-profile compatibility alone.

---

## Current inheritance model

A profile can have:

```json
"inherits": "Some Parent Profile"
```

The tool indexes available profile JSON files by:

- profile `"name"`
- filename stem
- full path

For effective mode it recursively resolves the parent chain.

Each effective key keeps:

```text
effective value
source profile name
```

The source is the nearest profile in the inheritance chain that explicitly supplied that key.

---

## Root vs derived profile context

This project started partly because Bambu Studio treats root and derived filament presets differently in some UI paths.

Current Bambu Studio AMS material-selection code contains a root-only filter conceptually equivalent to:

```cpp
if (filaments.get_preset_base(preset) != &preset)
    continue;
```

For user presets, `get_preset_base()` walks `inherits` until it reaches a user root.

This means a normal user-created diff preset can be valid for slicing yet absent from some AMS material dropdowns.

This is one reason the diff tool should make inheritance chains and source values very visible.

---

## Dimensional compensation context

Parameters of interest include:

```text
counter_coef_1
counter_coef_2
counter_coef_3
counter_limit_min
counter_limit_max

hole_coef_1
hole_coef_2
hole_coef_3
hole_limit_min
hole_limit_max

diameter_limit
circle_compensation_speed
```

Current common Bambu filament-profile values observed in `fdm_filament_common` include:

```text
counter_coef_1 = 0
counter_coef_2 = 0.008
counter_coef_3 = -0.041
counter_limit_min = -0.035
counter_limit_max = 0.033

hole_coef_1 = 0
hole_coef_2 = -0.008
hole_coef_3 = 0.23415
hole_limit_min = 0.088
hole_limit_max = 0.22

diameter_limit = 50
circle_compensation_speed = 200
```

For Bambu PETG HF on newer 0.4 mm printer profiles such as H2C/H2D/H2S/P2S, an explicit calibrated set was observed:

```text
counter_coef_2 = 0.0058
counter_coef_3 = 0.0107
counter_limit_min = 0.01
counter_limit_max = 0.15

hole_coef_2 = -0.0042
hole_coef_3 = 0.2006
hole_limit_min = 0.09
hole_limit_max = 0.20
```

X1C Bambu PETG HF did not explicitly override these and inherited the common/default set.

This comparison is a good example of why **effective values + source profile** matter.

---

## Bambu Studio / AMS observations relevant to future tooling

In current Bambu Studio source, AMS material selection filters filament presets using several conditions.

For the classic AMS material settings path:

1. Only root presets are included.
2. System and user presets are handled separately.
3. User presets are only included if the connected machine reports support for user presets.
4. `compatible_printers` must match the active machine/nozzle.
5. `filament_id` must be non-empty.
6. Results are deduplicated by `filament_id`.
7. A usable alias/display name must exist.

The newer Filament Manager code has already relaxed the root-only behavior for user-created derived presets and avoids deduping user presets solely by `filament_id`.

This difference may be useful if this project eventually grows from a diff tool into a profile diagnostic tool.

---

## Recommended next improvements

### 1. Selector syntax (completed)

Repeated per-profile selectors are now the only comparison syntax:

```bash
--select "Bambu PETG HF;machine=H2C;nozzle=0.4"
--select "Bambu PETG HF;machine=H2C;nozzle=0.6"
```

This allows comparisons such as:

```text
Bambu PETG HF / H2C / 0.4
Bambu PETG HF / X1C / 0.4
Generic PETG / H2C / 0.6
```

in one invocation. The former `--profile`, global `--machine`, and global
`--nozzle` arguments have been removed.

### 2. Add structured grouping

Instead of one alphabetical list, categorize keys into groups:

```text
Identity / metadata
Printer compatibility
Temperature
Bed temperature
Flow / volumetric speed
Cooling
Retraction / wipe
AMS / drying
Dimensional compensation
Material properties
G-code
Other
```

Add CLI options such as:

```bash
--group dimensional
--group temperature
--group cooling
```

### 3. Better table formatting

Potential improvements:

- auto column width
- multiline value wrapping
- richer ANSI output
- visually mark unique values
- visually mark inherited vs explicitly overridden values
- add an `explicit?` row/indicator
- show changed-only source lineage

### 4. Better HTML viewer

Could add:

- sticky first column
- per-group collapsible sections
- search box
- toggle effective/raw
- toggle show source
- highlight cells that differ from first profile
- highlight values explicitly overridden in that profile
- inheritance chain panel
- profile metadata header

### 5. `--explain KEY`

Example:

```bash
python profile_diff.py ... --explain counter_coef_2
```

Possible output:

```text
Bambu PETG HF @BBL H2C
  effective: 0.0058
  source: Bambu PETG HF @BBL H2C
  inheritance:
    Bambu PETG HF @base
      -> fdm_filament_pet
      -> fdm_filament_common

Generic PETG @BBL H2C 0.4 nozzle
  effective: 0.008
  source: fdm_filament_common
```

This would be extremely useful.

### 6. Explicit override diff

Add a mode showing only keys that a selected profile explicitly overrides relative to its parent.

Possible CLI:

```bash
--mode overrides
```

For each profile:

```text
profile value
parent effective value
difference
```

This is especially useful for sparse Bambu preset JSON.

### 7. Profile relationship graph

Optional output:

```bash
--graph inheritance.dot
```

or Mermaid text.

Useful for understanding complicated vendor trees.

### 8. Machine profile integration

If nozzle material and other hardware distinctions matter, index machine profiles too.

Potentially resolve:

```text
machine
nozzle diameter
nozzle material/type
extruder variant
```

Then allow selectors beyond `compatible_printers`.

### 9. Detect duplicate profile identities

Useful diagnostics:

```text
same filament_id, different names
same setting_id, different files
same profile name in Bambu and Orca
multiple user profiles inheriting same system profile
```

### 10. Test suite

Add `pytest` coverage for:

- simple inheritance
- multi-level inheritance
- missing parent
- cyclic inheritance
- duplicate names
- same profile present in both slicers
- profile substring ambiguity
- machine filtering
- nozzle filtering
- selector-based nozzle comparison
- explicit multi-column selection
- effective source tracking
- raw vs effective mode
- JSON arrays and scalar values
- malformed JSON ignored during indexing

---

## Suggested project structure if expanding beyond one script

```text
bambu-profile-diff/
├── pyproject.toml
├── README.md
├── src/
│   └── bambu_profile_diff/
│       ├── __init__.py
│       ├── cli.py
│       ├── discovery.py
│       ├── profiles.py
│       ├── inheritance.py
│       ├── selectors.py
│       ├── diff.py
│       └── render.py
└── tests/
    ├── fixtures/
    ├── test_discovery.py
    ├── test_inheritance.py
    ├── test_selectors.py
    └── test_diff.py
```

The current one-file implementation is still a good prototype, but this structure would make the next iteration easier to maintain.

---

## Design principles to preserve

1. **Never compare sparse JSON blindly** when effective profile values are desired.
2. Keep **raw** and **effective** modes separate.
3. Preserve **source provenance** for inherited values.
4. Prefer `compatible_printers` over filename heuristics for machine/nozzle selection.
5. Do not silently choose between ambiguous Bambu vs Orca copies.
6. Exact path should always be accepted as an escape hatch.
7. Machine/nozzle filters should narrow candidates, not alter profile data.
8. Avoid assuming Bambu profile naming conventions are globally consistent.

---

## First thing Codex should do

Before changing behavior:

1. Open `profile_diff.py`.
2. Run:

```bash
python profile_diff.py --help
```

3. Create a temporary synthetic profile tree and verify:
   - name lookup
   - inheritance
   - `--select "Generic PETG;machine=H2C;nozzle=0.4"`
   - inheritance and effective source tracking
   - multiple selectors across nozzle sizes

4. Then refactor only after behavior is covered by tests.

A strong next milestone would be:

> Continue improving diagnostics and tests around the selector-only grouped comparison workflow.
