import math
import types

import pytest

from hepyy_utils.pythia.flavor import (
    FlavorLabel,
    append_ghosts,
    classify_pdg_id,
    extract_hard_partons,
    extract_heavy_hadrons,
    ghost_labels_in_jet,
    is_heavy_hadron_pdg_id,
    make_heavy_hadron_ghosts,
    nearest_label,
    require_hadronization_for_ghost_tagging,
    tag_axis_by_hard_parton,
    tag_jet_by_heavy_hadron_ghosts,
)


class FakeParticle:
    def __init__(self, pdg_id, status_abs, pt, eta, phi, *, parton=False, hadron=False):
        self._pdg_id = pdg_id
        self._status_abs = status_abs
        self._pt = pt
        self._eta = eta
        self._phi = phi
        self._parton = parton
        self._hadron = hadron

    def id(self):
        return self._pdg_id

    def statusAbs(self):
        return self._status_abs

    def isParton(self):
        return self._parton

    def isHadron(self):
        return self._hadron

    def pT(self):
        return self._pt

    def eta(self):
        return self._eta

    def phi(self):
        return self._phi

    def px(self):
        return self._pt * math.cos(self._phi)

    def py(self):
        return self._pt * math.sin(self._phi)

    def pz(self):
        return self._pt * math.sinh(self._eta)

    def e(self):
        return self._pt * math.cosh(self._eta)


class FakeEvent:
    def __init__(self, particles):
        self._particles = list(particles)

    def size(self):
        return len(self._particles)

    def __getitem__(self, index):
        return self._particles[index]


class FakePseudoJet:
    def __init__(self, px=0.0, py=0.0, pz=0.0, energy=0.0, constituents=None):
        self.px = px
        self.py = py
        self.pz = pz
        self.energy = energy
        self._user_index = -1
        self._constituents = list(constituents or [])

    def set_user_index(self, user_index):
        self._user_index = int(user_index)

    def user_index(self):
        return self._user_index

    def constituents(self):
        return list(self._constituents)


def test_extract_hard_partons_selects_status_23_partons():
    event = FakeEvent(
        [
            FakeParticle(21, 21, 10.0, 0.0, 0.0, parton=True),
            FakeParticle(5, 23, 100.0, 0.2, 0.3, parton=True),
            FakeParticle(511, 91, 50.0, 0.2, 0.3, hadron=True),
        ]
    )

    labels = extract_hard_partons(event)

    assert labels == [FlavorLabel(1, 5, 100.0, 0.2, 0.3, 23, "hard_parton")]


def test_configurable_match_radius_accepts_and_rejects_nearest_label():
    labels = [FlavorLabel(4, 5, 90.0, 0.0, 0.0, 23, "hard_parton")]

    matched, dr = nearest_label(0.0, 0.2, labels, match_radius=0.3)
    rejected, rejected_dr = nearest_label(0.0, 0.2, labels, match_radius=0.1)

    assert matched == labels[0]
    assert dr == pytest.approx(0.2)
    assert rejected is None
    assert rejected_dr == pytest.approx(0.2)


def test_tag_axis_by_hard_parton_classifies_b_light_and_gluon():
    partons = [
        FlavorLabel(1, 5, 80.0, 0.0, 0.0, 23, "hard_parton"),
        FlavorLabel(2, 2, 80.0, 1.0, 0.0, 23, "hard_parton"),
        FlavorLabel(3, 21, 80.0, 2.0, 0.0, 23, "hard_parton"),
    ]

    assert tag_axis_by_hard_parton(0.0, 0.05, partons).flavor == "b"
    assert tag_axis_by_hard_parton(1.0, 0.05, partons).flavor == "light"
    assert tag_axis_by_hard_parton(2.0, 0.05, partons).flavor == "gluon"
    assert tag_axis_by_hard_parton(2.0, 0.05, partons, gluon_is_light=True).flavor == "light"


def test_heavy_hadron_pdg_detection_and_extraction():
    event = FakeEvent(
        [
            FakeParticle(211, 1, 5.0, 0.0, 0.0, hadron=True),
            FakeParticle(511, 91, 25.0, 0.2, 0.1, hadron=True),
            FakeParticle(541, 91, 12.0, 0.3, 0.1, hadron=True),
        ]
    )

    assert is_heavy_hadron_pdg_id(511)
    assert is_heavy_hadron_pdg_id(5122)
    assert not is_heavy_hadron_pdg_id(211)
    assert [label.pdg_id for label in extract_heavy_hadrons(event)] == [511, 541]


def test_make_heavy_hadron_ghosts_and_tag_jet():
    event = FakeEvent([FakeParticle(511, 91, 25.0, 0.2, 0.1, hadron=True)])
    fake_fastjet = types.SimpleNamespace(PseudoJet=FakePseudoJet)

    ghosts, labels = make_heavy_hadron_ghosts(event, fake_fastjet)
    vector = []
    append_ghosts(types.SimpleNamespace(push_back=vector.append), ghosts)
    jet = FakePseudoJet(constituents=vector)

    assert len(ghosts) == 1
    assert ghost_labels_in_jet(jet, labels)[0].pdg_id == 511
    tag = tag_jet_by_heavy_hadron_ghosts(jet, labels)
    assert tag.flavor == "b"
    assert tag.source == "hadron_ghost"


def test_hadron_ghost_mode_requires_hadronization():
    require_hadronization_for_ghost_tagging(True)
    with pytest.raises(RuntimeError, match="requires hadronization"):
        require_hadronization_for_ghost_tagging(False)


def test_classify_pdg_id_defaults_to_uds_light_only():
    assert classify_pdg_id(1) == "light"
    assert classify_pdg_id(4) == "charm"
    assert classify_pdg_id(5) == "b"
    assert classify_pdg_id(21) == "gluon"

