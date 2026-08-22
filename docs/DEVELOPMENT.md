# Development and testing

## Environment

Use uv for environment creation, dependency resolution, locking, and command
execution:

```bash
uv sync
```

Do not create a virtual environment with `python -m venv` or install project
dependencies with `pip`. `uv sync` creates and maintains the ignored `.venv`
from `pyproject.toml` and `uv.lock`.

Runtime dependencies are declared in `pyproject.toml`: Pydantic for typed recipe,
draft, and API models; Typer/Rich for the CLI; and FastAPI/Uvicorn/NiceGUI for the
local workbench. The profile-processing core remains independent of those
interface frameworks.

## Test layout

```text
tests/unit/          pure identity, resolution, transform, validation tests
tests/integration/   catalog copies, installation transactions, editor API
tests/cli/           installed command behavior through subprocesses
tests/fixtures/      deterministic Bambu-style profile trees
```

Run the repository-required suite:

```bash
uv run python -B -m unittest discover -s tests -v
```

CLI tests invoke the package with the same uv-managed Python interpreter.

Use temporary profile/config trees. Tests must never write into live Bambu
Studio or OrcaSlicer data. Cover missing parents, cycles, ambiguous names,
system/bundled differences, JSON type equality, identity, exact compatibility,
round trips, filename safety, no-overwrite behavior, and rollback.

## Static and package checks

```bash
uv run ruff check src tests
uv run ruff format --check src tests
uv build
git diff --check
```

Confirm that the NiceGUI workbench module is in the wheel and that `/` renders
without fetching UI assets from a CDN.

## Smoke checks

```bash
uv run filament-tools --help
uv run filament-tools --no-auto-discover \
  --search-dir tests/fixtures/profiles catalog search PETG
uv run filament-tools --no-auto-discover \
  --search-dir tests/fixtures/profiles compare \
  "Generic PETG H2C 0.4" "Bambu PETG HF H2C 0.4" --only-different
```

Write generated profiles/reports to a temporary directory or ignored
`artifacts/`. Do not leave caches or reports in the repository.

## Local macOS application

Run `./scripts/build_macos_app.sh` on an Apple Silicon Mac to create the ignored
`dist/Filament Tools.app` bundle. The script installs the `desktop` optional
dependencies through uv, generates the `.icns` file from the checked-in SVG,
packages a windowed `onedir` application with NiceGUI/PyInstaller, adds local
bundle metadata, and applies an ad-hoc signature. It does not notarize, sandbox,
or prepare the application for redistribution.

After desktop-launcher or packaging changes, open the generated app and verify
catalog discovery plus the Library, Compare, Create profile, Review & install,
and Lineage explorer surfaces. Inspect
`~/Library/Logs/Filament Tools/filament-tools.log` if startup fails.
Confirm that dismissing Quick start persists after quitting and reopening the
app; native webview state lives under
`~/Library/Application Support/Filament Tools/WebView`.

## Change checklist

For domain behavior:

1. Preserve raw/effective/provenance separation.
2. Add a unit regression and relevant integration/CLI test.
3. Update `ARCHITECTURE.md` when an invariant changes.
4. Update the README when user-visible behavior changes.

For CLI/editor changes:

1. Keep semantics in services, not commands/routes/browser JavaScript.
2. Return structured API errors and concise CLI stderr diagnostics.
3. Test preview and mutation separately.
4. Keep all filesystem writes exclusive or explicitly transactional.
5. Exercise Profiles, Compare, Lineage, Compose, both output modes, and install
   planning through the in-app browser Playwright surface when it is available.

Before handoff run the unittest suite, Ruff check/format check, `uv build`,
`git diff --check`, and inspect `git status --short` for generated artifacts.
