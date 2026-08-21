# Architecture and behavior

This document describes the current implementation of `profile_diff.py`. The README remains authoritative for user-facing CLI examples.

## Runtime pipeline

The CLI follows this sequence:

1. Parse repeated `--select` specifications into `ProfileSelector` objects.
2. Build search roots from explicit directories, selected file paths, optional platform discovery, and likely profile directories below the current working directory.
3. Build a `ProfileIndex` over JSON objects that look like presets.
4. Resolve every selector to one distinct `Profile`, including optional machine/nozzle compatibility filtering.
5. Resolve inheritance where the requested mode needs effective values.
6. Apply metadata, regex, group, and difference filters.
7. Render terminal output and optional CSV or HTML files.

`main()` owns argument validation and orchestration. Keep lower-level functions independent of `argparse` so their behavior remains testable.

## Data model

`Profile` contains the source `Path` and decoded JSON object. Its `name` falls back to the filename stem, and its `inherits` property normalizes an empty parent to `None`.

`EffectiveProfile` contains:

- the selected `Profile`
- merged effective `values`
- a `sources` map naming the profile that explicitly supplied each value
- the root-to-child inheritance `chain`

`OverrideReport` is deliberately different from a multi-way diff row. It represents one selected profile, the effective state of its immediate parent, parent-resolution status, and only that child's explicit keys.

## Profile indexing and selection

`ProfileIndex` recursively indexes JSON files below each unique search root. Malformed JSON and objects that do not resemble presets are ignored during bulk indexing. Loading an explicitly selected file is strict and surfaces JSON or shape errors.

Profiles are indexed by case-folded JSON `name`, filename stem, and resolved path. Search ranking prefers:

1. exact profile name
2. exact filename stem
3. prefix matches
4. substring matches

Before compatibility filtering, corresponding profiles in an application's `system` and bundled `resources/profiles` trees are recognized by their relative paths. The system copy is authoritative. If its parsed JSON differs from the bundled copy, selection emits one stderr warning containing both paths. Performing this step before compatibility filtering ensures a stale bundled copy cannot win merely because its compatibility metadata differs.

When other equally ranked candidates remain, selection fails with their paths and source classifications. Unrelated same-name variants and matches across applications are never collapsed. An exact JSON path bypasses copy preference and remains a reliable escape hatch.

Each selector has this grammar:

```text
PROFILE[;machine=MACHINE][;nozzle=DIAMETER][;label=DISPLAY NAME]
```

Machine and nozzle filtering use the effective `compatible_printers` value. This is important because filenames do not reliably encode nozzle compatibility. Nozzle matching currently recognizes a numeric diameter followed by `nozzle`; it does not infer nozzle material.

## Inheritance resolution

`resolve_effective()` recursively resolves `inherits`, copies the parent's effective values and source map, then overlays the child's explicit keys. The child becomes the source for every key it supplies. Completed resolutions are cached by absolute path.

The active path stack detects cycles before caching a result. Normal effective comparison fails when the selected profile cannot be fully resolved; this prevents incomplete effective values from being presented as valid.

Parent lookup prefers an exact profile in the child's directory when duplicate names exist there. Otherwise it applies the managed system-copy preference and then follows normal ambiguity rules.

## Diff modes

| Mode | Minimum selections | Keys shown | Values compared | Source behavior |
|---|---:|---|---|---|
| `effective` | 2 | Union of effective keys | Each selected profile's resolved value | Optional with `--show-source` |
| `raw` | 2 | Union of keys stored in selected JSON files | Unresolved explicit values | Optional; source is the selected profile |
| `overrides` | 1 | Explicit keys, reported separately for every selected profile | Child value versus immediate parent's effective value | Always includes parent source |

In override mode, difference labels mean:

- `changed`: the parent has the key with a different JSON type or value.
- `same`: the explicit child value exactly repeats the parent's effective type and value.
- `added`: the parent resolves successfully but has no effective value for the key.
- `no parent`: the selected profile does not declare `inherits`.
- `unavailable`: a missing, ambiguous, malformed, or cyclic parent prevents a trustworthy comparison.

Override mode is intentionally resilient: parent failures are visible in the report and as stderr warnings, while explicit child keys remain available. Effective mode remains strict because it claims to show complete resolved state.

## Filtering

`META_KEYS_DEFAULT` is removed unless `--include-meta` is present. `--keys` is a regular expression over parameter names. Repeated `--group` values restrict keys using `group_for_key()`.

For effective/raw multi-way comparisons, `--only-different` removes a row when every rendered value is identical. For override reports, it removes only `same` rows; added, changed, root, and unavailable rows remain visible.

When adding or changing a semantic group, update `GROUP_LABELS`, `group_for_key()`, README documentation, and group-filter tests together.

## Output contracts

Terminal, CSV, and HTML renderers consume the same collected rows or override reports. New filters and difference states must therefore be represented in the collection layer before rendering.

The effective/raw HTML view is a grouped multi-profile comparison. The override HTML view is organized by selected profile because each profile has a different parent and a different explicit-key set. Override CSV repeats profile and parent status on each row; a profile with no matching keys still receives an empty status row so it is not lost.

Keep output files self-contained. HTML must not depend on remote scripts, fonts, stylesheets, or network access.

## Safe extension points

- Add profile discovery candidates in `discover_profile_roots()` and cover platform-independent behavior separately from OS path constants.
- Add selector fields in `ProfileSelector`, `parse_selector()`, candidate filtering, help text, README syntax, and rejection tests as one change.
- Add report formats after the collection layer; avoid reimplementing inheritance or filtering inside renderers.
- If the script is split into modules, preserve `profile_diff.py` as the documented entry point unless a migration is explicitly requested.
