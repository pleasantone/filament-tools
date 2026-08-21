"""Intent-oriented Filament Tools command line interface."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Sequence, Set

import typer
import uvicorn
from rich.console import Console
from rich.table import Table

from filament_tools import __version__
from filament_tools.catalog import ProfileCatalog, app_label, discover_profile_roots, source_kind
from filament_tools.comparison import compare_overrides, compare_profiles
from filament_tools.editor.app import create_editor_app
from filament_tools.editor.projects import load_project, save_project
from filament_tools.installation import apply_install_plan, plan_install, plan_lines
from filament_tools.model import IdentityMode, OutputMode, ProfileDraft, TargetVariant
from filament_tools.reporting.csv_report import write_csv
from filament_tools.reporting.html_report import write_html
from filament_tools.reporting.terminal import comparison_text, issues_text, overrides_text
from filament_tools.schema import GROUP_LABELS
from filament_tools.selectors import parse_selector
from filament_tools.service import ProfileWorkbench
from filament_tools.transforms import write_artifact, write_artifacts
from filament_tools.validation import has_errors, validate_profile_data

app = typer.Typer(
    name="filament-tools",
    help="Inspect, compare, build, validate, edit, and install filament profiles.",
    no_args_is_help=True,
)
catalog_app = typer.Typer(help="Discover and search slicer profile catalogs.")
build_app = typer.Typer(help="Build sparse children, AMS roots, and material families.")
project_app = typer.Typer(help="Create and consume portable profile draft projects.")
app.add_typer(catalog_app, name="catalog")
app.add_typer(build_app, name="build")
app.add_typer(project_app, name="project")
console = Console()
error_console = Console(stderr=True)


@dataclass
class CliState:
    search_dirs: List[Path]
    app_filter: str
    auto_discover: bool

    def roots(self, specs: Sequence[str] = ()) -> List[Path]:
        roots = list(self.search_dirs)
        if self.auto_discover:
            roots.extend(discover_profile_roots(self.app_filter))
        for spec in specs:
            raw = parse_selector(spec).spec
            path = Path(raw).expanduser()
            if path.is_file():
                roots.append(path.resolve().parent)
        return list(dict.fromkeys(path.expanduser().resolve() for path in roots if path.exists()))

    def catalog(self, specs: Sequence[str] = ()) -> ProfileCatalog:
        return ProfileCatalog(
            self.roots(specs),
            warning_sink=lambda message: error_console.print(
                f"[yellow]warning:[/yellow] {message}"
            ),
        )


def _abort(exc: Exception) -> None:
    error_console.print(f"[red]error:[/red] {exc}")
    raise typer.Exit(2)


def _parse_edits(values: Sequence[str]) -> dict:
    edits = {}
    for value in values:
        if "=" not in value:
            raise ValueError(f"invalid --set {value!r}; expected KEY=JSON")
        key, raw = value.split("=", 1)
        if not key.strip():
            raise ValueError("--set key cannot be empty")
        try:
            edits[key.strip()] = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSON value for {key!r}: {exc}") from exc
    return edits


def _draft(
    name: str,
    source: str,
    mode: OutputMode,
    base: Optional[str],
    edits: Sequence[str],
    removals: Sequence[str],
    compatibility: Sequence[str],
    identity: IdentityMode,
    filament_id: Optional[str],
    material_name: Optional[str],
    variants: Optional[List[TargetVariant]] = None,
) -> ProfileDraft:
    return ProfileDraft(
        name=name,
        source=source,
        base=base,
        output_mode=mode,
        edits=_parse_edits(edits),
        removed_keys=list(removals),
        compatible_printers=list(compatibility) or None,
        identity_mode=identity,
        filament_id=filament_id,
        material_name=material_name,
        variants=variants or [],
    )


@app.callback()
def root(
    ctx: typer.Context,
    search_dir: Optional[List[Path]] = typer.Option(
        None, "--search-dir", help="Additional profile tree; repeatable."
    ),
    app_filter: str = typer.Option(
        "all", "--app", help="Catalog application: all, bambu, or orca."
    ),
    auto_discover: bool = typer.Option(
        True, "--auto-discover/--no-auto-discover", help="Search installed slicer locations."
    ),
    version: bool = typer.Option(False, "--version", help="Show the installed version and exit."),
) -> None:
    if version:
        console.print(__version__)
        raise typer.Exit()
    if app_filter not in {"all", "bambu", "orca"}:
        raise typer.BadParameter("must be all, bambu, or orca", param_hint="--app")
    ctx.obj = CliState(
        search_dirs=search_dir or [], app_filter=app_filter, auto_discover=auto_discover
    )


@catalog_app.command("paths")
def catalog_paths(ctx: typer.Context) -> None:
    """Show every active profile search root."""
    state: CliState = ctx.obj
    roots = state.roots()
    if not roots:
        console.print("No profile search roots found.")
        raise typer.Exit(1)
    for path in roots:
        console.print(path)


@catalog_app.command("search")
def catalog_search(
    ctx: typer.Context,
    query: str = typer.Argument("", help="Case-insensitive name or filename substring."),
    limit: int = typer.Option(100, min=1, max=1000),
) -> None:
    """Search indexed filament and printer profiles."""
    state: CliState = ctx.obj
    table = Table("Name", "Application/source", "Parent", "Path")
    for profile in state.catalog().search(query, limit):
        table.add_row(
            profile.name,
            f"{app_label(profile.path)}/{source_kind(profile.path)}",
            profile.inherits or "ROOT",
            str(profile.path),
        )
    console.print(table)


@app.command("inspect")
def inspect_profile(
    ctx: typer.Context,
    selector: str,
    view: str = typer.Option("effective", help="effective, raw, or overrides"),
    show_source: bool = typer.Option(False),
) -> None:
    """Inspect one profile's raw, resolved, or explicit override state."""
    state: CliState = ctx.obj
    try:
        catalog = state.catalog([selector])
        selected = parse_selector(selector)
        profile = catalog.select(selected)
        if view == "overrides":
            reports = compare_overrides([profile], [selected.label or profile.name], catalog)
            console.print(overrides_text(reports))
        elif view in {"effective", "raw"}:
            workbench = ProfileWorkbench(catalog)
            data = workbench.profile_view(selector)
            values = data[view]
            if show_source and view == "effective":
                values = {
                    key: {"value": value, "source": data["sources"].get(key)}
                    for key, value in values.items()
                }
            console.print_json(data=values)
        else:
            raise ValueError("--view must be effective, raw, or overrides")
    except Exception as exc:
        _abort(exc)


@app.command("compare")
def compare(
    ctx: typer.Context,
    selectors: List[str] = typer.Argument(..., help="Two or more profile selectors."),
    mode: str = typer.Option("effective", help="effective or raw"),
    show_source: bool = typer.Option(False),
    only_different: bool = typer.Option(False),
    include_meta: bool = typer.Option(False),
    keys: Optional[str] = typer.Option(None, help="Regular expression over setting names."),
    group: Optional[List[str]] = typer.Option(None, "--group", help="Semantic group; repeatable."),
    csv_path: Optional[Path] = typer.Option(None, "--csv"),
    html_path: Optional[Path] = typer.Option(None, "--html"),
) -> None:
    """Compare two or more profiles with inheritance-aware provenance."""
    state: CliState = ctx.obj
    try:
        catalog = state.catalog(selectors)
        resolver = ProfileWorkbench(catalog).resolver
        parsed = [parse_selector(value) for value in selectors]
        profiles = [catalog.select(value) for value in parsed]
        groups: Optional[Set[str]] = set(group) if group else None
        unknown = groups - GROUP_LABELS.keys() if groups else set()
        if unknown:
            raise ValueError(f"unknown groups: {', '.join(sorted(unknown))}")
        report = compare_profiles(
            profiles,
            resolver,
            [value.label or profile.name for value, profile in zip(parsed, profiles, strict=True)],
            mode=mode,
            include_meta=include_meta,
            key_pattern=keys,
            groups=groups,
            only_different=only_different,
        )
        console.print(comparison_text(report, show_source))
        if csv_path:
            write_csv(csv_path, report, show_source)
            console.print(f"Wrote {csv_path}")
        if html_path:
            write_html(html_path, report, show_source)
            console.print(f"Wrote {html_path}")
    except Exception as exc:
        _abort(exc)


@build_app.command("sparse")
def build_sparse_command(
    ctx: typer.Context,
    base: str = typer.Option(...),
    source: str = typer.Option(...),
    name: str = typer.Option(...),
    output: Path = typer.Option(...),
    set_value: Optional[List[str]] = typer.Option(None, "--set", help="KEY=JSON; repeatable."),
    remove: Optional[List[str]] = typer.Option(None, "--remove"),
    compatible_printer: Optional[List[str]] = typer.Option(None, "--compatible-printer"),
    project: Optional[Path] = typer.Option(None, help="Also save this draft project."),
) -> None:
    """Build an inheriting child containing only effective differences."""
    state: CliState = ctx.obj
    try:
        workbench = ProfileWorkbench(state.catalog([base, source]))
        draft = _draft(
            name,
            source,
            OutputMode.SPARSE,
            base,
            set_value or [],
            remove or [],
            compatible_printer or [],
            IdentityMode.INHERIT,
            None,
            None,
        )
        source_view = workbench.resolver.resolve_selector(source)
        base_view = workbench.resolver.resolve_selector(base)
        draft.source_fingerprint = source_view.fingerprint
        draft.base_fingerprint = base_view.fingerprint
        artifacts = workbench.build(draft)
        issues = workbench.validate(draft, artifacts)
        if has_errors(issues):
            raise ValueError(issues_text(issues))
        console.print(f"Wrote {write_artifact(artifacts[0], str(output))}")
        if issues:
            error_console.print(issues_text(issues))
        if project:
            save_project(project, draft)
    except Exception as exc:
        _abort(exc)


@build_app.command("root")
def build_root_command(
    ctx: typer.Context,
    source: str = typer.Option(...),
    name: str = typer.Option(...),
    output: Path = typer.Option(...),
    compatible_printer: Optional[List[str]] = typer.Option(None, "--compatible-printer"),
    identity: IdentityMode = typer.Option(IdentityMode.INHERIT),
    filament_id: Optional[str] = typer.Option(None),
    material_name: Optional[str] = typer.Option(None),
    set_value: Optional[List[str]] = typer.Option(None, "--set"),
    remove: Optional[List[str]] = typer.Option(None, "--remove"),
    project: Optional[Path] = typer.Option(None),
) -> None:
    """Flatten a desired effective profile into an inheritance-free AMS root."""
    state: CliState = ctx.obj
    try:
        workbench = ProfileWorkbench(state.catalog([source]))
        draft = _draft(
            name,
            source,
            OutputMode.ROOT,
            None,
            set_value or [],
            remove or [],
            compatible_printer or [],
            identity,
            filament_id,
            material_name,
        )
        draft.source_fingerprint = workbench.resolver.resolve_selector(source).fingerprint
        artifacts = workbench.build(draft)
        issues = workbench.validate(draft, artifacts)
        if has_errors(issues):
            raise ValueError(issues_text(issues))
        console.print(f"Wrote {write_artifact(artifacts[0], str(output))}")
        if issues:
            error_console.print(issues_text(issues))
        if project:
            save_project(project, draft)
    except Exception as exc:
        _abort(exc)


def _parse_variant(value: str) -> TargetVariant:
    if "::" not in value:
        raise ValueError("variant must be NAME::PRINTER[|PRINTER...]")
    name, printers = value.split("::", 1)
    return TargetVariant(name=name, compatible_printers=printers.split("|"))


@build_app.command("family")
def build_family_command(
    ctx: typer.Context,
    source: str = typer.Option(...),
    name: str = typer.Option(..., help="Material family name."),
    variant: List[str] = typer.Option(..., "--variant", help="NAME::PRINTER[|PRINTER...]."),
    output_dir: Path = typer.Option(...),
    identity: IdentityMode = typer.Option(IdentityMode.INHERIT),
    filament_id: Optional[str] = typer.Option(None),
    material_name: Optional[str] = typer.Option(None),
    set_value: Optional[List[str]] = typer.Option(None, "--set"),
) -> None:
    """Build separate AMS roots for targets while sharing one material ID."""
    state: CliState = ctx.obj
    try:
        workbench = ProfileWorkbench(state.catalog([source]))
        variants = [_parse_variant(value) for value in variant]
        draft = _draft(
            name,
            source,
            OutputMode.ROOT,
            None,
            set_value or [],
            [],
            [],
            identity,
            filament_id,
            material_name,
            variants,
        )
        artifacts = workbench.build(draft)
        issues = workbench.validate(draft, artifacts)
        if has_errors(issues):
            raise ValueError(issues_text(issues))
        for path in write_artifacts(artifacts, str(output_dir)):
            console.print(f"Wrote {path}")
    except Exception as exc:
        _abort(exc)


@app.command("validate")
def validate_command(ctx: typer.Context, profile: Path) -> None:
    """Validate a generated profile and resolve its inheritance when present."""
    state: CliState = ctx.obj
    try:
        catalog = state.catalog([str(profile)])
        loaded = catalog.load_path(profile)
        issues = validate_profile_data(loaded.data, loaded.path)
        if loaded.inherits:
            ProfileWorkbench(catalog).resolver.resolve(loaded)
        console.print(issues_text(issues))
        if has_errors(issues):
            raise typer.Exit(1)
    except typer.Exit:
        raise
    except Exception as exc:
        _abort(exc)


@app.command("install")
def install_command(
    profiles: List[Path] = typer.Argument(...),
    app_name: str = typer.Option("bambu", "--app"),
    config_dir: Optional[Path] = typer.Option(None),
    user_folder: Optional[str] = typer.Option(None),
    dry_run: bool = typer.Option(False, help="Validate and print the plan without writing."),
) -> None:
    """Install validated profiles into Bambu Studio or OrcaSlicer."""
    try:
        plan = plan_install(
            profiles, app=app_name, app_data_dir=config_dir, user_folder=user_folder
        )
        console.print("\n".join(plan_lines(plan)))
        if plan.issues:
            error_console.print(issues_text(plan.issues))
        if not plan.valid:
            raise typer.Exit(1)
        if dry_run:
            console.print("Dry run: no files written.")
        else:
            for path in apply_install_plan(plan):
                console.print(f"Installed {path}")
    except typer.Exit:
        raise
    except Exception as exc:
        _abort(exc)


@project_app.command("init")
def project_init(
    ctx: typer.Context,
    source: str = typer.Option(...),
    output: Path = typer.Option(...),
    name: Optional[str] = typer.Option(None),
    base: Optional[str] = typer.Option(None),
    mode: OutputMode = typer.Option(OutputMode.SPARSE),
) -> None:
    """Create a portable draft with source/base fingerprints."""
    state: CliState = ctx.obj
    try:
        workbench = ProfileWorkbench(state.catalog([value for value in (source, base) if value]))
        draft = workbench.create_draft(source, name, base, mode)
        console.print(f"Wrote {save_project(output, draft)}")
    except Exception as exc:
        _abort(exc)


@project_app.command("build")
def project_build(ctx: typer.Context, project: Path, output_dir: Path) -> None:
    """Build artifact(s) from a saved draft project."""
    state: CliState = ctx.obj
    try:
        draft = load_project(project)
        workbench = ProfileWorkbench(
            state.catalog([value for value in (draft.source, draft.base) if value])
        )
        artifacts = workbench.build(draft)
        issues = workbench.validate(draft, artifacts)
        if has_errors(issues):
            raise ValueError(issues_text(issues))
        for path in write_artifacts(artifacts, str(output_dir)):
            console.print(f"Wrote {path}")
        if issues:
            error_console.print(issues_text(issues))
    except Exception as exc:
        _abort(exc)


@app.command("editor")
def editor(
    ctx: typer.Context,
    host: str = typer.Option("127.0.0.1"),
    port: int = typer.Option(8765, min=1, max=65535),
) -> None:
    """Run the local visual filament profile workbench."""
    state: CliState = ctx.obj
    workbench = ProfileWorkbench(state.catalog())
    console.print(f"Editor available at http://{host}:{port}")
    uvicorn.run(create_editor_app(workbench), host=host, port=port, log_level="info")


def run() -> None:
    app()


if __name__ == "__main__":
    run()
