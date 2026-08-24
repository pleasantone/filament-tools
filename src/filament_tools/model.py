"""Typed domain objects shared by every interface."""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    "CONIN$",
    "CONOUT$",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}
_PORTABLE_FORBIDDEN_CHARACTERS = frozenset('<>:"/\\|?*')


def validate_filename_component(value: str, *, label: str = "filename") -> str:
    """Return one normalized component valid on macOS, Linux, and Windows."""
    if value != value.rstrip():
        raise ValueError(f"{label} cannot end with whitespace")
    name = unicodedata.normalize("NFC", value.strip())
    if not name:
        raise ValueError(f"{label} cannot be empty")
    if name in {".", ".."}:
        raise ValueError(f"{label} must be a portable filename")
    if name.endswith("."):
        raise ValueError(f"{label} cannot end with a dot")
    if any(character in _PORTABLE_FORBIDDEN_CHARACTERS for character in name) or any(
        ord(character) < 32 or ord(character) == 127 for character in name
    ):
        raise ValueError(f"{label} contains characters that are not portable filenames")
    device_basename = name.split(".", 1)[0].upper()
    if device_basename in _WINDOWS_RESERVED_NAMES:
        raise ValueError(f"{label} uses a reserved Windows device name")
    if len(f"{name}.json".encode()) > 255:
        raise ValueError(f"{label} is too long for a portable JSON filename")
    return name


def validate_profile_name(value: str) -> str:
    """Reject names that cannot safely become one slicer JSON filename."""
    return validate_filename_component(value, label="profile name")


class OutputMode(str, Enum):
    SPARSE = "sparse"
    ROOT = "root"


class IdentityMode(str, Enum):
    INHERIT = "inherit"
    REUSE = "reuse"
    GENERATE = "generate"
    EXPLICIT = "explicit"


class InstallAction(str, Enum):
    CREATE = "create"
    UPDATE = "update"
    UNINSTALL = "uninstall"


class ChoiceKind(str, Enum):
    SOURCE = "source"
    CUSTOM = "custom"
    REMOVE = "remove"


class Severity(str, Enum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass(frozen=True)
class Profile:
    path: Path
    data: Dict[str, Any]

    @property
    def name(self) -> str:
        return str(self.data.get("name") or self.path.stem)

    @property
    def inherits(self) -> Optional[str]:
        value = self.data.get("inherits")
        return value.strip() if isinstance(value, str) and value.strip() else None


@dataclass(frozen=True)
class ResolvedProfile:
    profile: Profile
    values: Dict[str, Any]
    sources: Dict[str, str]
    source_paths: Dict[str, Path]
    element_sources: Dict[str, Tuple[str, ...]]
    element_source_paths: Dict[str, Tuple[Path, ...]]
    package_version: Optional[str]
    chain: Tuple[str, ...]
    fingerprint: str


@dataclass(frozen=True)
class ProfileSelector:
    spec: str
    machine: Optional[str] = None
    nozzle: Optional[str] = None
    label: Optional[str] = None


class TargetVariant(BaseModel):
    """One output preset in a generated material family."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    compatible_printers: List[str] = Field(min_length=1)
    edits: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        return validate_profile_name(value)

    @field_validator("compatible_printers")
    @classmethod
    def normalize_compatibility(cls, values: List[str]) -> List[str]:
        result: List[str] = []
        for value in values:
            value = value.strip()
            if not value:
                raise ValueError("compatible printer cannot be empty")
            if value not in result:
                result.append(value)
        return result


class ProfileDraft(BaseModel):
    """Editable intent; sparse and root JSON are projections of this model."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    source: str = Field(min_length=1)
    base: Optional[str] = None
    output_mode: OutputMode = OutputMode.SPARSE
    edits: Dict[str, Any] = Field(default_factory=dict)
    removed_keys: List[str] = Field(default_factory=list)
    compatible_printers: Optional[List[str]] = None
    identity_mode: IdentityMode = IdentityMode.INHERIT
    filament_id: Optional[str] = None
    material_name: Optional[str] = None
    user_id: Optional[str] = None
    variants: List[TargetVariant] = Field(default_factory=list)
    source_fingerprint: Optional[str] = None
    base_fingerprint: Optional[str] = None

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        return validate_profile_name(value)

    @field_validator("source")
    @classmethod
    def strip_source(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("source cannot be empty")
        return value.strip()


class CompositionChoice(BaseModel):
    """One explicit setting choice in a multi-source composition recipe."""

    model_config = ConfigDict(extra="forbid")

    kind: ChoiceKind
    source: Optional[str] = None
    value: Any = None

    @model_validator(mode="after")
    def validate_choice(self) -> CompositionChoice:
        if self.kind == ChoiceKind.SOURCE and not (self.source and self.source.strip()):
            raise ValueError("a source choice requires a profile selector")
        if self.kind != ChoiceKind.SOURCE and self.source is not None:
            raise ValueError("only source choices may specify a profile selector")
        return self


class CompositionRecipe(BaseModel):
    """Portable intent for choosing effective settings from multiple profiles."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    starting_source: str = Field(min_length=1)
    reference_sources: List[str] = Field(default_factory=list)
    sparse_parent: Optional[str] = None
    output_mode: OutputMode = OutputMode.SPARSE
    selections: Dict[str, CompositionChoice] = Field(default_factory=dict)
    compatible_printers: Optional[List[str]] = None
    identity_mode: IdentityMode = IdentityMode.INHERIT
    filament_id: Optional[str] = None
    material_name: Optional[str] = None
    user_id: Optional[str] = None
    variants: List[TargetVariant] = Field(default_factory=list)
    fingerprints: Dict[str, str] = Field(default_factory=dict)

    @field_validator("name")
    @classmethod
    def strip_recipe_name(cls, value: str) -> str:
        return validate_profile_name(value)

    @field_validator("starting_source")
    @classmethod
    def strip_starting_source(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("starting_source cannot be empty")
        return value.strip()

    @field_validator("reference_sources")
    @classmethod
    def normalize_reference_sources(cls, values: List[str]) -> List[str]:
        result: List[str] = []
        for value in values:
            value = value.strip()
            if value and value not in result:
                result.append(value)
        return result

    @model_validator(mode="after")
    def validate_recipe_shape(self) -> CompositionRecipe:
        self.reference_sources = [
            source for source in self.reference_sources if source != self.starting_source
        ]
        if self.variants and self.output_mode != OutputMode.ROOT:
            raise ValueError("material-family variants require full AMS-compatible output")
        return self


class ValidationIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    severity: Severity
    code: str
    message: str
    key: Optional[str] = None
    path: Optional[str] = None


@dataclass(frozen=True)
class BuildArtifact:
    name: str
    data: Dict[str, Any]
    mode: OutputMode
    changed_keys: Tuple[str, ...]
    structural_keys: Tuple[str, ...] = ()
    source_fingerprint: Optional[str] = None
    base_fingerprint: Optional[str] = None


@dataclass(frozen=True)
class ComparisonCell:
    value: Any
    source: Optional[str]
    explicit: bool
    present: bool


@dataclass(frozen=True)
class ComparisonRow:
    key: str
    group: str
    cells: Tuple[ComparisonCell, ...]


@dataclass(frozen=True)
class ComparisonReport:
    labels: Tuple[str, ...]
    profiles: Tuple[ResolvedProfile, ...]
    rows: Tuple[ComparisonRow, ...]
    mode: str


@dataclass(frozen=True)
class OverrideRow:
    key: str
    explicit_value: Any
    parent_value: Any
    difference: str
    parent_source: Optional[str]


@dataclass(frozen=True)
class OverrideReport:
    profile: Profile
    label: str
    parent_status: str
    rows: Tuple[OverrideRow, ...]
    parent_error: Optional[str] = None


@dataclass(frozen=True)
class InstallOperation:
    source: Optional[Path]
    destination: Path
    data: Dict[str, Any]
    is_root: bool
    action: InstallAction = InstallAction.CREATE
    backup: Optional[Path] = None
    existing_fingerprint: Optional[str] = None


@dataclass
class InstallPlan:
    app: str
    app_data_dir: Path
    user_folder: str
    action: InstallAction = InstallAction.CREATE
    operations: List[InstallOperation] = field(default_factory=list)
    issues: List[ValidationIssue] = field(default_factory=list)

    @property
    def valid(self) -> bool:
        return not any(issue.severity == Severity.ERROR for issue in self.issues)
