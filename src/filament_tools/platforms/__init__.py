from filament_tools.platforms.bambu import BambuAdapter
from filament_tools.platforms.base import PlatformAdapter
from filament_tools.platforms.orca import OrcaAdapter


def platform_adapter(app: str) -> PlatformAdapter:
    if app == "bambu":
        return BambuAdapter()
    if app == "orca":
        return OrcaAdapter()
    raise ValueError(f"unsupported slicer application: {app!r}")


__all__ = ["BambuAdapter", "OrcaAdapter", "PlatformAdapter", "platform_adapter"]
