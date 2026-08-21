from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Optional, Sequence

ROOT = Path(__file__).parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def write_profile(
    directory: Path, name: str, data: Dict[str, Any], relative: Optional[str] = None
) -> Path:
    path = directory / (relative or f"{name}.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    document = dict(data)
    document.setdefault("name", name)
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def root_profile(name: str = "Synthetic PETG") -> Dict[str, Any]:
    return {
        "name": name,
        "type": "filament",
        "from": "User",
        "version": "1.10.0.0",
        "filament_id": "P1234567",
        "filament_settings_id": [name],
        "compatible_printers": ["Bambu Lab H2C 0.4 nozzle"],
        "filament_extruder_variant": ["Direct Drive"],
        "nozzle_temperature": ["250"],
        "filament_max_volumetric_speed": ["15"],
    }


def run_cli(args: Sequence[str], cwd: Optional[Path] = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "filament_tools", *args],
        cwd=cwd or ROOT,
        env={**os.environ, "NO_COLOR": "1"},
        text=True,
        capture_output=True,
        check=False,
    )
