"""Load native Core configuration literally and start the loopback API.

Shell evaluation is deliberately excluded because JSON, OAuth metadata, and tokens can
contain characters that a shell would reinterpret. Environment values are never logged.
"""

from __future__ import annotations

import os
from pathlib import Path
import re
import sys
from collections.abc import Sequence

import uvicorn


ENVIRONMENT_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def loadEnvironmentFile(environmentPath: Path) -> dict[str, str]:
    """Parse one simple KEY=VALUE file without expanding or evaluating its values."""
    if not environmentPath.is_file():
        raise FileNotFoundError("Required Core environment file is unavailable")

    loadedEnvironment: dict[str, str] = {}
    for lineNumber, rawLine in enumerate(environmentPath.read_text().splitlines(), start=1):
        if not rawLine or rawLine.lstrip().startswith("#"):
            continue
        variableName, separator, variableValue = rawLine.partition("=")
        if not separator:
            raise ValueError(f"environment line {lineNumber} is missing an equals sign")
        if not ENVIRONMENT_NAME_PATTERN.fullmatch(variableName):
            raise ValueError(f"environment line {lineNumber} has an invalid environment variable name")
        if not variableValue:
            raise ValueError(f"environment line {lineNumber} has an empty environment value")
        loadedEnvironment[variableName] = variableValue
    return loadedEnvironment


def loadEnvironmentFiles(environmentPaths: Sequence[Path]) -> None:
    """Load ordered environment files, allowing later files to replace earlier keys."""
    if not environmentPaths:
        raise ValueError("At least one Core environment file is required")
    for environmentPath in environmentPaths:
        os.environ.update(loadEnvironmentFile(environmentPath))


def main(argumentValues: Sequence[str] | None = None) -> int:
    """Start native LifeOps Core after loading its private managed configuration."""
    runtimeArguments = list(argumentValues if argumentValues is not None else sys.argv[1:])
    if not runtimeArguments:
        raise RuntimeError("Core environment file paths are required")

    loadEnvironmentFiles([Path(pathValue) for pathValue in runtimeArguments])
    uvicorn.run(
        "sage_core.main:createConfiguredApp",
        factory=True,
        host="127.0.0.1",
        port=8787,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
