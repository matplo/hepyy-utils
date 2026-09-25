from dataclasses import dataclass
from pathlib import Path

import numpy as np

from hepyy_utils.cache import ArtifactCache, config_digest, jsonable, safe_token


@dataclass(frozen=True)
class SmallConfig:
    value: int
    path: Path


def test_jsonable_handles_common_structured_values():
    data = jsonable(
        {
            "tuple": (1, 2),
            "set": {3, 1, 2},
            "numpy_scalar": np.int64(5),
            "numpy_array": np.asarray([1.0, 2.0]),
            "dataclass": SmallConfig(7, Path("x/y")),
        }
    )

    assert data == {
        "tuple": [1, 2],
        "set": [1, 2, 3],
        "numpy_scalar": 5,
        "numpy_array": [1.0, 2.0],
        "dataclass": {"value": 7, "path": "x/y"},
    }


def test_config_digest_is_order_insensitive_and_short():
    assert config_digest({"b": 2, "a": 1}) == config_digest({"a": 1, "b": 2})
    assert len(config_digest({"a": 1}, length=8)) == 8


def test_safe_token_removes_filename_hostile_characters():
    assert safe_token("pt 95-105/R=0.4") == "pt_95m105_R_0p4"


def test_artifact_cache_writes_pickle_and_json_sidecar(tmp_path):
    cache = ArtifactCache(tmp_path / "cache", schema_version=3, base_dir=tmp_path)
    config = {"n": 5, "mode": "demo"}
    path = cache.path("records", "pt demo", config)

    payload = {
        "cache_schema_version": cache.schema_version,
        "config": config,
        "records": [1, 2, 3],
    }
    cache.write_pickle(path, payload, sidecar_exclude={"records"})

    loaded = cache.read_pickle(path)
    sidecar = path.with_suffix(".json").read_text(encoding="utf-8")

    assert loaded == payload
    assert '"payload_file": "cache/records__pt_demo__' in sidecar
    assert '"records"' not in sidecar
    assert '"cache_schema_version": 3' in sidecar


def test_load_or_compute_pickle_reuses_existing_payload(tmp_path):
    cache = ArtifactCache(tmp_path)
    path = cache.path("payload", "demo", {"a": 1})
    calls = []

    def compute():
        calls.append("called")
        return {"value": 42}

    first, first_hit = cache.load_or_compute_pickle(path, compute)
    second, second_hit = cache.load_or_compute_pickle(path, compute)

    assert first == {"value": 42}
    assert second == {"value": 42}
    assert first_hit is False
    assert second_hit is True
    assert calls == ["called"]

