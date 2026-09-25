"""Small artifact-cache helpers for local analysis workflows.

This module provides deterministic file naming, pickle payload storage, and
JSON sidecars. It intentionally does not define the payload schema: callers own
the meaning and portability of the objects they cache.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import pickle
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Iterable


def jsonable(value: Any) -> Any:
    """Convert common Python/numpy-like values into JSON-safe structures."""

    if dataclasses.is_dataclass(value):
        return jsonable(dataclasses.asdict(value))
    if isinstance(value, Mapping):
        return {str(key): jsonable(val) for key, val in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(val) for val in value]
    if isinstance(value, set):
        return sorted(jsonable(val) for val in value)
    if isinstance(value, Path):
        return str(value)
    item = getattr(value, "item", None)
    if callable(item):
        try:
            return item()
        except Exception:
            pass
    tolist = getattr(value, "tolist", None)
    if callable(tolist):
        try:
            return jsonable(tolist())
        except Exception:
            pass
    return value


def config_digest(config: Mapping[str, Any], *, length: int = 12) -> str:
    text = json.dumps(jsonable(config), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[: int(length)]


def safe_token(value: Any) -> str:
    text = str(value).replace(".", "p").replace("-", "m")
    return "".join(char if char.isalnum() else "_" for char in text).strip("_")


def path_label(path: str | Path, *, base_dir: str | Path | None = None) -> str:
    p = Path(path)
    if base_dir is not None:
        try:
            return str(p.relative_to(Path(base_dir)))
        except ValueError:
            pass
    return str(p)


class ArtifactCache:
    """Local artifact cache with hashed names and JSON metadata sidecars."""

    def __init__(
        self,
        root: str | Path,
        *,
        schema_version: int = 1,
        base_dir: str | Path | None = None,
        digest_length: int = 12,
    ):
        self.root = Path(root)
        self.schema_version = int(schema_version)
        self.base_dir = Path(base_dir) if base_dir is not None else None
        self.digest_length = int(digest_length)

    def digest(self, config: Mapping[str, Any]) -> str:
        return config_digest(config, length=self.digest_length)

    def safe_token(self, value: Any) -> str:
        return safe_token(value)

    def path(self, prefix: str, stem: str, config: Mapping[str, Any], *, suffix: str = "pkl") -> Path:
        suffix = suffix[1:] if suffix.startswith(".") else suffix
        return self.root / f"{safe_token(prefix)}__{safe_token(stem)}__{self.digest(config)}.{suffix}"

    def label(self, path: str | Path) -> str:
        return path_label(path, base_dir=self.base_dir)

    def write_pickle(
        self,
        path: str | Path,
        payload: Mapping[str, Any],
        *,
        sidecar_exclude: Iterable[str] = (),
        sidecar_extra: Mapping[str, Any] | None = None,
    ) -> None:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("wb") as stream:
            pickle.dump(dict(payload), stream, protocol=pickle.HIGHEST_PROTOCOL)

        excluded = set(sidecar_exclude)
        sidecar = {key: value for key, value in payload.items() if key not in excluded}
        sidecar.setdefault("cache_schema_version", self.schema_version)
        sidecar["payload_file"] = self.label(p)
        if sidecar_extra:
            sidecar.update(sidecar_extra)
        p.with_suffix(".json").write_text(json.dumps(jsonable(sidecar), indent=2, sort_keys=True), encoding="utf-8")

    def read_pickle(self, path: str | Path) -> dict[str, Any]:
        with Path(path).open("rb") as stream:
            return pickle.load(stream)

    def load_or_compute_pickle(
        self,
        path: str | Path,
        compute,
        *,
        sidecar_exclude: Iterable[str] = (),
    ) -> tuple[dict[str, Any], bool]:
        p = Path(path)
        if p.exists():
            return self.read_pickle(p), True
        payload = compute()
        self.write_pickle(p, payload, sidecar_exclude=sidecar_exclude)
        return payload, False

