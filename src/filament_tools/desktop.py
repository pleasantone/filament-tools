"""Native macOS launcher for the local Filament Tools workbench."""

from __future__ import annotations

import logging
from multiprocessing import freeze_support
from pathlib import Path
from typing import Sequence

from nicegui import app as native_app
from nicegui import native, ui

from filament_tools import __version__
from filament_tools.catalog import ProfileCatalog, discover_profile_roots
from filament_tools.editor.app import create_editor_app
from filament_tools.editor.workbench_ui import render_workbench
from filament_tools.service import ProfileWorkbench

APP_NAME = "Filament Tools"
LOG_PATH = Path.home() / "Library" / "Logs" / APP_NAME / "filament-tools.log"
WEBVIEW_STORAGE_PATH = Path.home() / "Library" / "Application Support" / APP_NAME / "WebView"

native_app.native.window_args["min_size"] = (1000, 700)
native_app.native.start_args.update(
    private_mode=False,
    storage_path=str(WEBVIEW_STORAGE_PATH),
)


def configure_logging(path: Path = LOG_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        filename=path,
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        force=True,
    )


def create_desktop_workbench(roots: Sequence[Path] | None = None) -> ProfileWorkbench:
    selected_roots = list(roots) if roots is not None else discover_profile_roots()
    catalog = ProfileCatalog(
        selected_roots,
        warning_sink=lambda message: logging.getLogger(__name__).warning(message),
    )
    return ProfileWorkbench(catalog)


def run() -> None:
    configure_logging()
    logger = logging.getLogger(__name__)
    logger.info("Starting %s %s", APP_NAME, __version__)
    workbench = create_desktop_workbench()
    logger.info(
        "Indexed %d profiles from %d roots",
        len(workbench.catalog.by_path),
        len(workbench.catalog.roots),
    )
    create_editor_app(workbench, target=native_app, mount_ui=False)
    ui.run(
        root=lambda: render_workbench(workbench),
        host="127.0.0.1",
        port=native.find_open_port(8765, 8865),
        title=APP_NAME,
        favicon="🧵",
        dark=None,
        native=True,
        window_size=(1440, 1000),
        reload=False,
        show_welcome_message=False,
        uvicorn_logging_level="error",
    )


if __name__ == "__main__":
    freeze_support()
    run()
