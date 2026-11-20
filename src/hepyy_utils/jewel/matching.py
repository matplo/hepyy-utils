"""Match JEWEL shower-start directions to reconstructed final jets."""

from __future__ import annotations

import math
from itertools import product

import numpy as np


def _axis(row):
    if "eta" in row and "phi" in row:
        phi = float(row["phi"])
        return float(row["eta"]), math.remainder(phi, math.tau) if math.isfinite(phi) else math.nan
    px, py, pz = (float(row[key]) for key in ("px", "py", "pz"))
    pt = math.hypot(px, py)
    eta = math.asinh(pz / pt) if pt else math.nan
    return eta, math.atan2(py, px)


def match_hard_legs(legs, jets, max_delta_r=0.3):
    """Match up to two hard legs to distinct jets using pseudorapidity and azimuth.

    Each input mapping supplies eta/phi or px/py/pz and its leg_id or jet_id.
    Jets are given in pT rank order, with an optional explicit 1-based jet_rank.
    Select the most matches within max_delta_r, then minimize the total distance.
    Exact ties favor higher-ranked jets in leg order. A leg is ambiguous when it
    has multiple candidates or shares a candidate with another leg.
    """
    if not math.isfinite(max_delta_r) or max_delta_r <= 0:
        raise ValueError("maximum matching delta R must be positive and finite")
    legs, jets = list(legs), list(jets)
    if len(legs) > 2:
        raise ValueError("JEWEL dijet matching supports up to two hard legs")
    if len({leg["leg_id"] for leg in legs}) != len(legs) or len({jet["jet_id"] for jet in jets}) != len(jets):
        raise ValueError("JEWEL jet matching requires unique leg and jet IDs")
    jet_axes = [_axis(jet) for jet in jets]
    candidates = []
    for leg in legs:
        eta, phi = _axis(leg)
        eligible = {}
        for index, (jet_eta, jet_phi) in enumerate(jet_axes):
            if not (math.isfinite(phi) and math.isfinite(jet_phi)):
                continue
            distance = math.hypot(eta - jet_eta, math.remainder(phi - jet_phi, math.tau))
            if distance <= max_delta_r:
                eligible[index] = distance
        candidates.append(eligible)

    unmatched = len(jets)
    best_assignment = (unmatched,) * len(legs)
    best_score = (0, 0.0, best_assignment)
    for assignment in product(*(tuple(eligible) + (unmatched,) for eligible in candidates)):
        assigned = [index for index in assignment if index != unmatched]
        if len(set(assigned)) != len(assigned):
            continue
        distance = sum(eligible.get(index, 0.0) for eligible, index in zip(candidates, assignment))
        score = (-len(assigned), distance, assignment)
        if score < best_score:
            best_score, best_assignment = score, assignment

    shared = candidates[0].keys() & candidates[1].keys() if len(candidates) == 2 else set()
    results = []
    for leg, eligible, index in zip(legs, candidates, best_assignment):
        matched = index != unmatched
        jet = jets[index] if matched else {}
        results.append({
            "leg_id": leg["leg_id"],
            "jet_id": jet["jet_id"] if matched else None,
            "jet_rank": jet.get("jet_rank", index + 1) if matched else None,
            "delta_r": eligible.get(index),
            "matched": matched,
            "ambiguous": len(eligible) > 1 or bool(shared.intersection(eligible)),
            "n_candidates": len(eligible),
        })
    return results


def require_fastjet():
    try:
        import fastjet
    except ImportError as exc:
        raise RuntimeError(
            "JEWEL jet matching requires FastJet. Load it with hepyy.load('fastjet') "
            "or install the fastjet Python package."
        ) from exc
    return fastjet


def cluster_final_jets(px, py, pz, e, radius=0.4, min_pt=0.0):
    """Return inclusive anti-k_t jets from the supplied four-vectors in pT order."""
    if not math.isfinite(radius) or radius <= 0:
        raise ValueError("jet radius must be positive and finite")
    if not math.isfinite(min_pt) or min_pt < 0:
        raise ValueError("minimum jet pT must be non-negative and finite")
    vectors = [np.asarray(column, dtype=float) for column in (px, py, pz, e)]
    if any(column.ndim != 1 or column.shape != vectors[0].shape for column in vectors):
        raise ValueError("jet clustering needs four one-dimensional arrays of equal length")
    if not all(np.isfinite(column).all() for column in vectors):
        raise ValueError("jet inputs must have finite four-momenta")
    fastjet = require_fastjet()
    if not len(vectors[0]):
        return []

    if hasattr(fastjet, "gbl"):
        # The cppyy ClusterSequence constructor needs a typed C++ vector.
        particles = fastjet.gbl.std.vector[fastjet.PseudoJet]()
        for p4 in zip(*vectors):
            particles.push_back(fastjet.PseudoJet(*p4))
    else:
        particles = [fastjet.PseudoJet(*p4) for p4 in zip(*vectors)]
    definition = fastjet.JetDefinition(fastjet.antikt_algorithm, radius)
    sequence = fastjet.ClusterSequence(particles, definition)
    jets = []
    for jet in fastjet.sorted_by_pt(sequence.inclusive_jets(min_pt)):
        if jet.pt() <= 0:
            continue
        row = {"px": jet.px(), "py": jet.py(), "pz": jet.pz(), "e": jet.e(), "pt": jet.pt()}
        row["eta"], row["phi"] = _axis(row)
        row["jet_id"], row["jet_rank"] = len(jets), len(jets) + 1
        jets.append(row)
    return jets
