"""Pythia8 truth-flavor helpers for jet studies.

The functions in this module are intentionally library-first: they do not
import Pythia8, FastJet, cppyy, or heppyyier at module import time.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Iterable, Mapping


@dataclass(frozen=True)
class FlavorLabel:
    index: int
    pdg_id: int
    pt: float
    eta: float
    phi: float
    status_abs: int | None = None
    source: str = "unknown"


@dataclass(frozen=True)
class FlavorTag:
    flavor: str
    source: str
    pdg_id: int | None = None
    delta_r: float | None = None
    matched_index: int | None = None

    @property
    def matched(self) -> bool:
        return self.matched_index is not None


def wrap_delta_phi(dphi: float) -> float:
    return (float(dphi) + math.pi) % (2.0 * math.pi) - math.pi


def delta_r(eta_a: float, phi_a: float, eta_b: float, phi_b: float) -> float:
    return math.hypot(float(eta_a) - float(eta_b), wrap_delta_phi(float(phi_a) - float(phi_b)))


def classify_pdg_id(
    pdg_id: int | None,
    *,
    b_abs_ids: Iterable[int] = (5,),
    light_abs_ids: Iterable[int] = (1, 2, 3),
    gluon_is_light: bool = False,
    charm_is_light: bool = False,
) -> str:
    if pdg_id is None:
        return "unmatched"
    abs_id = abs(int(pdg_id))
    if abs_id in set(int(v) for v in b_abs_ids):
        return "b"
    if abs_id in set(int(v) for v in light_abs_ids):
        return "light"
    if abs_id == 21:
        return "light" if gluon_is_light else "gluon"
    if abs_id == 4:
        return "light" if charm_is_light else "charm"
    return "other"


def extract_hard_partons(
    event: Any,
    *,
    status_abs: int = 23,
    min_pt: float = 0.0,
) -> list[FlavorLabel]:
    labels: list[FlavorLabel] = []
    for index, particle in _iter_pythia_event(event):
        if _call_int(particle, "statusAbs") != int(status_abs):
            continue
        if not _call_bool(particle, "isParton", default=True):
            continue
        pt = _call_float(particle, "pT")
        if pt < float(min_pt):
            continue
        labels.append(
            FlavorLabel(
                index=index,
                pdg_id=_call_int(particle, "id"),
                pt=pt,
                eta=_call_float(particle, "eta"),
                phi=_call_float(particle, "phi"),
                status_abs=_call_int(particle, "statusAbs"),
                source="hard_parton",
            )
        )
    return labels


def is_heavy_hadron_pdg_id(pdg_id: int, *, quark_digit: int = 5) -> bool:
    abs_id = abs(int(pdg_id))
    if abs_id <= 100:
        return False
    return str(int(quark_digit)) in str(abs_id)


def extract_heavy_hadrons(
    event: Any,
    *,
    quark_digit: int = 5,
    min_pt: float = 0.0,
) -> list[FlavorLabel]:
    labels: list[FlavorLabel] = []
    for index, particle in _iter_pythia_event(event):
        pdg_id = _call_int(particle, "id")
        if not is_heavy_hadron_pdg_id(pdg_id, quark_digit=quark_digit):
            continue
        if not _call_bool(particle, "isHadron", default=True):
            continue
        pt = _call_float(particle, "pT")
        if pt < float(min_pt):
            continue
        labels.append(
            FlavorLabel(
                index=index,
                pdg_id=pdg_id,
                pt=pt,
                eta=_call_float(particle, "eta"),
                phi=_call_float(particle, "phi"),
                status_abs=_call_int(particle, "statusAbs"),
                source="heavy_hadron",
            )
        )
    return labels


def nearest_label(
    eta: float,
    phi: float,
    labels: Iterable[FlavorLabel],
    *,
    match_radius: float = 0.3,
) -> tuple[FlavorLabel | None, float | None]:
    best_label = None
    best_dr = None
    for label in labels:
        dr = delta_r(eta, phi, label.eta, label.phi)
        if best_dr is None or dr < best_dr:
            best_label = label
            best_dr = dr
    if best_label is None or best_dr is None or best_dr > float(match_radius):
        return None, best_dr
    return best_label, best_dr


def tag_axis_by_hard_parton(
    eta: float,
    phi: float,
    partons: Iterable[FlavorLabel],
    *,
    match_radius: float = 0.3,
    b_abs_ids: Iterable[int] = (5,),
    light_abs_ids: Iterable[int] = (1, 2, 3),
    gluon_is_light: bool = False,
    charm_is_light: bool = False,
) -> FlavorTag:
    label, dr = nearest_label(eta, phi, partons, match_radius=match_radius)
    if label is None:
        return FlavorTag("unmatched", source="hard_parton", delta_r=dr)
    flavor = classify_pdg_id(
        label.pdg_id,
        b_abs_ids=b_abs_ids,
        light_abs_ids=light_abs_ids,
        gluon_is_light=gluon_is_light,
        charm_is_light=charm_is_light,
    )
    return FlavorTag(flavor, source="hard_parton", pdg_id=label.pdg_id, delta_r=dr, matched_index=label.index)


def tag_jet_by_hard_parton(jet: Any, partons: Iterable[FlavorLabel], **kwargs: Any) -> FlavorTag:
    return tag_axis_by_hard_parton(_jet_eta(jet), _jet_phi(jet), partons, **kwargs)


def make_heavy_hadron_ghosts(
    event: Any,
    fastjet: Any,
    *,
    ghost_scale: float = 1.0e-20,
    user_index_offset: int = 10_000_000,
    quark_digit: int = 5,
) -> tuple[list[Any], dict[int, FlavorLabel]]:
    ghosts = []
    labels_by_user_index: dict[int, FlavorLabel] = {}
    for offset, label in enumerate(extract_heavy_hadrons(event, quark_digit=quark_digit)):
        particle = event[label.index]
        ghost = fastjet.PseudoJet(
            _call_float(particle, "px") * float(ghost_scale),
            _call_float(particle, "py") * float(ghost_scale),
            _call_float(particle, "pz") * float(ghost_scale),
            _call_float(particle, "e") * float(ghost_scale),
        )
        user_index = int(user_index_offset) + offset
        set_user_index = getattr(ghost, "set_user_index", None)
        if not callable(set_user_index):
            raise RuntimeError("FastJet PseudoJet does not expose set_user_index; cannot build heavy-hadron ghosts")
        set_user_index(user_index)
        ghosts.append(ghost)
        labels_by_user_index[user_index] = label
    return ghosts, labels_by_user_index


def append_ghosts(pseudojet_vector: Any, ghosts: Iterable[Any]) -> Any:
    for ghost in ghosts:
        pseudojet_vector.push_back(ghost)
    return pseudojet_vector


def ghost_labels_in_jet(
    jet: Any,
    labels_by_user_index: Mapping[int, FlavorLabel],
    *,
    user_index_offset: int = 10_000_000,
) -> list[FlavorLabel]:
    labels = []
    for constituent in jet.constituents():
        user_index_method = getattr(constituent, "user_index", None)
        if not callable(user_index_method):
            continue
        user_index = int(user_index_method())
        if user_index >= int(user_index_offset) and user_index in labels_by_user_index:
            labels.append(labels_by_user_index[user_index])
    return labels


def tag_jet_by_heavy_hadron_ghosts(
    jet: Any,
    labels_by_user_index: Mapping[int, FlavorLabel],
    *,
    user_index_offset: int = 10_000_000,
) -> FlavorTag:
    labels = ghost_labels_in_jet(jet, labels_by_user_index, user_index_offset=user_index_offset)
    if not labels:
        return FlavorTag("unmatched", source="hadron_ghost")
    label = max(labels, key=lambda item: item.pt)
    return FlavorTag("b", source="hadron_ghost", pdg_id=label.pdg_id, delta_r=0.0, matched_index=label.index)


def require_hadronization_for_ghost_tagging(hadronization: bool) -> None:
    if not hadronization:
        raise RuntimeError("hadron_ghost flavor tagging requires hadronization; set hadronization=True")


def _iter_pythia_event(event: Any):
    size = int(event.size())
    for index in range(size):
        yield index, event[index]


def _call_bool(obj: Any, name: str, *, default: bool = False) -> bool:
    method = getattr(obj, name, None)
    if not callable(method):
        return bool(default)
    return bool(method())


def _call_int(obj: Any, name: str) -> int:
    method = getattr(obj, name, None)
    if not callable(method):
        raise AttributeError(f"object does not expose {name}()")
    return int(method())


def _call_float(obj: Any, name: str) -> float:
    method = getattr(obj, name, None)
    if not callable(method):
        raise AttributeError(f"object does not expose {name}()")
    return float(method())


def _jet_eta(jet: Any) -> float:
    return float(jet.eta())


def _jet_phi(jet: Any) -> float:
    phi_std = getattr(jet, "phi_std", None)
    if callable(phi_std):
        return float(phi_std())
    return float(jet.phi())

