import math

import pytest

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


def test_cluster_anti_kt_jets_are_ranked_and_matchable():
    pytest.importorskip("fastjet")
    jets = cluster_final_jets([10, 5, -20, 0], [0, 0.2, 0, 1], [0] * 4,
                             [10, math.hypot(5, 0.2), 20, 1], radius=0.4, min_pt=5)

    assert [row["jet_id"] for row in jets] == [0, 1]
    assert [row["jet_rank"] for row in jets] == [1, 2]
    assert [row["pt"] for row in jets] == pytest.approx([20, math.hypot(15, 0.2)])
    assert jets[1]["px"] == pytest.approx(15)
    assert jets[1]["eta"] == pytest.approx(0)
    assert [row["jet_id"] for row in match_hard_legs([_leg(1), _leg(2, phi=math.pi)], jets)] == [1, 0]
