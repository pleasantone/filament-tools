# Runtime architecture and invariants

The README is authoritative for CLI behavior. `PRODUCT_ARCHITECTURE.md` records
the product-level analysis and roadmap. This document describes the implemented
runtime boundaries and invariants.

## Dependency direction

Core domain modules (`model`, `schema`, `catalog`, `selectors`, `resolution`,
`comparison`, `identity`, `transforms`, `validation`, and `installation`) do not
depend on the CLI or editor. `ProfileWorkbench` composes those services. Typer,
Rich, FastAPI, and Uvicorn are adapters at the edge.

No renderer, command, or API route may independently resolve inheritance,
calculate deltas, manufacture identities, or decide installation destinations.

## Profile catalog

`ProfileCatalog` indexes JSON objects that resemble slicer presets. Bulk scans
ignore malformed/unrelated JSON; explicit path loads surface parse and shape
errors. Names, filename stems, and paths are indexed separately.

Search ranking is exact name, exact stem, prefix, then substring. Corresponding
managed `system` and bundled `resources/profiles` paths are collapsed before
selection. The system copy wins and a warning is emitted once when parsed JSON
differs. All other equal-rank ambiguity is an error. Exact paths remain the
escape hatch.

Selectors filter on recursively resolved `compatible_printers`. Machine matching
is case-insensitive; nozzle matching recognizes a numeric diameter followed by
`nozzle` and does not infer nozzle material.

## Resolution and provenance

`ProfileResolver` recursively resolves `inherits`, starting with the parent and
overlaying explicit child keys. Every effective key has both a source profile
name and exact source path. Nullable per-extruder vectors are resolved
positionally: a child `"nil"` element inherits the corresponding parent element,
and element-level source names and paths preserve mixed provenance. Root `"nil"`
values remain literal slicer defaults because no parent exists. The chain is
root-to-child. Resolved effective JSON has a stable SHA-256 fingerprint for
saved-draft drift detection.

The active path detects cycles. Missing, cyclic, or ambiguous parents invalidate
effective resolution. Override reports are intentionally resilient: explicit
child keys remain visible while parent values are marked unavailable.

Raw JSON, effective settings, and explicit overrides are separate concepts and
must not share a misleading value model.

## Comparison

`comparison.py` collects typed rows before rendering. Metadata, key regex,
semantic group, and difference filters apply in this layer so terminal, CSV,
HTML, and API clients see the same selected data.

JSON equality is type-sensitive: `1`, `1.0`, `true`, and `"1"` are distinct.
Missing values are represented by absent keys internally and rendered as `∅`.

## Composition, draft, and transformation pipeline

`CompositionRecipe` records one starting source, any number of reference
sources, per-setting source/custom/removal choices, source fingerprints, and an
output policy. Identity and compatibility keys are locked out of ordinary
composition and remain dedicated output controls. Materialization retains two
origins: the profile selected by the user and the ancestor that actually defines
its effective value.

Unselected settings come from the starting source. Group actions are expanded
into explicit per-setting selections, so saved recipes have no hidden group
precedence. A recipe compiles into the same `ProfileDraft` used by builders; the
recipe can therefore switch between sparse and root output without changing its
desired effective values. Source fingerprint drift is a warning.

`ProfileDraft` records desired edits, removals, source/base fingerprints, output
mode, compatibility, identity policy, and optional variants. The builder first
derives one desired effective map from the source plus edits. Output modes are
projections of that state.

Sparse projection:

- requires a resolvable base with effective `filament_id`;
- emits type-sensitive behavioral differences only;
- cannot represent deletion of a base-supplied setting;
- reconstructs name/from/version/settings identity explicitly;
- omits material/cloud identity and retains required structural fields;
- receives a round-trip equivalence check against base plus child.

Root projection:

- emits complete effective behavior with no `inherits`;
- requires exact nonempty compatibility entries;
- assigns one material `filament_id` by explicit/reuse/generate policy;
- excludes cloud-owned identity and creates user preset metadata;
- supports intentional setting removal because no parent is involved.

Family projection creates separate roots with variant-specific compatibility and
edits while passing one chosen `filament_id` to every artifact.

Generated filenames must exactly match profile names. Names cannot contain path
separators. Writers use exclusive creation and family writes roll back earlier
files when a later artifact fails.

## Identity rules

`filament_id` is material-family identity. Generated IDs match Bambu Studio's
initial `P` plus seven MD5 hexadecimal characters using `material_name` or
`material_name@user_id`, with time-based collision fallback. Existing roots for
the same inferred material name may be reused.

`filament_settings_id[0]` is the preset name. `setting_id` and sibling `.info`
metadata are cloud-owned and never generated. See `BAMBU_PROFILE_IDENTITY.md`
for pinned source references.

## Validation

Validation produces `ValidationIssue` objects with severity, stable code,
message, optional setting, and optional path. It checks:

- safe name and filename/name agreement;
- user origin, version, and `filament_settings_id`;
- forbidden cloud metadata;
- root `filament_id` and compatibility;
- known printer names when machine profiles exist in the catalog;
- sparse round-trip behavior and saved-draft source/base drift.

Warnings are inspectable but do not block writes. Errors block generation and
installation.

## Installation

Platform adapters own data-root discovery, application config names, active
`preset_folder`, and destination layout. Bambu Studio is the default; OrcaSlicer
is explicit.

`plan_install` resolves and validates every source before writing. Roots route to
`filament/base`; children route to `filament`. Existing destination JSON or
sibling `.info` is an error. `apply_install_plan` creates destinations
exclusively and removes files created by the current transaction on failure.
Pre-existing files are never removed.

## Editor

The FastAPI app exposes catalog, profile, comparison, lineage, composition,
preview, exclusive build, project persistence, install-plan, and confirmed
installation endpoints. NiceGUI is mounted on that application and supplies a
per-browser Profiles/Compare/Lineage/Compose/Build workbench. It calls the same
`ProfileWorkbench` services and does not duplicate grouping, inheritance,
composition, builders, identity, validation, or installation semantics.

Lineage is queried contextually because presets have at most one parent. The
initial page does not build the catalog-wide forest: a selected-profile query
returns its ancestor chain and immediate dependents, and a bounded descendant
query expands the requested branch. The catalog-wide flat graph remains an
explicit problems/maintainer operation and retains unresolved nodes, missing
parents, and cycles.

Catalog UI queries apply managed-copy preference and effective type/filter scope
before ranking, limiting, and pagination. The default scope is `type=filament`;
an advanced all-types scope and exact paths remain escape hatches.

The visual recipe has a monotonic workspace revision. Generated artifacts,
validation, and installation plans are attached to the revision that produced
them. A recipe change invalidates all three projections, and writes or installs
require a valid current preview. The default Uvicorn bind is localhost and
installation still requires a separately reviewed plan and confirmation action.

Full-output compatibility is edited as exact machine-preset selections. The
editor queries a bounded ranked printer-name window and preserves exact custom
names as an escape hatch. Loading composition sources seeds compatibility from
the starting profile. Material-family variants are structured name plus printer
selection rows and compile into the same `TargetVariant` model used by the API.

## Output and errors

Human output goes to stdout. Warnings and errors go to stderr. Domain errors
return nonzero CLI status without tracebacks. CSV, HTML, project, generated
profile, and installed profile writes refuse overwrite.
