from __future__ import annotations

import os
import platform
from pathlib import Path
from typing import List

from filament_tools.platforms.base import PlatformAdapter


class BambuAdapter(PlatformAdapter):
    def __init__(self) -> None:
        super().__init__(
            slug="bambu",
            label="Bambu Studio",
            config_name="BambuStudio.conf",
            environment_names=("BAMBU_STUDIO_CONFIG_DIR", "BAMBUSTUDIO_CONFIG_DIR"),
        )

    def data_dir_candidates(self) -> List[Path]:
        home = Path.home()
        candidates = [
            Path(os.environ[name]) for name in self.environment_names if os.environ.get(name)
        ]
        if platform.system() == "Windows":
            appdata = Path(os.environ.get("APPDATA", home / "AppData" / "Roaming"))
            local = Path(os.environ.get("LOCALAPPDATA", home / "AppData" / "Local"))
            candidates.extend((appdata / "BambuStudio", local / "BambuStudio"))
        elif platform.system() == "Darwin":
            candidates.append(home / "Library" / "Application Support" / "BambuStudio")
        else:
            xdg = Path(os.environ.get("XDG_CONFIG_HOME", home / ".config"))
            candidates.extend(
                (
                    xdg / "BambuStudio",
                    home / ".var/app/com.bambulab.BambuStudio/config/BambuStudio",
                )
            )
        return list(dict.fromkeys(path.expanduser().resolve() for path in candidates))
