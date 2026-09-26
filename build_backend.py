"""Keep uv's backend; refuse distribution builds without the built browser assets."""

from pathlib import Path
from typing import Any

import uv_build


def require_cards() -> None:
    root = Path(__file__).parent / "hirz" / "mcp" / "ui"
    for name in (
        "plan-card",
        "approval-card",
        "verification-card",
        "doorbell-card",
        "scorecard",
    ):
        path = root / f"{name}.html"
        if (
            not path.is_file()
            or "</html>" not in path.read_text()
            or "<script" not in path.read_text()
        ):
            raise RuntimeError(
                "Build all five MCP cards first: pnpm --filter mcp-app build"
            )


def build_wheel(*args: Any, **kwargs: Any) -> str:
    require_cards()
    require_companion()
    return str(uv_build.build_wheel(*args, **kwargs))


def build_sdist(*args: Any, **kwargs: Any) -> str:
    require_cards()
    require_companion()
    return str(uv_build.build_sdist(*args, **kwargs))


def __getattr__(name: str) -> Any:
    return getattr(uv_build, name)


def require_companion() -> None:
    root = Path(__file__).parent / "hirz" / "companion" / "ui"
    if not all(
        (root / name).is_file()
        for name in ("index.html", "sw.js", "manifest.webmanifest", "icon.svg")
    ) or not list((root / "assets").glob("*.js")):
        raise RuntimeError("Build the companion first: pnpm --filter web build")
