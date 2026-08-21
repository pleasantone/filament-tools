# Development and testing

The project is a standard-library-only Python CLI. It has no build step, lockfile, or required third-party test runner.

## Local requirements

- Python 3.9 or newer
- Optional: Ruff for static checks

Use `python3` in repository documentation and verification commands. The `-B` flag prevents bytecode cache artifacts during routine checks.

## Test suite

Run all tests from the repository root:

```bash
python3 -B -m unittest discover -s tests -v
```

The suite invokes the CLI in subprocesses. Tests disable automatic discovery and pass controlled search directories so results do not depend on profiles installed on the developer's machine.

Static fixtures in `tests/fixtures/profiles/` cover the normal PETG comparison and selector workflow. Tests create temporary JSON trees for behavior that needs isolation, including multi-level provenance, missing parents, inheritance cycles, and root profiles.

When adding tests:

- Use unique synthetic profile names so global fixture indexing cannot create accidental ambiguity.
- Prefer exact selected paths when the test concerns inheritance rather than search ranking.
- Assert return code and stderr as well as stdout when testing errors or warnings.
- Use CSV for exact field-level assertions and terminal output for human-readable status behavior.
- Inspect generated HTML as text for structure, classes, labels, and escaped content; do not require a browser for the unit suite.

## Focused smoke checks

Show CLI help and confirm all modes are registered:

```bash
python3 -B profile_diff.py --help
```

Run an effective comparison against committed fixtures:

```bash
python3 -B profile_diff.py \
  --no-auto-discover \
  --search-dir tests/fixtures/profiles \
  --select "Generic PETG H2C 0.4" \
  --select "Bambu PETG HF H2C 0.4" \
  --only-different \
  --show-source
```

Run a single-profile override audit:

```bash
python3 -B profile_diff.py \
  --no-auto-discover \
  --search-dir tests/fixtures/profiles \
  --select "Bambu PETG HF H2C 0.4" \
  --mode overrides
```

Write generated CSV or HTML to a temporary directory or the ignored repository-local `artifacts/` directory during smoke testing. The CLI does not create parent directories, so create it first when needed:

```bash
mkdir -p artifacts
python3 -B profile_diff.py \
  --no-auto-discover \
  --search-dir tests/fixtures/profiles \
  --select "Generic PETG H2C 0.4" \
  --select "Bambu PETG HF H2C 0.4" \
  --html artifacts/petg-diff.html
```

Do not commit generated reports.

## Pre-handoff checks

For code changes:

```bash
python3 -B -m unittest discover -s tests -v
ruff check profile_diff.py tests/test_profile_diff.py
git diff --check
git status --short
```

Ruff is optional until the repository declares it as a development dependency; if it is unavailable, report that and still run the test suite and `git diff --check`.

For documentation-only changes, run at least:

```bash
git diff --check
```

Then inspect relative Markdown links and command names manually.

## Change checklist

For a CLI option or semantic change:

1. Update argument parsing and `--help` text.
2. Keep validation errors on stderr with a nonzero exit code.
3. Update the shared collection model before changing renderers.
4. Verify terminal, CSV, and HTML behavior where the change applies.
5. Add a synthetic regression test for the main path and relevant failure path.
6. Update the README's user-facing examples.
7. Update `docs/ARCHITECTURE.md` if an invariant, pipeline stage, or output contract changed.

For profile discovery or inheritance changes, also test ambiguous names, exact-path selection, effective source provenance, missing parents, and cycles as applicable.

## Generated and local files

Do not commit:

- `__pycache__/` or `*.pyc`
- ad hoc CSV/HTML diff reports; put them in the ignored `artifacts/` directory
- local Bambu Studio or OrcaSlicer profile exports containing personal data
- editor or operating-system metadata

If recurring local artifacts become a problem, add a narrowly scoped `.gitignore` in a dedicated change rather than silently staging generated files.
