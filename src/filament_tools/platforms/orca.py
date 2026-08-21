from __future__ import annotations

import os
import platform
from pathlib import Path
from typing import List

from filament_tools.platforms.base import PlatformAdapter


class OrcaAdapter(PlatformAdapter):
    def __init__(self) -> None:
        super().__init__(
            slug="orca",
            label="OrcaSlicer",
            config_name="OrcaSlicer.conf",
            environment_names=("ORCASLICER_CONFIG_DIR", "ORCA_SLICER_CONFIG_DIR"),
        )

    def data_dir_candidates(self) -> List[Path]:
        home = Path.home()
        candidates = [
            Path(os.environ[name]) for name in self.environment_names if os.environ.get(name)
        ]
        if platform.system() == "Windows":
            appdata = Path(os.environ.get("APPDATA", home / "AppData" / "Roaming"))
            local = Path(os.environ.get("LOCALAPPDATA", home / "AppData" / "Local"))
            candidates.extend((appdata / "OrcaSlicer", local / "OrcaSlicer"))
        elif platform.system() == "Darwin":
            candidates.append(home / "Library" / "Application Support" / "OrcaSlicer")
        else:
            xdg = Path(os.environ.get("XDG_CONFIG_HOME", home / ".config"))
            candidates.extend(
                (
                    xdg / "OrcaSlicer",
                    home / ".var/app/com.orcaslicer.OrcaSlicer/config/OrcaSlicer",
                )
            )
        return list(dict.fromkeys(path.expanduser().resolve() for path in candidates))
