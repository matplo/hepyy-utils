"""JEWEL parameter-file helpers."""

from __future__ import annotations

from pathlib import Path


def set_param_text(text: str, key: str, value: str | int | float) -> str:
    """Set one JEWEL parameter in a parameter-file text block.

    Comment lines are preserved. The first active occurrence of ``key`` is
    replaced and later duplicate active occurrences are dropped. Missing keys
    are appended.
    """

    replacement = f"{key} {value}"
    lines = text.splitlines()
    output: list[str] = []
    done = False

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            output.append(line)
            continue
        first = stripped.split(None, 1)[0]
        if first == key:
            if not done:
                output.append(replacement)
                done = True
            continue
        output.append(line)

    if not done:
        output.append(replacement)

    return "\n".join(output) + "\n"


def set_param_file(path: str | Path, key: str, value: str | int | float) -> None:
    param_path = Path(path)
    param_path.write_text(set_param_text(param_path.read_text(), key, value))
