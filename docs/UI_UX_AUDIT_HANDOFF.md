# UI/UX audit handoff

**Audit date:** 2026-08-21
**Status:** P0 and guided-output/help batches implemented; later roadmap remains
**Scope:** Local NiceGUI profile workbench, including catalog discovery,
inspection, comparison, lineage, composition, sparse/root generation, project
persistence, validation, export, and installation

## Purpose

This document hands off a senior UI design engineering and UX review of the
Filament Tools visual workbench. It records the product context, observed
behavior, high-priority defects, recommended information architecture, complete
improvement backlog, and acceptance criteria. It should be read with
`PRODUCT_ARCHITECTURE.md` for product boundaries and `ARCHITECTURE.md` for
profile-processing invariants.

The original audit changed no application code. Its P0 handoff was implemented
on 2026-08-21 with server-side filtered catalog windows, scoped lineage queries,
a full-width direct-donor composer, revision-bound preview/install state,
unsaved-work protection, progressive output controls, and updated regression and
browser verification. A following guided-output/help batch added exact
printer-preset search and source seeding, structured material-family variants,
contextual terminology help, and a persistent first-run walkthrough. The later
editing-intelligence, profile-maintenance, cross-slicer, and richer
installed-profile operations in this document remain roadmap items.

## Product context

Filament Tools is no longer a single comparison script. Its shared domain layer
now supports:

- Bambu Studio and OrcaSlicer profile discovery and deterministic selection;
- sparse inheritance resolution with effective-value provenance;
- raw, effective, and override comparison semantics;
- comparison of two or more profiles;
- multi-source composition by setting or semantic group;
- sparse inherited and full AMS-compatible output from the same recipe;
- Bambu-compatible material identities and machine/nozzle families;
- validation, exclusive writes, project persistence, and transactional install;
- a subcommand CLI and a local FastAPI/NiceGUI workbench using the same services.

The current workbench presents five equal-weight tabs:

1. Profiles
2. Compare
3. Lineage
4. Compose
5. Build & install

The domain architecture is sound. The main weaknesses are catalog scale,
lineage rendering, information architecture, layout, reactive-state integrity,
progressive disclosure, and insufficient help for Bambu-specific concepts.

## Audit method and evidence

The review combined source inspection with live Playwright testing through the
in-app browser.

The deterministic workflow was launched with:

```bash
UV_CACHE_DIR=/private/tmp/filament-tools-uv-cache \
  uv run filament-tools \
  --no-auto-discover \
  --search-dir tests/fixtures/profiles \
  editor --host 127.0.0.1 --port 8765
```

The deterministic fixture catalog contains five filament profiles plus two
machine presets and was used to exercise:

- raw and effective inspection;
- a two-profile Generic PETG/Bambu PETG HF comparison;
- inheritance-tree selection;
- comparison-to-composition transfer;
- individual donor selection;
- sparse and full output preview;
- validation and the install confirmation dialog.

A second workbench was launched with normal auto-discovery against the installed
Bambu Studio and OrcaSlicer profiles. The installed catalog contained:

- 18,828 indexed JSON profiles before managed-copy preference;
- 13,944 visible profiles after preference;
- 7,953 filament profiles;
- 3,740 process profiles;
- 1,267 machine profiles;
- 529 profiles without a type;
- 443 machine-model profiles;
- 13,944 lineage nodes and 12,144 lineage edges.

The UI reported only 399 indexed profiles. None of those 399 was a filament
profile, and searching for `PETG` produced no result. Navigating the real catalog
also exceeded the browser navigation timeout, and opening the eagerly expanded
lineage view became unresponsive.

## Executive assessment

The workbench demonstrates the intended functionality, but it should still be
treated as a prototype. Do not prioritize cosmetic refinement until the
following P0 issues are resolved:

1. catalog queries omit the profiles the product is intended to edit;
2. the full lineage tree does not scale to real installations;
3. the composer hides donor columns at a normal desktop width;
4. generated output, inspectors, and status labels can become stale;
5. actions can discard work or operate on state that has not been reviewed.

## P0 recommendations

### 1. Correct catalog search and scope

`ProfileWorkbench.catalog_entries()` currently calls
`search_visible(query, 500)`. Catalog search limits the sorted raw results before
managed system/bundled copies are collapsed. The workbench then captures that
result once as a static set of options. With a real combined catalog, the first
alphabetical results are process and machine presets rather than filaments.

Required changes:

- default the visual library to effective `type=filament`;
- query the complete catalog server-side instead of searching a static client
  list;
- apply managed-copy preference and type filters before the result limit;
- debounce input and return a small ranked result window, such as 50 items;
- virtualize long result lists;
- add application, source, vendor/material, machine, nozzle, and user/system
  filters;
- show total result count and active-filter chips;
- retain an Advanced option for non-filament preset types and exact paths;
- add recent and favorite profiles.

Relevant code:

- `src/filament_tools/service.py`, `catalog_entries`
- `src/filament_tools/catalog.py`, `search`, `visible_profiles`, and
  `search_visible`
- `src/filament_tools/editor/workbench_ui.py`, `WorkbenchSession`

Acceptance criteria:

- searching `PETG` finds installed PETG filaments even when they sort beyond the
  first 500 catalog records;
- the default workbench list contains filament profiles, not process or machine
  profiles;
- system/bundled preference and difference warnings remain intact;
- an exact JSON path remains a reliable escape hatch;
- startup does not serialize thousands of unused options to the browser.

### 2. Replace the eagerly expanded lineage forest

The complete lineage graph is created while the workbench page is rendered, even
when Lineage is not active. Every node is then passed to `ui.tree`, and the tree
is expanded immediately.

Required changes:

- initially show the selected profile, its ancestors, and immediate children;
- fetch descendants when a node is expanded;
- provide lineage search and a deliberate Show all descendants action;
- virtualize large child collections;
- separate Ancestors, Children/dependents, and Problems views;
- preserve broken parents and cycles without expanding the entire catalog;
- defer graph work until the lineage surface is opened.

Acceptance criteria:

- initial workbench load does not construct or transmit the full lineage forest;
- selecting a profile displays its complete ancestor chain and immediate
  dependents promptly;
- expanding a node loads only the requested branch;
- broken and cyclic profiles remain discoverable;
- the installed 13,944-node catalog remains interactive.

### 3. Make the composition table the primary workspace

At a 1440-pixel-wide desktop viewport, the fixed-width Group action and Setting
choice panels compress the grid until its donor-profile columns are not visible.
The user can see Setting, Group, and Composed result, but not the source values
they are expected to choose between.

Required changes:

- give the comparison/composition table the full available width;
- move group actions and the setting inspector into collapsible drawers or a
  context panel;
- keep Setting and Result sticky only when sufficient room remains;
- expose an obvious horizontal scrollbar for multiple donor columns;
- make donor cells directly selectable instead of requiring a separate source
  dropdown and Apply button;
- add setting-name and group search above the table;
- highlight explicitly selected rows and groups.

Acceptance criteria:

- two donor columns, setting name, and result are visible at 1280 and 1440
  pixels without obscuring the source values;
- keyboard and pointer users can choose a donor directly from the row;
- the selected donor and the ancestor that defined its effective value are both
  understandable;
- three or more sources remain usable through intentional horizontal scrolling.

### 4. Establish authoritative reactive state and preview invalidation

Observed stale-state failures:

- after applying a donor, the grid changed but `Current result` remained stale;
- changing sparse output to full output left sparse JSON and validation visible;
- the header retained `Comparing 2 profiles` while Lineage was active;
- Write and Install remained enabled after recipe inputs changed;
- the install plan could become disconnected from the recipe that produced it.

Required changes:

- derive each visible result from one recipe/workspace state;
- assign a monotonically changing recipe revision or deterministic fingerprint;
- attach preview and install-plan results to the revision that produced them;
- invalidate generated JSON, validation, and install plans after every relevant
  input change;
- display `Changes not previewed` until the current revision is validated;
- disable Write and Install until the current revision has a valid preview;
- update the selected-row inspector immediately after composition changes;
- make the header describe durable workspace state, not the last executed action.

Acceptance criteria:

- stale JSON is never presented as the current output;
- a changed recipe cannot write or install using an earlier validation result;
- the active setting inspector and table always agree;
- sparse/full switching preserves choices but immediately invalidates the old
  projection.

### 5. Protect unsaved work

`Load sources` currently clears selections, fingerprints, and undo/redo history
without warning.

Required changes:

- confirm before replacing sources when explicit choices exist;
- show Saved, Unsaved changes, Preview stale, and Validation failed states;
- disable Undo and Redo when their stacks are empty;
- label undo history with the action that will be reversed;
- keep a browser-local recovery copy of the active recipe;
- warn before reload/navigation when unsaved work exists;
- explain source-fingerprint drift when loading saved projects.

## Recommended information architecture

Five peer tabs overstate Lineage as a primary task and separate Compose from the
Build step that completes it. A clearer product structure is:

### Library

Find, filter, inspect, refresh, favorite, and select profiles. The selected
profile has a structured overview and contextual lineage drawer.

### Compare

Compare two or more profiles. Select a baseline, filter settings, understand
differences, and mark candidate donor settings. An explicit `Create from this
comparison` action begins composition.

### Create profile

Use a persistent four-step flow:

1. **Sources** — starting profile, reference profiles, and optional sparse parent.
2. **Choose settings** — donor selection, custom values, removals, and group
   operations.
3. **Output** — sparse/full mode, material identity, exact compatibility, and
   optional family variants.
4. **Review** — effective change summary, validation, generated artifacts,
   export, project save, and install.

Settings choices must remain visible and preserved while moving between steps.

### Installed profiles

Inspect destinations and support install, update, backup, and uninstall. Keep
filesystem/account overrides in an Advanced section.

### Lineage placement

Lineage should normally be contextual to the currently selected profile. A
dedicated full graph can remain available for maintainers, but must be searched
and expanded on demand.

The global floating `Use comparison in composer` button should be removed. It is
visible on unrelated tabs, can obscure content, and can operate on stale
comparison state. Place the action in the Compare results toolbar.

## Screen-level recommendations

### Library and profile inspection

- Replace JSON-first inspection with a summary of material, vendor, application,
  source kind, machine/nozzle compatibility, parent, inheritance depth, explicit
  override count, and validation state.
- Present settings in a table with effective value and provenance.
- Offer Raw JSON under an Advanced disclosure.
- Add the missing Overrides view so the UI matches CLI semantics.
- Show breadcrumbs or a compact lineage chain with clickable ancestors.
- Explain managed system/bundled copy preference and surface the difference
  warning in the UI.
- Distinguish `Other/other` labels with useful source names or omit them when no
  useful classification is available.

The current Profiles hint promises that effective values retain their defining
source, but the JSON view does not display source information per setting.

### Compare

- Recompute automatically when view, group, or difference filters change.
- Add key/name search, Include metadata, and Overrides mode.
- Let the user designate a baseline profile.
- Highlight changed cells and unchanged inherited values differently.
- Show friendly setting names, units, and raw keys together.
- Show numeric deltas where meaningful while preserving exact JSON values.
- Permit custom column labels for profiles with identical names.
- Make columns flex to use available grid width.
- Keep provenance concise in cells and expose full source paths on demand.
- Move export controls into a secondary action menu.
- Provide a summary such as `3 differences across Temperature, Flow, and
  Dimensional compensation`, with clickable group filters.

### Compose

- Make donor cells clickable and show the pending result before committing.
- Display `starting value -> resulting value` for changed rows.
- Keep selected-via and defined-by provenance distinct.
- Preview the number and values affected by a group action before applying it.
- Use schema-aware editors for numeric, boolean, enum, temperature, and vector
  values.
- Keep raw Custom JSON as an expert fallback.
- Explain why a removal cannot be represented by sparse output when applicable.
- Support reusable transforms such as temperature or flow offsets.
- Keep undo/redo, choice count, and dirty state near the composition table.

### Output and build

Use progressive disclosure:

- Sparse output shows its parent and a short explanation of the behavioral
  delta. Hide material identity, compatibility, and root-family controls.
- Full output hides the inheritance parent and explains why AMS identity and
  exact compatibility are required.
- Show Explicit `filament_id` only when explicit identity is selected.
- Populate compatibility from the source and render exact printer presets as
  searchable chips.
- Replace `NAME::PRINTER|PRINTER` text syntax with a structured family-variant
  editor.
- Show a human-readable change summary before raw generated JSON.
- Label inherited defaults and intentional overrides.
- Suggest a safe filename and provide file/directory pickers where the framework
  permits them.
- Treat generated JSON as an Advanced inspection surface, not the main result.

### Validation, export, and installation

- Render validation messages beside the responsible fields.
- Keep a persistent warning/error summary with Go to field actions.
- Do not rely on transient notifications for actionable errors.
- Require a current reviewed installation plan before enabling Install.
- Summarize application, account/user folder, profile type, destination, and
  no-overwrite behavior in the confirmation dialog.
- Do not say destinations were reviewed if the user skipped the plan preview.
- Explain whether Bambu Studio or OrcaSlicer must be restarted.
- Detect existing destinations and offer explicit update/backup/cancel choices.
- Separate project save, JSON export, and slicer installation as distinct user
  intents.

## Help and terminology

The current interface assumes knowledge of slicer internals. Add concise inline
help for:

- raw, effective, and override values;
- starting profile versus reference/donor profile;
- provenance, selected via, and defined by;
- sparse inherited versus full AMS-compatible output;
- material identity and `filament_id`;
- exact compatible-printer preset names;
- material/root families;
- user folder and application data directory;
- values that cannot be removed from a sparse child.

Use an information icon with a one- or two-sentence tooltip. Link to a longer
help panel for examples and edge cases. Do not fill primary screens with long
instruction paragraphs.

Add a first-run walkthrough using a small example:

1. choose a starting filament;
2. add a faster donor filament;
3. compare only differences;
4. choose one temperature or flow setting;
5. preview sparse and full output;
6. review an installation plan without writing it.

## Accessibility and responsive design

- Give icon-only copy buttons accessible names such as `Copy generated JSON`.
- Announce status and validation changes through appropriate live regions.
- Associate errors and help with fields through accessible descriptions.
- Preserve full keyboard operation and visible focus in grids and dialogs.
- Do not rely only on color for selection, inheritance, warnings, or errors.
- Audit all theme colors against WCAG contrast requirements.
- Use the green product palette consistently for primary actions instead of the
  visually conflicting default blue.
- Use meaningful page/section headings and landmarks.
- Test zoomed text and keyboard-only navigation.
- Replace fixed `w-80`, `w-96`, `w-[430px]`, and large minimum widths with
  responsive breakpoints.
- Test 1280, 1440, and 1920 pixel desktop layouts plus a narrow resizable window.
- Reduce large blank grid areas and avoid fixed viewport-height panels when only
  a few rows exist.

The visual design is otherwise clean and restrained: spacing, card grouping,
typography, and the dark-green header provide a useful base. Refinement should
preserve that simplicity while improving information density and action
hierarchy.

## Additional functionality backlog

### Profile discovery and organization

- catalog refresh and source-location management;
- favorites, recents, tags, and named collections;
- clearer application/source badges;
- exact machine/nozzle compatibility filtering;
- diagnostics for profiles hidden by ambiguity or failed resolution.

### Profile maintenance

- safe backup, update, and uninstall;
- source-drift explanation;
- rebase a sparse profile onto a newer or different parent;
- dependent-child impact preview before editing a base;
- import/export of complete material-family bundles.

### Editing intelligence

- setting descriptions, units, ranges, enum choices, and warnings;
- first-class per-extruder vector editing with inherited-position display;
- reusable temperature, flow, and cooling transformations;
- calibration-result import;
- named templates and organization baseline policies.

### Cross-slicer and operations

- Bambu/Orca equivalence and unsupported-setting reports;
- cross-slicer conversion with explicit loss reporting;
- slicer-running or restart guidance;
- batch builds from project files;
- structured material-family management.

## Recommended delivery sequence

### Phase 1: Make the real catalog usable

- server-side filament search and filters;
- correct preference/filter/limit ordering;
- lazy lineage queries and rendering;
- startup and interaction performance budgets.

### Phase 2: Make state trustworthy

- central workspace/recipe state;
- preview and install-plan revision tracking;
- invalidation and disabled actions;
- dirty-state protection and recovery.

### Phase 3: Redesign comparison and composition

- full-width table;
- direct donor selection;
- responsive inspector drawers;
- setting search, friendly names, units, deltas, and provenance;
- structured group actions and custom editors.

### Phase 4: Guided output and help

- progressive sparse/full controls;
- structured compatibility and family editors;
- human-readable review summary;
- contextual help and first-run walkthrough.

### Phase 5: Accessibility and profile operations

- accessibility remediation and automated checks;
- visual regression coverage;
- backup/update/uninstall;
- drift and rebase workflows.

## Test strategy for the redesign

Add browser-level tests for:

- a generated catalog with thousands of mixed profile types;
- a filament whose name sorts beyond the first 500 raw profiles;
- server-side query, application, source, machine, and nozzle filters;
- managed-copy preference after filtering;
- lineage expansion without a full-tree render;
- two-, three-, and five-source comparisons;
- donor selection and immediate inspector/result synchronization;
- sparse/full mode switching and preview invalidation;
- invalid writes and installs after recipe edits;
- source replacement with unsaved choices;
- keyboard-only operation;
- automated accessibility checks;
- visual regression at 1280, 1440, and 1920 pixels.

Keep the existing unit and API tests for profile semantics. Browser tests should
validate interface state and task completion, not reimplement domain assertions.

## Implementation hotspots

- `src/filament_tools/catalog.py`: ranking, managed-copy preference, type-aware
  and server-side search.
- `src/filament_tools/service.py`: catalog query DTOs, scoped lineage queries,
  setting metadata, and workbench-oriented summaries.
- `src/filament_tools/editor/workbench_ui.py`: layout, reactive workspace state,
  progressive disclosure, help, accessibility, and task flow.
- `src/filament_tools/editor/app.py`: paginated search and lineage endpoints if
  the NiceGUI adapter does not call services directly.
- `src/filament_tools/schema.py`: setting names, descriptions, units, ranges,
  enums, and editor types.
- `tests/integration/test_editor.py`: API and state-contract coverage.
- future browser tests: task flow, scale, accessibility, and visual layout.

Core profile semantics must remain in the domain services. The UI may derive
presentation state, but it must not independently resolve inheritance,
manufacture IDs, calculate sparse deltas, validate profiles, or choose install
destinations.

## Handoff cautions

- The worktree already contains the broader package/workbench refactor and is
  intentionally dirty. Inspect `git status --short` and stage explicit paths.
- Use `uv` for dependency management, commands, tests, and builds.
- In restricted execution environments, set
  `UV_CACHE_DIR=/private/tmp/filament-tools-uv-cache`.
- Binding the local NiceGUI server or initializing its process pool may require
  permission outside a restricted sandbox.
- Never click the final install confirmation during a read-only browser audit.
- Preserve sparse/effective/raw/provenance invariants from `ARCHITECTURE.md`.
- Do not solve catalog or lineage scale by silently omitting ambiguous, broken,
  cyclic, or exact-path-selectable profiles.
