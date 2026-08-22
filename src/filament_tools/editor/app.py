"""FastAPI and NiceGUI adapters for the local filament workbench."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

from filament_tools.editor.projects import (
    load_composition_project,
    load_project,
    save_composition_project,
    save_project,
)
from filament_tools.installation import apply_install_plan, plan_install
from filament_tools.model import CompositionRecipe, ProfileDraft
from filament_tools.service import ProfileWorkbench
from filament_tools.transforms import write_artifact, write_artifacts
from filament_tools.validation import has_errors


class ProjectRequest(BaseModel):
    path: str = Field(min_length=1)
    draft: ProfileDraft


class CompositionProjectRequest(BaseModel):
    path: str = Field(min_length=1)
    recipe: CompositionRecipe


class InstallPreviewRequest(BaseModel):
    draft: ProfileDraft
    app: str = "bambu"
    config_dir: Optional[str] = None
    user_folder: Optional[str] = None


class BuildRequest(BaseModel):
    draft: ProfileDraft
    output_path: Optional[str] = None
    output_directory: Optional[str] = None


class CompositionBuildRequest(BaseModel):
    recipe: CompositionRecipe
    output_path: Optional[str] = None
    output_directory: Optional[str] = None


class ComparisonRequest(BaseModel):
    profiles: List[str] = Field(min_length=2)
    mode: str = "effective"
    include_meta: bool = False
    key_pattern: Optional[str] = None
    groups: List[str] = Field(default_factory=list)
    only_different: bool = False


class CompositionInstallRequest(BaseModel):
    recipe: CompositionRecipe
    app: str = "bambu"
    config_dir: Optional[str] = None
    user_folder: Optional[str] = None


def _artifact_json(artifact: Any) -> Dict[str, Any]:
    return {
        "name": artifact.name,
        "mode": artifact.mode.value,
        "changed_keys": list(artifact.changed_keys),
        "structural_keys": list(artifact.structural_keys),
        "data": artifact.data,
    }


def create_editor_app(workbench: ProfileWorkbench) -> FastAPI:
    app = FastAPI(title="Filament Tools Profile Editor", version="0.2.0")

    @app.get("/api/profiles")
    def profiles(
        q: str = Query(default=""),
        limit: int = Query(default=50, ge=1, le=200),
        offset: int = Query(default=0, ge=0),
        profile_type: Optional[str] = Query(default="filament"),
        app_filter: List[str] = Query(default=[]),
        source: List[str] = Query(default=[]),
        vendor_material: Optional[str] = Query(default=None),
        machine: Optional[str] = Query(default=None),
        nozzle: Optional[str] = Query(default=None),
    ) -> Dict[str, Any]:
        return workbench.catalog_query(
            q,
            limit=limit,
            offset=offset,
            profile_type=profile_type or None,
            applications=set(app_filter) or None,
            source_kinds=set(source) or None,
            vendor_or_material=vendor_material,
            machine=machine,
            nozzle=nozzle,
        )

    @app.get("/api/profile")
    def profile(selector: str) -> Dict[str, Any]:
        try:
            return workbench.profile_view(selector)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/printers")
    def printers(
        q: str = Query(default=""), limit: int = Query(default=50, ge=1, le=200)
    ) -> Dict[str, Any]:
        return workbench.printer_options(q, limit=limit)

    @app.post("/api/compare")
    def compare(request: ComparisonRequest) -> Dict[str, Any]:
        try:
            return workbench.comparison_view(
                request.profiles,
                mode=request.mode,
                include_meta=request.include_meta,
                key_pattern=request.key_pattern,
                groups=set(request.groups) or None,
                only_different=request.only_different,
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/lineage")
    def lineage() -> Dict[str, Any]:
        try:
            return workbench.lineage_view()
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/lineage/context")
    def lineage_scope(
        selector: str, child_limit: int = Query(default=50, ge=1, le=200)
    ) -> Dict[str, Any]:
        try:
            return workbench.lineage_context(selector, child_limit=child_limit)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/lineage/descendants")
    def lineage_branch(
        selector: str, limit: int = Query(default=500, ge=1, le=2000)
    ) -> Dict[str, Any]:
        try:
            return workbench.lineage_descendants(selector, limit=limit)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/composition")
    def composition(recipe: CompositionRecipe) -> Dict[str, Any]:
        try:
            return workbench.composition_view(recipe)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/composition/preview")
    def composition_preview(recipe: CompositionRecipe) -> Dict[str, Any]:
        try:
            artifacts = workbench.build_recipe(recipe)
            issues = workbench.validate_recipe(recipe, artifacts)
            return {
                "artifacts": [_artifact_json(artifact) for artifact in artifacts],
                "issues": [issue.model_dump(mode="json") for issue in issues],
            }
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/preview")
    def preview(draft: ProfileDraft) -> Dict[str, Any]:
        try:
            artifacts = workbench.build(draft)
            issues = workbench.validate(draft, artifacts)
            return {
                "artifacts": [_artifact_json(artifact) for artifact in artifacts],
                "issues": [issue.model_dump(mode="json") for issue in issues],
            }
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/build")
    def build(request: BuildRequest) -> Dict[str, Any]:
        try:
            artifacts = workbench.build(request.draft)
            issues = workbench.validate(request.draft, artifacts)
            if has_errors(issues):
                detail = "; ".join(f"{issue.code}: {issue.message}" for issue in issues)
                raise ValueError(detail)
            if len(artifacts) == 1:
                if not request.output_path:
                    raise ValueError("one-profile builds require output_path")
                paths = [write_artifact(artifacts[0], request.output_path)]
            else:
                if not request.output_directory:
                    raise ValueError("family builds require output_directory")
                paths = write_artifacts(artifacts, request.output_directory)
            return {
                "paths": paths,
                "issues": [issue.model_dump(mode="json") for issue in issues],
            }
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/composition/build")
    def composition_build(request: CompositionBuildRequest) -> Dict[str, Any]:
        try:
            artifacts = workbench.build_recipe(request.recipe)
            issues = workbench.validate_recipe(request.recipe, artifacts)
            if has_errors(issues):
                detail = "; ".join(f"{issue.code}: {issue.message}" for issue in issues)
                raise ValueError(detail)
            if len(artifacts) == 1:
                if not request.output_path:
                    raise ValueError("one-profile builds require output_path")
                paths = [write_artifact(artifacts[0], request.output_path)]
            else:
                if not request.output_directory:
                    raise ValueError("family builds require output_directory")
                paths = write_artifacts(artifacts, request.output_directory)
            return {
                "paths": paths,
                "issues": [issue.model_dump(mode="json") for issue in issues],
            }
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/install-plan")
    def install_preview(request: InstallPreviewRequest) -> Dict[str, Any]:
        try:
            artifacts = workbench.build(request.draft)
            plan = plan_install(
                artifacts=artifacts,
                app=request.app,
                app_data_dir=Path(request.config_dir) if request.config_dir else None,
                user_folder=request.user_folder,
            )
            return {
                "valid": plan.valid,
                "operations": [
                    {
                        "destination": str(operation.destination),
                        "is_root": operation.is_root,
                    }
                    for operation in plan.operations
                ],
                "issues": [issue.model_dump(mode="json") for issue in plan.issues],
            }
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    def _composition_install_plan(request: CompositionInstallRequest):
        artifacts = workbench.build_recipe(request.recipe)
        issues = workbench.validate_recipe(request.recipe, artifacts)
        if has_errors(issues):
            detail = "; ".join(f"{issue.code}: {issue.message}" for issue in issues)
            raise ValueError(detail)
        plan = plan_install(
            artifacts=artifacts,
            app=request.app,
            app_data_dir=Path(request.config_dir) if request.config_dir else None,
            user_folder=request.user_folder,
        )
        plan.issues[:0] = issues
        return plan

    @app.post("/api/composition/install-plan")
    def composition_install_preview(request: CompositionInstallRequest) -> Dict[str, Any]:
        try:
            plan = _composition_install_plan(request)
            return {
                "valid": plan.valid,
                "operations": [
                    {"destination": str(operation.destination), "is_root": operation.is_root}
                    for operation in plan.operations
                ],
                "issues": [issue.model_dump(mode="json") for issue in plan.issues],
            }
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/composition/install")
    def composition_install(request: CompositionInstallRequest) -> Dict[str, Any]:
        try:
            plan = _composition_install_plan(request)
            return {"paths": [str(path) for path in apply_install_plan(plan)]}
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/project/save")
    def project_save(request: ProjectRequest) -> Dict[str, str]:
        try:
            return {"path": str(save_project(Path(request.path), request.draft))}
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/project/load")
    def project_load(path: str) -> Dict[str, Any]:
        try:
            return load_project(Path(path)).model_dump(mode="json")
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/composition/project/save")
    def composition_project_save(request: CompositionProjectRequest) -> Dict[str, str]:
        try:
            return {"path": str(save_composition_project(Path(request.path), request.recipe))}
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/composition/project/load")
    def composition_project_load(path: str) -> Dict[str, Any]:
        try:
            return load_composition_project(Path(path)).model_dump(mode="json")
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    from filament_tools.editor.workbench_ui import mount_workbench

    mount_workbench(app, workbench)

    return app
