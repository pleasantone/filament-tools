# Repository instructions

These instructions apply to the entire repository.

## Start here

Before changing code:

1. Check `git status --short` and preserve unrelated work.
2. Read the relevant section of `README.md` for user-visible CLI behavior.
3. Read only the detailed document needed for the task:

   - `docs/ARCHITECTURE.md` for profile lookup, inheritance, diff modes, and output invariants.
   - `docs/DEVELOPMENT.md` for tests, fixtures, smoke checks, and change checklists.

## Repository map

- `profile_diff.py`: the supported CLI and implementation. There is no separate package or alternate versioned entry point.
- `tests/test_profile_diff.py`: end-to-end CLI tests using `unittest` and subprocesses.
- `tests/fixtures/profiles/`: small, deterministic Bambu-style profile trees.
- `README.md`: authoritative user-facing CLI documentation.
- `docs/`: deeper maintainer references and historical context.

## Required verification

Run the focused suite after any behavior change:

```bash
python3 -B -m unittest discover -s tests -v
```

Before handing off a code or documentation change, also run:

```bash
git diff --check
```

If Ruff is installed, run:

```bash
ruff check profile_diff.py tests/test_profile_diff.py
```

Do not leave `__pycache__`, generated HTML/CSV reports, or other smoke-test artifacts in the repository.

## Behavioral invariants

- Bambu/Orca profiles are sparse. Keep raw JSON values distinct from recursively resolved effective values.
- Preserve the source profile for every effective value.
- Never silently select among ambiguous profile matches; an exact JSON path must remain a reliable escape hatch.
- Match machine/nozzle selectors against effective `compatible_printers`, not filename conventions.
- Keep `effective`, `raw`, and `overrides` semantics distinct. Override mode must still show explicit child keys when the parent is missing or cyclic.
- Apply key, metadata, and group filters consistently to terminal, CSV, and HTML output.
- Preserve current exit-code behavior and keep diagnostics on stderr.

## Change discipline

- Keep the implementation standard-library-only unless the user explicitly approves a dependency or packaging change.
- Prefer focused edits to the current single-file design. Read `docs/ARCHITECTURE.md` before splitting modules or changing inheritance resolution.
- Add synthetic regression coverage for behavior changes. Use temporary profile trees for malformed, missing-parent, cyclic, and ambiguity cases.
- When a CLI flag or output meaning changes, update `README.md` in the same change.
- Put detailed design rationale, platform notes, or multi-step maintenance procedures in `docs/`; keep this file limited to rules needed on most turns.
