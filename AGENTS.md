# Repository instructions

These instructions apply to the entire repository.

## Start here

Before changing code:

1. Check `git status --short` and preserve unrelated work.
2. Read the relevant section of `README.md` for user-visible CLI behavior.
3. Read only the detailed document needed for the task:

   - `docs/ARCHITECTURE.md` for profile lookup, inheritance, diff modes, and output invariants.
   - `docs/DEVELOPMENT.md` for tests, fixtures, smoke checks, and change checklists.
   - `docs/PRODUCT_ARCHITECTURE.md` for product boundaries, editor design, and the feature roadmap.
   - `.codex/memories/filament-profile-comparisons.md` for the analyzed comparison workflow and dated local-profile findings; verify the installed profiles before reusing snapshot values.

## Repository map

- `src/filament_tools/`: domain services plus CLI and editor adapters.
- `pyproject.toml`: dependencies, console entry point, packaging, and Ruff policy.
- `tests/{unit,integration,cli}/`: layered `unittest` coverage.
- `tests/fixtures/profiles/`: small, deterministic Bambu-style profile trees.
- `README.md`: authoritative user-facing CLI documentation.
- `docs/`: deeper maintainer references and historical context.

## Required verification

Run the focused suite after any behavior change:

```bash
uv run python -B -m unittest discover -s tests -v
```

Before handing off a code or documentation change, also run:

```bash
git diff --check
```

Run Ruff through uv:

```bash
uv run ruff check src tests
uv run ruff format --check src tests
```

Do not leave `__pycache__`, generated HTML/CSV reports, or other smoke-test artifacts in the repository.

## Behavioral invariants

- Bambu/Orca profiles are sparse. Keep raw JSON values distinct from recursively resolved effective values.
- Preserve the source profile for every effective value.
- Never silently select among ambiguous profile matches; an exact JSON path must remain a reliable escape hatch.
- Match machine/nozzle selectors against effective `compatible_printers`, not filename conventions.
- Keep `effective`, `raw`, and `overrides` semantics distinct. Override mode must still show explicit child keys when the parent is missing or cyclic.
- Apply key, metadata, and group filters consistently to terminal, CSV, and HTML output.
- Keep diagnostics on stderr and document intentional exit-code changes.

## Change discipline

- Use `uv sync`, `uv run`, and `uv build`; do not create hand-built virtual
  environments or install project dependencies with `pip`.
- Prefer maintained Python libraries at interface boundaries. Keep core profile semantics framework-independent.
- Put new behavior in its owning module; do not duplicate profile semantics in CLI commands, API routes, or browser JavaScript.
- Add synthetic regression coverage for behavior changes. Use temporary profile trees for malformed, missing-parent, cyclic, and ambiguity cases.
- When a CLI flag or output meaning changes, update `README.md` in the same change.
- Put detailed design rationale, platform notes, or multi-step maintenance procedures in `docs/`; keep this file limited to rules needed on most turns.

## Git push authorization

- A user instruction of "push" explicitly authorizes an ordinary, non-force
  push of `HEAD` to the current branch's existing configured upstream.
- Before pushing, verify the current branch, upstream, and remote URL.
- "Push" does not authorize force pushes, tag pushes, another branch or remote,
  changing remote configuration, deleting refs, or creating an upstream.
- If the current branch has no unambiguous upstream, ask for clarification.
