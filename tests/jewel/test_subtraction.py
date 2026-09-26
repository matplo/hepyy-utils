import json
import math

import numpy as np
import pytest

from hepyy_utils.jewel import subtraction
from hepyy_utils.jewel.convert import PART_DTYPE, const_subtraction_event


def _p4(pt, y, phi, m=0.0):
    mt = math.hypot(pt, m)
    return pt * math.cos(phi), pt * math.sin(phi), mt * math.sinh(y), mt * math.cosh(y)


def _event(rows):
    """rows: (status, pid, pt, y, phi) -> HepMC-like arrays."""
    status = np.array([r[0] for r in rows])
    pid = np.array([r[1] for r in rows])
    mom = np.array([_p4(*r[2:]) for r in rows])
    return status, pid, mom[:, 0], mom[:, 1], mom[:, 2], mom[:, 3]


def _pt(out, tag):
    m = out["tag"] == tag
    return np.hypot(out["px"][m], out["py"][m])


def test_reference_subtracts_only_within_dRmax_and_keeps_leftovers():
    # particle at (0, 0); thermal momenta at dR = 0.3 (inside) and dR = 1.0 (outside dRmax = 0.5)
    ev = _event([(1, 211, 10.0, 0.0, 0.0), (3, 21, 4.0, 0.3, 0.0), (3, 21, 3.0, 1.0, 0.0)])
    out = subtraction.subtract(*ev, dRmax=0.5)
    assert _pt(out, subtraction.TAG_SUBTRACTED) == pytest.approx([6.0])
    assert _pt(out, subtraction.TAG_THERMAL_LEFT) == pytest.approx([3.0])  # untouched, kept as particle
    assert out["pid"][out["tag"] == subtraction.TAG_THERMAL_LEFT].tolist() == [211]


def test_reference_uses_status_4_and_skips_dummies():
    ev = _event([(4, 211, 5.0, 0.0, 0.0), (1, 111, 1e-6, 0.0, 0.0), (3, 21, 1.0, 0.1, 0.0)])
    ev = list(ev)
    ev[5] = ev[5].copy()
    ev[5][1] = 1e-6  # JEWEL dummy: E = 1e-6 GeV
    out = subtraction.subtract(*ev)
    assert _pt(out, subtraction.TAG_SUBTRACTED) == pytest.approx([4.0])
    assert len(out["tag"]) == 1


def test_legacy_has_no_distance_cut():
    # the thermal momentum at dR = 1.0 is outside dRmax: reference leaves the particle alone
    rows = [(1, 211, 10.0, 0.0, 0.0), (3, 21, 3.0, 1.0, 0.0)]
    out = subtraction.subtract(*_event(rows), dRmax=0.5)
    assert _pt(out, subtraction.TAG_SUBTRACTED) == pytest.approx([10.0])
    parts = np.array([(10.0, 0.0, 0.0, 0.0, 211, 0)], dtype=PART_DTYPE)
    ghosts = np.array([(3.0, 0.0, 0.0, 1.0, 21, 1)], dtype=PART_DTYPE)
    assert const_subtraction_event(parts, ghosts)[0][0] == pytest.approx(7.0)


def test_thermal_pid_modes_change_only_leftover_ids():
    ev = _event([(1, 211, 1.0, 0.0, 0.0)] + [(3, 21, 2.0, 0.01 * k, 0.0) for k in range(300)])
    ref = subtraction.subtract(*ev)
    alt = subtraction.subtract(*ev, thermal_pid="intended", rng=np.random.default_rng(1))
    np.testing.assert_array_equal(ref["tag"], alt["tag"])
    np.testing.assert_allclose(ref["px"], alt["px"])
    assert set(alt["pid"][alt["tag"] == subtraction.TAG_THERMAL_LEFT]) == {211, -211, 111}


def _write_hepmc(path, n=8):
    pyhepmc = pytest.importorskip("pyhepmc")
    rng = np.random.default_rng(3)
    chans = [(2212, 2212), (2212, 2112), (2112, 2212), (2112, 2112)]
    with pyhepmc.open(path, "w", format="hepmc2") as writer:
        for i in range(n):
            ev = pyhepmc.GenEvent(pyhepmc.Units.GEV, pyhepmc.Units.MM)
            ev.event_number = 1 + i
            ev.weights = [1.0 + i]
            xs = pyhepmc.GenCrossSection()
            xs.set_cross_section(1.0e6 * (1 + i // 2), 0.0)
            ev.cross_section = xs
            vertex = pyhepmc.GenVertex()
            # as JEWEL 2.6.0: both beams written as 2212 with status 4, a neutron marked by its mass
            for sign, beam in zip((1, -1), chans[i // 2 % 4]):
                mass = subtraction.M_NEUTRON if beam == 2112 else subtraction.M_PROTON
                nucleon = pyhepmc.GenParticle((0, 0, sign * math.sqrt(2510**2 - mass**2), 2510), 2212, 4)
                nucleon.generated_mass = mass
                vertex.add_particle_in(nucleon)
            for status, pid, count in ((1, 211, 30), (4, -211, 3), (3, 21, 20)):
                for _ in range(count):
                    p4 = _p4(rng.exponential(2.0) + 0.2, rng.uniform(-2, 2), rng.uniform(-np.pi, np.pi), 0.14)
                    vertex.add_particle_out(pyhepmc.GenParticle(p4, pid, status))
            ev.add_vertex(vertex)
            writer.write(ev)


def test_root_reference_matches_tables_and_records_settings(tmp_path):
    uproot = pytest.importorskip("uproot")
    pq = pytest.importorskip("pyarrow.parquet")
    from hepyy_utils.jewel.convert import convert_hepmc_to_root
    from hepyy_utils.jewel.tables import convert_hepmc_to_tables

    hepmc = tmp_path / "run.hepmc"
    _write_hepmc(hepmc)
    convert_hepmc_to_root(hepmc, tmp_path / "ref.root", subtract_4mom=True, progress=False)
    convert_hepmc_to_root(hepmc, tmp_path / "drop.root", subtract_4mom=True, leftovers="drop", progress=False)
    convert_hepmc_to_tables([hepmc], tmp_path / "tab", double=True)

    with uproot.open(tmp_path / "ref.root") as f:
        tracks = f["tracks"].arrays(library="np")
        info = f["event_info"].arrays(library="np")
        settings = json.loads(str(f["jewel_cs"]))
    events = pq.read_table(tmp_path / "tab/run.events.parquet").to_pandas()
    parts = pq.read_table(tmp_path / "tab/run.particles.parquet").to_pandas()
    parts["ev"] = np.repeat(np.arange(len(events)), events.n_cs)

    assert settings["cs_mode"] == "reference" and settings["dRmax"] == 0.5
    for e in range(len(events)):
        m = tracks["eventID"] == e
        a = np.sort(np.c_[tracks["px"][m], tracks["pz"][m], tracks["tag"][m]], axis=0)
        b = parts[parts.ev == e]
        np.testing.assert_allclose(a, np.sort(np.c_[b.px, b.pz, b.tag], axis=0), rtol=1e-9, atol=1e-9)
    np.testing.assert_allclose(info["cs_left_pt"], events.cs_left_pt)
    assert info["jewel_event"].tolist() == list(range(1, 9))
    assert list(zip(info["beam1_pid"], info["beam2_pid"])) == list(zip(events.beam1_pid, events.beam2_pid))
    assert set(zip(events.beam1_pid, events.beam2_pid)) == {(2212, 2212), (2212, 2112), (2112, 2212), (2112, 2112)}
    assert not np.any((np.hypot(tracks["px"], tracks["py"]) == 0) & (np.abs(tracks["pz"]) > 2000))  # no beams

    with uproot.open(tmp_path / "drop.root") as f:
        dropped = f["tracks"].arrays(library="np")
    assert set(dropped["tag"]) <= {0, 1}
    assert len(dropped["tag"]) == int(np.isin(tracks["tag"], [0, 1]).sum())


def test_nucleon_pid_and_beam_mask():
    assert subtraction.nucleon_pid(2212, 0.93957) == 2112     # JEWEL 2.6.0 neutron beam
    assert subtraction.nucleon_pid(2212, 0.93827) == 2212
    assert subtraction.nucleon_pid(2112, 0.93957) == 2112     # JEWEL 2.2.0
    assert subtraction.nucleon_pid(211, 0.93957) == 211
    mask = subtraction.beam_mask([4, 4, 1, 4, 2], [0, 0, 0, 1.0, 0], [0, 0, 0, 0, 0])
    assert mask.tolist() == [True, True, False, False, True]
