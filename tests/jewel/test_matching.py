import math
import sys
from types import ModuleType, SimpleNamespace

import pytest

from hepyy_utils.fastjet import require_fastjet
from hepyy_utils.jewel.matching import cluster_final_jets, match_hard_legs


def _leg(index, eta=0.0, phi=0.0):
    return {"leg_id": index, "eta": eta, "phi": phi}


def _jet(index, eta=0.0, phi=0.0, **extra):
    return {"jet_id": index, "eta": eta, "phi": phi, **extra}


def test_matching_tracks_shower_axes_across_final_jet_rank_swap():
    legs = [{"leg_id": 1, "px": 50, "py": 0, "pz": 0}, _leg(2, phi=math.pi)]
    jets = [_jet(0, phi=3.10), _jet(1, phi=0.07)]

    matches = match_hard_legs(legs, jets)

    assert [row["leg_id"] for row in matches] == [1, 2]
    assert [row["jet_id"] for row in matches] == [1, 0]
    assert [row["jet_rank"] for row in matches] == [2, 1]
    assert [row["delta_r"] for row in matches] == pytest.approx([0.07, math.pi - 3.10])
    assert all(row["matched"] and not row["ambiguous"] for row in matches)


def test_matching_maximizes_cardinality_when_nearest_jet_is_shared():
    legs = [_leg(1), _leg(2, eta=0.25)]
    jets = [_jet(4, eta=0.1, jet_rank=5), _jet(8, eta=-0.2, jet_rank=9)]

    matches = match_hard_legs(legs, jets)

    assert [row["jet_id"] for row in matches] == [8, 4]
    assert [row["jet_rank"] for row in matches] == [9, 5]
    assert [row["n_candidates"] for row in matches] == [2, 1]
    assert all(row["ambiguous"] for row in matches)


def test_matching_minimizes_total_distance_after_cardinality():
    legs = [_leg(1, eta=0.16), _leg(2, eta=0.20)]
    jets = [_jet(0, eta=0.20), _jet(1, eta=0.07)]

    assert [row["jet_id"] for row in match_hard_legs(legs, jets)] == [1, 0]


def test_matching_reports_single_contested_jet_and_one_unmatched_leg():
    matches = match_hard_legs([_leg(1), _leg(2, eta=0.05)], [_jet(0)])

    assert matches[0]["matched"]
    assert matches[1] == {
        "leg_id": 2,
        "jet_id": None,
        "jet_rank": None,
        "delta_r": None,
        "matched": False,
        "ambiguous": True,
        "n_candidates": 1,
    }


def test_matching_wraps_phi_and_respects_distance_threshold():
    legs = [_leg(1, phi=math.pi - 0.01), _leg(2, phi=0)]
    jets = [_jet(0, phi=-math.pi + 0.01), _jet(1, eta=0.301)]
    matched, unmatched = match_hard_legs(legs, jets, max_delta_r=0.3)

    assert matched["delta_r"] == pytest.approx(0.02)
    assert not unmatched["matched"]
    assert not unmatched["ambiguous"]
    assert unmatched["n_candidates"] == 0
    assert not match_hard_legs(legs, [])[0]["matched"]


def test_require_fastjet_loads_cppyy_backend_once(monkeypatch):
    monkeypatch.delitem(sys.modules, "fastjet", raising=False)
    fastjet = ModuleType("fastjet")
    fastjet.PseudoJet = type("PseudoJet", (), {})
    fastjet.gbl = SimpleNamespace(fastjet=SimpleNamespace(PseudoJet=fastjet.PseudoJet))
    hepyy = ModuleType("hepyy")
    calls = []

    def load(name):
        calls.append(name)
        monkeypatch.setitem(sys.modules, name, fastjet)

    hepyy.load = load
    monkeypatch.setitem(sys.modules, "hepyy", hepyy)

    assert require_fastjet() is fastjet
    assert require_fastjet() is fastjet
    assert calls == ["fastjet"]


def test_require_fastjet_explains_missing_hepyy(monkeypatch):
    monkeypatch.delitem(sys.modules, "fastjet", raising=False)
    monkeypatch.setitem(sys.modules, "hepyy", None)

    with pytest.raises(RuntimeError, match="hepyy install fastjet") as caught:
        require_fastjet()

    assert "pip install" in str(caught.value)
    assert isinstance(caught.value.__cause__, ImportError)


def test_require_fastjet_preserves_native_load_failure(monkeypatch):
    monkeypatch.delitem(sys.modules, "fastjet", raising=False)
    hepyy = ModuleType("hepyy")
    failure = OSError("cannot open libfastjet")

    def load(name):
        assert name == "fastjet"
        raise failure

    hepyy.load = load
    monkeypatch.setitem(sys.modules, "hepyy", hepyy)

    with pytest.raises(RuntimeError, match="hepyy install fastjet") as caught:
        require_fastjet()

    assert caught.value.__cause__ is failure


def test_require_fastjet_does_not_import_standalone_binding_if_proxy_is_missing(monkeypatch, tmp_path):
    monkeypatch.delitem(sys.modules, "fastjet", raising=False)
    (tmp_path / "fastjet.py").write_text('raise AssertionError("Standalone binding was imported")\n')
    monkeypatch.syspath_prepend(str(tmp_path))
    hepyy = ModuleType("hepyy")

    def load(name):
        assert name == "fastjet"

    hepyy.load = load
    monkeypatch.setitem(sys.modules, "hepyy", hepyy)

    with pytest.raises(RuntimeError, match=r"(?i)restart"):
        require_fastjet()

    assert "fastjet" not in sys.modules


@pytest.mark.parametrize("has_cppyy_namespace", [False, True])
def test_require_fastjet_rejects_preloaded_non_native_binding(monkeypatch, has_cppyy_namespace):
    fastjet = ModuleType("fastjet")
    fastjet.PseudoJet = type("PseudoJet", (), {})
    if has_cppyy_namespace:
        fastjet.gbl = SimpleNamespace(fastjet=SimpleNamespace(PseudoJet=object()))
    monkeypatch.setitem(sys.modules, "fastjet", fastjet)
    hepyy = ModuleType("hepyy")

    def load(name):
        pytest.fail(f"Loaded native {name} while an incompatible binding was present")

    hepyy.load = load
    monkeypatch.setitem(sys.modules, "hepyy", hepyy)

    with pytest.raises(RuntimeError, match=r"(?i)restart"):
        require_fastjet()

    assert sys.modules["fastjet"] is fastjet


def test_cluster_anti_kt_jets_are_ranked_and_matchable(native_fastjet):
    jets = cluster_final_jets([10, 5, -20, 0], [0, 0.2, 0, 1], [0] * 4,
                             [10, math.hypot(5, 0.2), 20, 1], radius=0.4, min_pt=5)

    assert [row["jet_id"] for row in jets] == [0, 1]
    assert [row["jet_rank"] for row in jets] == [1, 2]
    assert [row["pt"] for row in jets] == pytest.approx([20, math.hypot(15, 0.2)])
    assert jets[1]["px"] == pytest.approx(15)
    assert jets[1]["eta"] == pytest.approx(0)
    assert [row["jet_id"] for row in match_hard_legs([_leg(1), _leg(2, phi=math.pi)], jets)] == [1, 0]
