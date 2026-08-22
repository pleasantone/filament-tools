# Filament Tools

Filament Tools discovers, inspects, compares, builds, validates, edits, and
installs Bambu Studio and OrcaSlicer filament profiles. It understands sparse
inheritance and preserves the source of every effective value.

The project provides an intent-oriented CLI and a local visual profile
workbench. Both use the same typed drafts and composition recipes, resolver,
validation, identity, and installation services.

## Install for development

[uv](https://docs.astral.sh/uv/) manages the Python environment, dependencies,
lockfile, and command execution. Python 3.10 or newer is required.

```bash
uv sync
uv run filament-tools --help
```

`uv sync` installs the default development dependency group and creates a
uv-managed `.venv` when needed. The console command can also be run as
`uv run python -m filament_tools`.

## Discovery and selection

The default catalog searches common Bambu Studio and OrcaSlicer user, system,
and application-resource locations on macOS, Windows, and Linux.

```bash
uv run filament-tools catalog paths
uv run filament-tools catalog search "PETG HF"
uv run filament-tools --app orca catalog search PETG
uv run filament-tools --search-dir /portable/profiles catalog search PETG
```

Set `BAMBU_STUDIO_CONFIG_DIR`, `BAMBUSTUDIO_CONFIG_DIR`,
`ORCASLICER_CONFIG_DIR`, or `ORCA_SLICER_CONFIG_DIR` for portable layouts.
Use `--no-auto-discover` for a controlled catalog.

Managed system and bundled profiles with the same relative path are treated as
copies. The system copy wins; a warning identifies both files when their parsed
JSON differs. Unrelated same-name profiles remain ambiguous, and an exact JSON
path is always accepted.

Selectors support effective printer compatibility filters:

```text
PROFILE[;machine=MACHINE][;nozzle=DIAMETER][;label=DISPLAY NAME]
```

Quote selectors containing semicolons. Machine/nozzle matching uses the
resolved `compatible_printers` value, not filename conventions.

## Inspect and compare

Inspect raw JSON, recursively resolved effective settings, or explicit child
overrides against the immediate parent:

```bash
uv run filament-tools inspect "My PETG" --view raw
uv run filament-tools inspect "My PETG" --view effective --show-source
uv run filament-tools inspect "My PETG" --view overrides
```

Compare two or more profiles:

```bash
uv run filament-tools compare \
  "Generic PETG;machine=H2C;nozzle=0.4;label=Generic" \
  "Bambu PETG HF;machine=H2C;nozzle=0.4;label=HF" \
  --only-different --show-source
```

`--mode effective` is the default; `--mode raw` compares only physically stored
keys. In sparse per-extruder vectors, `"nil"` positions inherit the matching
parent elements and retain element-level provenance. Filters are applied once to
the shared report model:

```bash
uv run filament-tools compare PROFILE_A PROFILE_B \
  --keys 'temperature|flow|counter_' \
  --group temperature --group flow \
  --only-different --csv comparison.csv --html comparison.html
```

Semantic groups are `identity`, `compatibility`, `temperature`, `flow`,
`cooling`, `retraction`, `ams`, `dimensional`, `material`, `gcode`, and `other`.
Metadata is hidden unless `--include-meta` is supplied. CSV and HTML paths are
created exclusively; existing reports are not overwritten.

## Build a sparse child

A sparse child expresses the effective behavioral difference between a base
and a modified source:

```bash
uv run filament-tools build sparse \
  --base "Tecbears PETG HS Matte;machine=H2C;nozzle=0.4" \
  --source "/path/to/Tecbears PETG HS Matte tuned.json" \
  --name "Tecbears PETG HS Matte tuned sparse" \
  --output "/output/Tecbears PETG HS Matte tuned sparse.json"
```

The generated child inherits its material `filament_id`, omits cloud metadata,
sets `filament_settings_id` to its new name, and retains Bambu's required
`filament_extruder_variant` structural field. A sparse child cannot express the
removal of a value supplied by its base; that is a validation error.

Add typed edits using JSON values and override compatibility with repeatable
exact printer preset names:

```bash
uv run filament-tools build sparse ... \
  --set 'nozzle_temperature=["255"]' \
  --set 'enable_pressure_advance=true' \
  --compatible-printer "Bambu Lab H2C 0.4 nozzle"
```

## Flatten into an AMS root

`build root` resolves the source inheritance chain, applies edits/removals, and
writes a complete inheritance-free user profile:

```bash
uv run filament-tools build root \
  --source "My tuned sparse profile" \
  --name "My PETG H2C 0.4" \
  --output "/output/My PETG H2C 0.4.json"
```

The output has no `inherits`, has a nonempty material `filament_id`, keeps exact
`compatible_printers`, and excludes `setting_id` and `.info` fields. The default
identity policy retains the source's effective `filament_id`. Other policies:

```bash
uv run filament-tools build root ... --identity reuse
uv run filament-tools build root ... --identity generate --material-name "My PETG"
uv run filament-tools build root ... --identity explicit --filament-id P1234567
```

`generate` implements Bambu Studio's `P` plus seven MD5 hexadecimal characters
algorithm and collision fallback. `reuse` first retains/reuses a known matching
material identity, then generates one when necessary. Cloud `setting_id` is
never generated; the slicer assigns it during synchronization.

## Build a machine/nozzle family

Bambu's conservative custom-filament pattern creates separate roots per target
while sharing one material identity:

```bash
uv run filament-tools build family \
  --source "My tuned profile" \
  --name "My PETG" \
  --variant "My PETG H2C 0.4::Bambu Lab H2C 0.4 nozzle" \
  --variant "My PETG H2C 0.6::Bambu Lab H2C 0.6 nozzle" \
  --output-dir /output
```

Separate several compatibility names with `|` inside one variant. All generated
variants share one `filament_id`; each has its own name and
`filament_settings_id`. Saved draft projects and the editor API also support
variant-specific setting edits.

## Draft projects

A project records editable intent and source/base fingerprints without embedding
installed source profiles:

```bash
uv run filament-tools project init \
  --source "My tuned profile" --base "Generic PETG" \
  --name "My tuned sparse" --output my-petg.ftdraft

uv run filament-tools project build my-petg.ftdraft /output
```

When loaded, fingerprints detect source or base drift. Projects are JSON files
with a versioned `filament-tools-draft-v1` envelope.

## Validate and install

Validate a generated file and, for a child, resolve its inheritance:

```bash
uv run filament-tools --search-dir /profiles validate "/output/My PETG.json"
```

Diagnostics have stable codes and error/warning severity. Root validation checks
AMS identity, compatibility, filename/name agreement, cloud metadata, and user
preset fields. When machine profiles are indexed, unknown exact compatibility
names produce warnings.

Preview installation before writing:

```bash
uv run filament-tools install "/output/My PETG.json" --dry-run
uv run filament-tools install "/output/My PETG.json"
uv run filament-tools install profiles/*.json --app orca
```

Bambu Studio is the default. Use `--config-dir` for a portable/test tree and
`--user-folder` to override the active `preset_folder`. Roots are installed to
`user/<folder>/filament/base`; sparse children go to `user/<folder>/filament`.
The installer validates every operation before writing, refuses JSON or `.info`
collisions, creates files exclusively, and rolls back files from the current
transaction if a later write fails. It never creates or copies `.info` files.
Restart the slicer after installation.

## Local visual workbench

Launch the editor on localhost:

```bash
uv run filament-tools editor
```

Open `http://127.0.0.1:8765`. The workbench follows the editing workflow:

- **Library** searches the complete preferred catalog on the server, defaults
  to filament presets, and filters by application, source, material/vendor,
  machine, and nozzle. Inspection separates effective values, explicit
  overrides, provenance, and raw JSON.
- **Compare** automatically refreshes a two-or-more-profile effective, raw, or
  override grid. Choose a baseline and filter by setting, metadata, semantic
  group, or difference; provenance and numeric deltas remain visible.
- **Create profile** starts from the comparison or an independent source set.
  Select donor values directly in the full-width grid, with custom values,
  removals, group actions, filters, and undo/redo in contextual panels.
- **Review & install** chooses sparse or full output, previews and validates the
  current recipe revision, writes JSON, saves projects, and installs only from a
  current reviewed plan. Recipe changes clear stale output and disable writes.
- **Lineage explorer** loads one profile, its complete ancestors, and immediate
  dependents on demand. Descendant branches and catalog-wide problems are
  deliberate actions rather than startup work.

Composition output is an explicit choice between a **sparse inherited profile**
and a **full AMS-compatible profile**. Switching modes preserves every setting
selection. Sparse output requires an inheritance parent and contains only its
behavioral delta. Full output contains all effective behavior, removes
`inherits`, and applies the selected material-identity and exact compatibility
policy. Full-output compatibility uses searchable exact printer-preset chips;
optional family variants use structured name and compatibility rows and share
one material identity.

Composition projects use the versioned `filament-tools-composition-v1` envelope
and preserve source fingerprints plus the recipe for every explicit choice. The
UI previews installation destinations before a separate confirmation action;
writes and installation retain the same no-overwrite behavior as the CLI. It
warns before replacing explicit composition choices, tracks saved/unsaved and
preview-stale state, keeps a browser-local recovery draft, and warns before
leaving a page with unsaved work. **Quick start** opens the guided six-step
walkthrough and terminology reference; it opens automatically on first use and
remains available from the header.

### Local macOS application

On Apple Silicon Macs, build a self-contained local application bundle with:

```bash
./scripts/build_macos_app.sh
```

The command creates `dist/Filament Tools.app`. It bundles Python, NiceGUI, and
the native webview runtime, uses the same automatic Bambu Studio and OrcaSlicer
profile discovery as the CLI, and is ad-hoc signed for local use. The app writes
startup diagnostics to `~/Library/Logs/Filament Tools/filament-tools.log` and
keeps its webview workspace data under `~/Library/Application Support/Filament
Tools/WebView`. This local build is not notarized or intended for redistribution.

## Maintainer documentation

- [`docs/PRODUCT_ARCHITECTURE.md`](docs/PRODUCT_ARCHITECTURE.md) records the
  product analysis, package boundaries, required features, and optional roadmap.
- [`docs/UI_UX_AUDIT_HANDOFF.md`](docs/UI_UX_AUDIT_HANDOFF.md) records the
  visual-workbench audit, real-catalog scale findings, prioritized redesign, and
  implementation acceptance criteria.
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) defines runtime invariants.
- [`docs/BAMBU_PROFILE_IDENTITY.md`](docs/BAMBU_PROFILE_IDENTITY.md) records the
  source-verified Bambu/Orca identity and installation model.
- [`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md) covers tests and release checks.
