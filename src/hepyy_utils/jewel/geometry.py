"""Read the JEWEL hard-leg geometry diagnostic sidecar."""

import csv
import gzip
import hashlib
import math
import os
import re
import shutil
import stat
import tempfile
from contextlib import contextmanager
from pathlib import Path


SCHEMA = "jewel_geometry_v1"
EVENT_FIELDS = ("b_fm", "centrality", "x0_fm", "y0_fm", "z0_fm", "t0_fm")
ME_FIELDS = ("me_px", "me_py", "me_pz", "me_e")
PATH_FIELDS = ("L_geom_T_fm", "L_hot_fm", "L_hot_T_fm", "int_T3_dl")
FIELDS = (
    "event_id", "leg_id", "pid", "weight", *EVENT_FIELDS, *ME_FIELDS,
    "px", "py", "pz", "e", *PATH_FIELDS,
)
INT_FIELDS = {"event_id", "leg_id", "pid"}
_RUN_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}")
_INTEGER = re.compile(r"[+-]?[0-9]+")
_NUMBER = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eEdD][+-]?[0-9]+)?")
_SHA256 = re.compile(r"[0-9a-f]{64}")


def resolve_geometry_path(hepmc_path, geometry=None):
    """Use an explicit path or find <HepMC filename without .gz>.geometry.csv."""
    if geometry is None:
        candidate = Path(str(hepmc_path).removesuffix(".gz") + ".geometry.csv")
        if not candidate.exists():
            return None
    else:
        candidate = Path(geometry)
    if not candidate.is_file():
        raise ValueError(f"JEWEL geometry sidecar is not a file: {candidate}")
    return candidate


def hepmc_digest(path):
    """Return a SHA-256 digest of the uncompressed HepMC bytes."""
    opener = gzip.open if str(path).endswith(".gz") else open
    digest = hashlib.sha256()
    with opener(path, "rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_geometry_digest(hepmc_path, metadata):
    """Verify the sidecar's HepMC digest when present."""
    if "hepmc_sha256" not in metadata:
        return
    expected = metadata["hepmc_sha256"]
    if not isinstance(expected, str) or not _SHA256.fullmatch(expected):
        raise ValueError("geometry hepmc_sha256 must be 64 lowercase hexadecimal characters")
    if hepmc_digest(hepmc_path) != expected:
        raise ValueError(f"geometry HepMC SHA-256 digest does not match {hepmc_path}")


def seal_geometry(geometry_path, hepmc_path):
    """Bind a validated geometry sidecar to the exact uncompressed HepMC content."""
    geometry_path = Path(geometry_path)
    with open_geometry(geometry_path) as (metadata, _):
        if "hepmc_sha256" in metadata:
            verify_geometry_digest(hepmc_path, metadata)
            return

    digest = hepmc_digest(hepmc_path)
    mode = stat.S_IMODE(geometry_path.stat().st_mode)
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(dir=geometry_path.parent, delete=False) as target:
            temp_path = Path(target.name)
            target.write(f"# hepmc_sha256={digest}\n".encode("ascii"))
            with geometry_path.open("rb") as source:
                shutil.copyfileobj(source, target)
        temp_path.chmod(mode)
        os.replace(temp_path, geometry_path)
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def _float(value, key):
    if _NUMBER.fullmatch(value):
        number = float(value.replace("D", "E").replace("d", "e"))
        if math.isfinite(number):
            return number
    raise ValueError(f"{key} must be a finite number, got {value!r}")


def _int(value, key):
    if _INTEGER.fullmatch(value):
        number = int(value)
        if -(2**63) <= number < 2**63:
            return number
    raise ValueError(f"{key} must be a signed 64-bit integer, got {value!r}")


def _read_header(stream, path):
    meta = {}
    for lineno, raw in enumerate(stream, 1):
        line = raw.strip()
        if not line:
            continue
        if not line.startswith("#"):
            break
        key, sep, value = line[1:].partition("=")
        key, value = key.strip(), value.strip()
        if not sep or not key or not value or key in meta:
            raise ValueError(f"{path}:{lineno}: invalid or duplicate geometry metadata: {line}")
        meta[key] = value
    else:
        raise ValueError(f"{path}: missing geometry CSV header")

    if tuple(next(csv.reader([line]))) != FIELDS:
        raise ValueError(f"{path}:{lineno}: expected geometry header {','.join(FIELDS)}")
    if meta.get("schema") != SCHEMA or meta.get("axis") != "shower_start":
        raise ValueError(f"{path}: expected schema={SCHEMA} and axis=shower_start")
    if not _RUN_ID.fullmatch(meta.get("run_id", "")):
        raise ValueError(f"{path}: run_id must start with a letter or digit and use at most 128 safe characters")
    if meta.get("medium") not in ("simple", "vac"):
        raise ValueError(f"{path}: expected medium=simple or medium=vac")
    try:
        meta["step_fm"] = _float(meta.get("step_fm", ""), "step_fm")
        if meta["step_fm"] <= 0:
            raise ValueError("step_fm must be positive")
    except ValueError as exc:
        raise ValueError(f"{path}: {exc}") from exc
    return meta, lineno


def _read_events(reader, path, header_lineno):
    first = None
    previous = None
    try:
        for values in reader:
            if not values:
                continue
            if len(values) != len(FIELDS):
                raise ValueError(f"expected {len(FIELDS)} geometry fields, got {len(values)}")
            row = {
                key: (_int if key in INT_FIELDS else _float)(value.strip(), key)
                for key, value in zip(FIELDS, values)
            }
            event_id, leg_id = row["event_id"], row["leg_id"]
            if event_id < 0 or leg_id not in (1, 2) or row["pid"] == 0:
                raise ValueError("geometry requires a nonnegative event_id, leg_id 1 or 2, and nonzero pid")
            if min(row["me_e"], row["e"]) <= 0:
                raise ValueError("geometry energies me_e and e must be positive")
            if any(row[key] < 0 for key in PATH_FIELDS):
                raise ValueError("geometry lengths and temperature integral must be nonnegative")
            if previous is not None and event_id <= previous:
                raise ValueError(f"geometry event {event_id} is repeated or out of order")
            if first is None:
                first = row
                continue
            if event_id != first["event_id"]:
                raise ValueError(f"geometry event {first['event_id']} is missing its second leg")
            if leg_id == first["leg_id"]:
                raise ValueError(f"duplicate geometry leg {leg_id} for event {event_id}")
            if any(row[key] != first[key] for key in ("weight", *EVENT_FIELDS)):
                raise ValueError(f"geometry legs for event {event_id} disagree on weight or production geometry")
            previous = event_id
            yield (first, row) if first["leg_id"] == 1 else (row, first)
            first = None
        if first is not None:
            raise ValueError(f"geometry event {first['event_id']} is missing its second leg")
    except (csv.Error, ValueError) as exc:
        raise ValueError(f"{path}:{header_lineno + reader.line_num}: {exc}") from exc


@contextmanager
def open_geometry(path):
    """Yield metadata and a streaming iterator of two-row events in HepMC order.

    Each event yields two row dicts in leg ID order. Consume the iterator inside
    the context to validate all records.
    """
    with open(path, encoding="utf-8", newline="") as stream:
        meta, lineno = _read_header(stream, path)
        yield meta, _read_events(csv.reader(stream, strict=True), path, lineno)
