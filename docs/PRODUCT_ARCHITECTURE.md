# Filament Tools product architecture

This document records the restructuring analysis, the target product shape, the
implemented scope, and the complete feature backlog. It is the design reference
for the application; `ARCHITECTURE.md` documents lower-level runtime invariants.

## Why the program needs a product architecture

The original single script combined six distinct responsibilities: profile
discovery, inheritance, comparison, transformation, installation, and report
presentation. Each is useful independently and has different failure modes.
Keeping them behind one argument parser made changes risky, encouraged raw JSON
dictionaries to cross every boundary, and made an interactive editor difficult
to add without duplicating core logic.

Filament Tools is now organized as a library with two adapters: a subcommand CLI
and a local web workbench. Both use the same typed recipe/draft, resolution,
build, validation, and installation services.

## Product model

`CompositionRecipe` is the central visual editing artifact. It records:

- one starting source and any number of reference sources;
- explicit per-setting choices from a source, a custom JSON value, or removal;
- source fingerprints and a distinct selected-via/effective-source provenance;
- a sparse inheritance parent plus the output and identity policy.

The recipe materializes into `ProfileDraft`, the lower-level build artifact. It records:

- source and optional base profile selectors plus source fingerprints;
- desired setting edits and intentional removals;
- sparse-child or inheritance-free root output mode;
- one shared compatibility list or a family of target variants;
- material identity policy and optional explicit `filament_id`;
- validation state derived by services, rather than stored in output JSON.

The source profile is evidence, the draft is intent, and generated JSON is an
output projection. Sparse and root profiles therefore cannot drift into separate
editing models. A sparse projection contains only behavior that differs from its
base. A root projection contains the complete desired effective behavior and no
inheritance. Variants may add their own edits but share one material identity.

Metadata is not treated like ordinary inherited settings. `filament_id` is a
material-family identity, `filament_settings_id` follows the preset name, and
`setting_id` belongs to slicer cloud synchronization. See
`BAMBU_PROFILE_IDENTITY.md` for source evidence.

## Package boundaries

```text
src/filament_tools/
  model.py             typed runtime objects and editable drafts
  schema.py            key policy and semantic groups
  catalog.py           discovery, indexing, copy preference, search
  selectors.py         selector parsing and compatibility matching
  resolution.py        inheritance and per-key provenance
  comparison.py        comparison and override report models
  transforms.py        sparse, root, and material-family builders
  identity.py          Bambu-compatible material identity policy
  validation.py        structured diagnostics and round-trip checks
  installation.py      previewable, transactional install plans
  platforms/           Bambu Studio and OrcaSlicer filesystem adapters
  reporting/           terminal, CSV, and self-contained HTML renderers
  cli/                  discoverable subcommands
  editor/               local API, recipe persistence, and visual workbench
```

Core modules do not know about Typer, Rich, FastAPI, or browser state. Interface
code converts typed service results to terminal output or JSON.

## Command structure

The clean-break CLI groups commands by user intent:

```text
uv run filament-tools catalog paths
uv run filament-tools catalog search PETG
uv run filament-tools inspect PROFILE --view effective|raw|overrides
uv run filament-tools compare PROFILE PROFILE [PROFILE...]
uv run filament-tools build sparse --base BASE --source MODIFIED --name NAME --output FILE
uv run filament-tools build root --source PROFILE --name NAME --output FILE
uv run filament-tools build family --source PROFILE --variant SPEC [--variant SPEC...]
uv run filament-tools validate PROFILE
uv run filament-tools install PROFILE [PROFILE...] [--dry-run]
uv run filament-tools editor
```

Every mutating operation has a previewable model. Generated output uses
exclusive creation. Installation validates all operations before it writes and
rolls back files from the current operation if a later write fails.

## Workbench structure

The editor is a local FastAPI/NiceGUI application with five connected surfaces:

1. **Library**: server-side filament discovery/filtering plus structured
   effective, override, provenance, summary, and raw inspection.
2. **Compare**: a two-or-more-profile effective/raw/override grid with a chosen
   baseline, setting and semantic filters, provenance, deltas, and a difference
   summary.
3. **Create profile**: starting/reference selection and a full-width direct-donor
   grid, with contextual custom/removal and group controls plus undo/redo.
4. **Review & install**: progressive sparse or full AMS output, family variants,
   revision-bound validation, exclusive writes, project persistence, recovery,
   and a separately confirmable installation plan.
5. **Lineage explorer**: scoped ancestors/immediate dependents, bounded
   descendants, and an explicit catalog-wide problems view.

The header exposes a browser-persistent first-run walkthrough and terminology
reference. Full-output controls use searchable exact printer-preset selections
and structured family-variant rows; the browser does not parse a separate
variant mini-language.

The browser is an adapter, not the owner of profile semantics. API endpoints
load recipes and drafts, compare profiles, expose lineage, preview
sparse/root/family outputs, validate them, save/load projects, and preview or
apply install plans.

## Required feature set

The product is expected to provide all of the following:

- cross-platform Bambu Studio and OrcaSlicer profile discovery;
- managed system-copy preference with a warning when bundled JSON differs;
- exact-path escape hatch and explicit ambiguity errors;
- recursive inheritance with cycle/missing-parent diagnostics;
- effective-value provenance per setting;
- positional `"nil"` inheritance and element provenance for nullable vectors;
- effective, raw, and explicit-override comparison modes;
- consistent regex, metadata, group, and difference filtering;
- terminal, CSV, and self-contained HTML reports;
- sparse profile creation from a base and modified desired state;
- inheritance-free full/root flattening;
- Bambu-compatible user material ID generation, explicit identity, and reuse;
- shared-identity machine/nozzle variant families;
- exact compatibility targeting and catalog validation where possible;
- structured validation codes and error/warning severity;
- generation preview and no-overwrite writes;
- round-trip equivalence checking for generated sparse profiles;
- installation preview, root/child routing, validation, and transaction rollback;
- Bambu Studio default installation and optional OrcaSlicer installation;
- local multi-view filament workbench backed by the same services;
- multi-source settings and semantic-group composition with undo/redo;
- one-click recipe switching between sparse inherited and full AMS output;
- catalog-wide ancestor/descendant forest with broken-link visibility;
- saved, portable draft project files with source fingerprints.

## Optional and future features

These are deliberately recorded even when they are not part of the first
refactored release.

### Profile maintenance

- Detect source drift from saved fingerprints and explain changed ancestors.
- Rebase a sparse profile onto a newer or different base.
- Show the inheritance graph, cycles, orphans, and dependent children.
- Update, uninstall, and back up installed profiles safely.
- Package and import a complete material family as one bundle.
- Batch builds from declarative project files.
- Compare equivalent Bambu Studio and OrcaSlicer interpretations.

### Editing and domain knowledge

- Schema-derived descriptions, units, ranges, enum choices, and warnings.
- First-class nullable/per-extruder vector editing with inherited-position UI.
- Reusable transformations such as temperature or flow offsets.
- Named templates and organization-wide baseline policies.
- Calibration-result import and mapping into profile settings.
- Cross-slicer conversion with an explicit loss/unsupported-settings report.
- Side-by-side dependent-child impact before changing a base.

### Operations and quality

- Live slicer restart/reload detection when a platform exposes it safely.
- Signed release artifacts and platform launchers.
- A lockfile and automated dependency updates.
- Property-based tests for inheritance and sparse/root round trips.
- Golden fixtures harvested from multiple slicer versions.
- JSON Schema export for project and API payloads.
- Pluggable schema/version adapters as Bambu and Orca formats diverge.

## Delivery phases

The first refactored release establishes the package, typed draft, resolver,
comparison services, sparse/root/family builders, validation, transactional
installation, subcommand CLI, local workbench, project persistence, and layered
tests. Optional features remain tracked above and should be implemented through
the same service boundaries rather than added directly to an interface.
