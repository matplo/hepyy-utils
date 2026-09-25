"""Convert JEWEL HepMC output to uproot-written ROOT TTrees."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np


PART_DTYPE = np.dtype(
    [
        ("pt", float),
        ("mdelta", float),
        ("phi", float),
        ("y", float),
        ("pdg_id", int),
        ("list_id", int),
    ]
)


@dataclass
class RootBuffers:
    event_id: list[int] = field(default_factory=list)
    label: list[int] = field(default_factory=list)
    px: list[float] = field(default_factory=list)
    py: list[float] = field(default_factory=list)
    pz: list[float] = field(default_factory=list)
    energy: list[float] = field(default_factory=list)
    info_event_id: list[int] = field(default_factory=list)
    weight: list[float] = field(default_factory=list)
    xsec: list[float] = field(default_factory=list)


def const_subtraction_event(parts: np.ndarray, ghosts: np.ndarray) -> list[tuple[float, float, float, float, int, int]]:
    """Event-wise 4-momentum subtraction using final particles and JEWEL ghosts."""

    if parts.size == 0 or ghosts.size == 0:
        return [(p["pt"], p["mdelta"], p["phi"], p["y"], p["pdg_id"], p["list_id"]) for p in parts]

    parts_phi = parts["phi"][:, np.newaxis]
    parts_y = parts["y"][:, np.newaxis]
    ghosts_phi = ghosts["phi"][np.newaxis, :]
    ghosts_y = ghosts["y"][np.newaxis, :]

    deltaphi = np.abs(parts_phi - ghosts_phi)
    deltaphi[deltaphi > math.pi] = 2.0 * math.pi - deltaphi[deltaphi > math.pi]
    distances = np.sqrt(deltaphi**2 + (parts_y - ghosts_y) ** 2)
    sorted_indices = np.argsort(distances.flatten())

    current_parts_pt = parts["pt"].copy()
    current_parts_mdelta = parts["mdelta"].copy()
    current_ghosts_pt = ghosts["pt"].copy()
    current_ghosts_mdelta = ghosts["mdelta"].copy()
    num_ghosts = ghosts.shape[0]

    for idx in sorted_indices:
        ipart = idx // num_ghosts
        ighost = idx % num_ghosts
        if current_parts_pt[ipart] <= 0 and current_ghosts_pt[ighost] <= 0:
            continue

        pt_p = current_parts_pt[ipart]
        pt_g = current_ghosts_pt[ighost]
        if pt_p >= pt_g:
            current_parts_pt[ipart] -= pt_g
            current_ghosts_pt[ighost] = 0.0
        else:
            current_ghosts_pt[ighost] -= pt_p
            current_parts_pt[ipart] = 0.0

        md_p = current_parts_mdelta[ipart]
        md_g = current_ghosts_mdelta[ighost]
        if md_p >= md_g:
            current_parts_mdelta[ipart] -= md_g
            current_ghosts_mdelta[ighost] = 0.0
        else:
            current_ghosts_mdelta[ighost] -= md_p
            current_parts_mdelta[ipart] = 0.0

    subevent: list[tuple[float, float, float, float, int, int]] = []
    for i in range(parts.shape[0]):
        if current_parts_pt[i] > 0:
            subevent.append(
                (
                    float(current_parts_pt[i]),
                    float(current_parts_mdelta[i]),
                    float(parts["phi"][i]),
                    float(parts["y"][i]),
                    int(parts["pdg_id"][i]),
                    int(parts["list_id"][i]),
                )
            )
    return subevent


def _momentum_components(momentum) -> tuple[float, float, float, float]:
    return (
        float(momentum.px),
        float(momentum.py),
        float(momentum.pz),
        float(momentum.e),
    )


def _append_track(buffers: RootBuffers, event_id: int, label: int, px: float, py: float, pz: float, energy: float) -> None:
    buffers.event_id.append(int(event_id))
    buffers.label.append(int(label))
    buffers.px.append(float(px))
    buffers.py.append(float(py))
    buffers.pz.append(float(pz))
    buffers.energy.append(float(energy))


def _append_event_info(buffers: RootBuffers, event_id: int, event) -> None:
    weight = math.nan
    xsec = math.nan
    weights = getattr(event, "weights", None)
    if weights:
        try:
            weight = float(weights[0])
        except Exception:
            weight = math.nan
    cross_section = getattr(event, "cross_section", None)
    if cross_section is not None:
        try:
            xsec_attr = getattr(cross_section, "xsec")
            xsec = float(xsec_attr() if callable(xsec_attr) else xsec_attr)
        except Exception:
            xsec = math.nan
    buffers.info_event_id.append(int(event_id))
    buffers.weight.append(weight)
    buffers.xsec.append(xsec)


def _kinematic_tuple(particle, list_id: int) -> tuple[float, float, float, float, int, int] | None:
    px, py, pz, energy = _momentum_components(particle.momentum)
    if not np.isfinite([px, py, pz, energy]).all() or np.isclose(energy, 1.0e-6):
        return None
    if energy - abs(pz) <= 0.0:
        return None
    pt = math.hypot(px, py)
    phi = math.atan2(py, px)
    y = 0.5 * math.log((energy + pz) / (energy - pz))
    mdelta = math.sqrt(max(energy * energy - pz * pz, 0.0)) - pt
    return (pt, mdelta, phi, y, int(particle.pid), int(list_id))


def _convert_event_without_subtraction(buffers: RootBuffers, event_id: int, event, final_status: int) -> None:
    for particle in event.particles:
        if int(particle.status) != final_status:
            continue
        px, py, pz, energy = _momentum_components(particle.momentum)
        if np.isfinite([px, py, pz, energy]).all() and not np.isclose(energy, 1.0e-6):
            _append_track(buffers, event_id, int(particle.pid), px, py, pz, energy)


def _convert_event_with_subtraction(
    buffers: RootBuffers,
    event_id: int,
    event,
    final_status: int,
    ghost_status: int,
) -> None:
    parts: list[tuple[float, float, float, float, int, int]] = []
    ghosts: list[tuple[float, float, float, float, int, int]] = []

    for idx, particle in enumerate(event.particles):
        status = int(particle.status)
        if status == final_status:
            kin = _kinematic_tuple(particle, idx)
            if kin is None:
                px, py, pz, energy = _momentum_components(particle.momentum)
                if np.isfinite([px, py, pz, energy]).all() and not np.isclose(energy, 1.0e-6):
                    _append_track(buffers, event_id, int(particle.pid), px, py, pz, energy)
            else:
                parts.append(kin)
        elif status == ghost_status:
            kin = _kinematic_tuple(particle, idx)
            if kin is not None:
                ghosts.append(kin)

    subevent = const_subtraction_event(np.array(parts, dtype=PART_DTYPE), np.array(ghosts, dtype=PART_DTYPE))
    for pt, mdelta, phi, y, pdg_id, _list_id in subevent:
        px = pt * math.cos(phi)
        py = pt * math.sin(phi)
        pz = (mdelta + pt) * math.sinh(y)
        energy = (mdelta + pt) * math.cosh(y)
        _append_track(buffers, event_id, pdg_id, px, py, pz, energy)


def _write_root(output_root_file: str | Path, buffers: RootBuffers, *, write_event_info: bool = True) -> None:
    import uproot

    output_path = Path(output_root_file).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tracks = {
        "eventID": np.asarray(buffers.event_id, dtype=np.int64),
        "label": np.asarray(buffers.label, dtype=np.int64),
        "px": np.asarray(buffers.px, dtype=np.float64),
        "py": np.asarray(buffers.py, dtype=np.float64),
        "pz": np.asarray(buffers.pz, dtype=np.float64),
        "energy": np.asarray(buffers.energy, dtype=np.float64),
    }
    with uproot.recreate(output_path) as root_file:
        root_file["tracks"] = tracks
        if write_event_info:
            root_file["event_info"] = {
                "eventID": np.asarray(buffers.info_event_id, dtype=np.int64),
                "weight": np.asarray(buffers.weight, dtype=np.float64),
                "xsec": np.asarray(buffers.xsec, dtype=np.float64),
            }


def convert_hepmc_to_root(
    input_hepmc_file: str | Path,
    output_root_file: str | Path,
    *,
    subtract_4mom: bool = False,
    max_events: int | None = None,
    final_status: int = 1,
    ghost_status: int = 3,
    progress: bool = True,
    write_event_info: bool = True,
) -> dict:
    """Convert HepMC events to ROOT track TTrees using uproot."""

    import pyhepmc
    from tqdm import tqdm

    input_path = Path(input_hepmc_file).expanduser().resolve()
    if not input_path.is_file():
        raise FileNotFoundError(f"HepMC input not found: {input_path}")

    buffers = RootBuffers()
    event_count = 0

    with pyhepmc.open(input_path) as reader:
        iterator = reader
        if progress:
            iterator = tqdm(reader, total=max_events, desc="Converting HepMC")
        for event in iterator:
            if max_events is not None and event_count >= max_events:
                break
            if write_event_info:
                _append_event_info(buffers, event_count, event)
            if subtract_4mom:
                _convert_event_with_subtraction(buffers, event_count, event, final_status, ghost_status)
            else:
                _convert_event_without_subtraction(buffers, event_count, event, final_status)
            event_count += 1

    _write_root(output_root_file, buffers, write_event_info=write_event_info)
    return {
        "input": str(input_path),
        "output": str(Path(output_root_file).expanduser().resolve()),
        "events": event_count,
        "tracks": len(buffers.event_id),
        "subtract_4mom": bool(subtract_4mom),
    }
