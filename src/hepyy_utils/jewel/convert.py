"""Convert JEWEL HepMC output to uproot-written ROOT TTrees.

Constituent subtraction of the thermal momenta (``subtract_4mom=True``) has two modes:

``cs_mode="reference"`` (default)
    ``subtraction.subtract``, a step-by-step port of the JEWEL authors' Rivet projection
    ``SubtractedJewelEvent`` (Milhano, Zapp, Eur. Phys. J. C 82 (2022)): final state = status 1
    and 4, pairs only up to ``dRmax`` (0.5), leftover thermal momenta kept as particles
    (``leftovers="keep"``, tag 2) or dropped (``leftovers="drop"``).
``cs_mode="legacy"``
    the original ``const_subtraction_event`` of this package, kept to reproduce older samples:
    status 1 only, no distance cut (every particle-thermal pair of the event takes part),
    leftovers dropped, degenerate thermal momenta dropped.

The ``tracks`` tree carries ``tag`` (0: subtracted particle, 1: particle passed through,
2: leftover thermal momentum, 3: degenerate thermal momentum; -1 without subtraction), so a
leftover convention can still be chosen at analysis time. ``event_info`` carries the JEWEL
event number, the two beam PDG ids (the pp/pn/np/nn isospin channel, each with its own running
cross section in ``xsec``; JEWEL 2.6.0 writes 2212 for both beams and marks a neutron only by its
mass, which ``subtraction.nucleon_pid`` reads) and the leftover thermal pT per event. The two beam
records (status 4 in JEWEL 2.6.0, pT = 0) are removed before the subtraction.

If the input has outgoing hard partons (status 23, from JEWEL patched with
``patch_jewel_partons.py``), they are written to a ``partons`` tree (eventID, pid, px, py, pz,
energy) that can be matched to the jets of the same eventID.
"""

from __future__ import annotations

import json
import math
import zlib
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from . import subtraction

CS_MODES = ("reference", "legacy")
PARTON_STATUS = 23
LEFTOVER_MODES = ("keep", "drop")


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
    tag: list[int] = field(default_factory=list)
    px: list[float] = field(default_factory=list)
    py: list[float] = field(default_factory=list)
    pz: list[float] = field(default_factory=list)
    energy: list[float] = field(default_factory=list)
    info_event_id: list[int] = field(default_factory=list)
    weight: list[float] = field(default_factory=list)
    xsec: list[float] = field(default_factory=list)
    jewel_event: list[int] = field(default_factory=list)
    beam1_pid: list[int] = field(default_factory=list)
    beam2_pid: list[int] = field(default_factory=list)
    cs_left_pt: list[float] = field(default_factory=list)
    parton_event_id: list[int] = field(default_factory=list)
    parton_pid: list[int] = field(default_factory=list)
    parton_px: list[float] = field(default_factory=list)
    parton_py: list[float] = field(default_factory=list)
    parton_pz: list[float] = field(default_factory=list)
    parton_energy: list[float] = field(default_factory=list)


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


def _append_track(
    buffers: RootBuffers, event_id: int, label: int, px: float, py: float, pz: float, energy: float, tag: int = -1
) -> None:
    buffers.event_id.append(int(event_id))
    buffers.label.append(int(label))
    buffers.tag.append(int(tag))
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
    beams = [subtraction.nucleon_pid(p.pid, p.generated_mass) for p in list(event.particles)[:2]]
    beams += [0] * (2 - len(beams))
    buffers.info_event_id.append(int(event_id))
    buffers.weight.append(weight)
    buffers.xsec.append(xsec)
    buffers.jewel_event.append(int(getattr(event, "event_number", -1)))
    buffers.beam1_pid.append(beams[0])
    buffers.beam2_pid.append(beams[1])
    buffers.cs_left_pt.append(math.nan)


def _append_partons(buffers: RootBuffers, event_id: int, event) -> None:
    """Outgoing hard partons (status 23) written by JEWEL patched with patch_jewel_partons.py."""

    for particle in event.particles:
        if int(particle.status) == PARTON_STATUS:
            px, py, pz, energy = _momentum_components(particle.momentum)
            buffers.parton_event_id.append(int(event_id))
            buffers.parton_pid.append(int(particle.pid))
            buffers.parton_px.append(px)
            buffers.parton_py.append(py)
            buffers.parton_pz.append(pz)
            buffers.parton_energy.append(energy)


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


def _convert_event_with_reference_subtraction(
    buffers: RootBuffers,
    event_id: int,
    event,
    *,
    dRmax: float,
    leftovers: str,
    thermal_pid: str,
    rng,
) -> float:
    """Reference constituent subtraction; returns the leftover thermal pT of the event."""

    particles = list(event.particles)
    if not particles:
        return 0.0
    status = np.array([int(p.status) for p in particles])
    pid = np.array([int(p.pid) for p in particles])
    mom = np.array([_momentum_components(p.momentum) for p in particles], dtype=np.float64)
    keep = ~subtraction.beam_mask(status, mom[:, 0], mom[:, 1])  # the two beam nucleons
    status, pid, mom = status[keep], pid[keep], mom[keep]
    out = subtraction.subtract(
        status, pid, mom[:, 0], mom[:, 1], mom[:, 2], mom[:, 3], dRmax=dRmax, thermal_pid=thermal_pid, rng=rng
    )
    left = out["tag"] == subtraction.TAG_THERMAL_LEFT
    keep = np.ones(len(out["tag"]), dtype=bool)
    if leftovers == "drop":
        keep = out["tag"] <= subtraction.TAG_PASSTHROUGH
    for i in np.flatnonzero(keep):
        _append_track(
            buffers, event_id, int(out["pid"][i]), out["px"][i], out["py"][i], out["pz"][i], out["e"][i], int(out["tag"][i])
        )
    return float(np.hypot(out["px"][left], out["py"][left]).sum())


def _convert_event_with_subtraction(
    buffers: RootBuffers,
    event_id: int,
    event,
    final_status: int,
    ghost_status: int,
) -> None:
    """Legacy subtraction (``cs_mode="legacy"``)."""
    parts: list[tuple[float, float, float, float, int, int]] = []
    ghosts: list[tuple[float, float, float, float, int, int]] = []

    for idx, particle in enumerate(event.particles):
        status = int(particle.status)
        if status == final_status:
            kin = _kinematic_tuple(particle, idx)
            if kin is None:
                px, py, pz, energy = _momentum_components(particle.momentum)
                if np.isfinite([px, py, pz, energy]).all() and not np.isclose(energy, 1.0e-6):
                    _append_track(buffers, event_id, int(particle.pid), px, py, pz, energy, 1)
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
        _append_track(buffers, event_id, pdg_id, px, py, pz, energy, 0)


def _write_root(
    output_root_file: str | Path, buffers: RootBuffers, *, write_event_info: bool = True, settings: dict | None = None
) -> None:
    import uproot

    def column(values, n, fill, dtype):
        # buffers filled by older callers may lack the newer columns
        return np.asarray(values if len(values) == n else [fill] * n, dtype=dtype)

    output_path = Path(output_root_file).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    ntrk, nev = len(buffers.event_id), len(buffers.info_event_id)
    tracks = {
        "eventID": np.asarray(buffers.event_id, dtype=np.int64),
        "label": np.asarray(buffers.label, dtype=np.int64),
        "px": np.asarray(buffers.px, dtype=np.float64),
        "py": np.asarray(buffers.py, dtype=np.float64),
        "pz": np.asarray(buffers.pz, dtype=np.float64),
        "energy": np.asarray(buffers.energy, dtype=np.float64),
        "tag": column(buffers.tag, ntrk, -1, np.int8),
    }
    with uproot.recreate(output_path) as root_file:
        root_file["tracks"] = tracks
        if settings is not None:
            root_file["jewel_cs"] = json.dumps(settings)
        if buffers.parton_event_id:
            root_file["partons"] = {
                "eventID": np.asarray(buffers.parton_event_id, dtype=np.int64),
                "pid": np.asarray(buffers.parton_pid, dtype=np.int32),
                "px": np.asarray(buffers.parton_px, dtype=np.float64),
                "py": np.asarray(buffers.parton_py, dtype=np.float64),
                "pz": np.asarray(buffers.parton_pz, dtype=np.float64),
                "energy": np.asarray(buffers.parton_energy, dtype=np.float64),
            }
        if write_event_info:
            root_file["event_info"] = {
                "eventID": np.asarray(buffers.info_event_id, dtype=np.int64),
                "weight": np.asarray(buffers.weight, dtype=np.float64),
                "xsec": np.asarray(buffers.xsec, dtype=np.float64),
                "jewel_event": column(buffers.jewel_event, nev, -1, np.int64),
                "beam1_pid": column(buffers.beam1_pid, nev, 0, np.int32),
                "beam2_pid": column(buffers.beam2_pid, nev, 0, np.int32),
                "cs_left_pt": column(buffers.cs_left_pt, nev, math.nan, np.float64),
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
    cs_mode: str = "reference",
    dRmax: float = 0.5,
    leftovers: str = "keep",
    thermal_pid: str = "reference",
    seed: int = 0,
) -> dict:
    """Convert HepMC events to ROOT track TTrees using uproot.

    With ``subtract_4mom``, ``cs_mode`` selects the reference or the legacy subtraction (see the
    module docstring); ``dRmax``, ``leftovers`` and ``thermal_pid`` apply to the reference mode.
    ``final_status`` and ``ghost_status`` apply to the legacy mode and to conversion without
    subtraction. The settings are stored in the ROOT file as the TObjString ``jewel_cs``.
    """

    if cs_mode not in CS_MODES:
        raise ValueError(f"cs_mode must be one of {CS_MODES}, not {cs_mode!r}")
    if leftovers not in LEFTOVER_MODES:
        raise ValueError(f"leftovers must be one of {LEFTOVER_MODES}, not {leftovers!r}")
    if thermal_pid not in subtraction.THERMAL_PID_MODES:
        raise ValueError(f"thermal_pid must be one of {subtraction.THERMAL_PID_MODES}, not {thermal_pid!r}")

    import pyhepmc
    from tqdm import tqdm

    input_path = Path(input_hepmc_file).expanduser().resolve()
    if not input_path.is_file():
        raise FileNotFoundError(f"HepMC input not found: {input_path}")

    buffers = RootBuffers()
    event_count = 0
    rng = np.random.default_rng([int(seed), zlib.crc32(input_path.name.encode())])

    with pyhepmc.open(input_path) as reader:
        iterator = reader
        if progress:
            iterator = tqdm(reader, total=max_events, desc="Converting HepMC")
        for event in iterator:
            if max_events is not None and event_count >= max_events:
                break
            if write_event_info:
                _append_event_info(buffers, event_count, event)
            _append_partons(buffers, event_count, event)
            if subtract_4mom and cs_mode == "reference":
                left_pt = _convert_event_with_reference_subtraction(
                    buffers, event_count, event, dRmax=dRmax, leftovers=leftovers, thermal_pid=thermal_pid, rng=rng
                )
                if write_event_info:
                    buffers.cs_left_pt[-1] = left_pt
            elif subtract_4mom:
                _convert_event_with_subtraction(buffers, event_count, event, final_status, ghost_status)
            else:
                _convert_event_without_subtraction(buffers, event_count, event, final_status)
            event_count += 1

    settings = {
        "source": input_path.name,
        "subtract_4mom": bool(subtract_4mom),
        "cs_mode": cs_mode if subtract_4mom else None,
        "dRmax": dRmax if subtract_4mom and cs_mode == "reference" else None,
        "leftovers": leftovers if subtract_4mom and cs_mode == "reference" else None,
        "thermal_pid": thermal_pid if subtract_4mom and cs_mode == "reference" else None,
        "seed": int(seed),
    }
    _write_root(output_root_file, buffers, write_event_info=write_event_info, settings=settings)
    return {
        "input": str(input_path),
        "output": str(Path(output_root_file).expanduser().resolve()),
        "events": event_count,
        "tracks": len(buffers.event_id),
        "subtract_4mom": bool(subtract_4mom),
        "cs_mode": settings["cs_mode"],
    }
