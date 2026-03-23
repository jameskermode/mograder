"""Hub data models."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from time import time


@dataclass
class MarimoSession:
    """A running headless marimo edit session."""

    username: str
    assignment: str
    port: int
    process: subprocess.Popen | None
    notebook_path: str | Path
    last_seen: float = field(default_factory=time)
