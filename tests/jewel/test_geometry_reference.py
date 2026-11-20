import math
from pathlib import Path

import pytest
import uproot

from hepyy_utils.jewel.convert import convert_hepmc_to_root
from hepyy_utils.jewel.geometry import EVENT_FIELDS, PATH_FIELDS, open_geometry, verify_geometry_digest
from hepyy_utils.jewel.tables import convert_hepmc_to_tables, iter_events_with_geometry


FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "jewel_geometry"
LEG_KEY = ["run_id", "event_id", "leg_id"]


@pytest.fixture(params=["vac", "simple", "recoils", "long"])
def reference_run(request):
    sample = request.param
    hepmc = FIXTURE_DIR / sample / "events.hepmc.gz"
    sidecar = FIXTURE_DIR / sample / "events.hepmc.geometry.csv"
    assert hepmc.is_file(), hepmc
    assert sidecar.is_file(), sidecar

    with open_geometry(sidecar) as (metadata, events):
        verify_geometry_digest(hepmc, metadata)
        records = list(iter_events_with_geometry(hepmc, events))
    assert records
    assert metadata["medium"] == ("vac" if sample == "vac" else "simple")
    event_ids, legs = [], []
    for header, particles, pair in records:
        event_ids.append(header["event_id"])
        assert (particles[:, 0] == 23).sum() == (0 if sample == "long" else 2)
        assert [row["leg_id"] for row in pair] == [1, 2]
        for row in pair:
            assert all(math.isfinite(row[key]) and row[key] >= 0 for key in PATH_FIELDS)
            assert row["L_hot_T_fm"] <= min(row["L_hot_fm"], row["L_geom_T_fm"]) + 1e-10
            if sample == "vac":
                assert row["centrality"] == -1
                assert all(row[key] == 0 for key in PATH_FIELDS)
            else:
                assert 0 <= row["centrality"] <= 1
                assert row["L_geom_T_fm"] > 0
            legs.append({"run_id": metadata["run_id"], **row})
    if sample != "vac":
        assert any(row["int_T3_dl"] > 0 for row in legs)
    return hepmc, metadata["run_id"], event_ids, legs


def _root_columns(tree, keys):
    return {key: tree[key].array(library="np").tolist() for key in keys}


def test_reference_tables(reference_run, tmp_path):
    pq = pytest.importorskip("pyarrow.parquet")
    pytest.importorskip("fastjet")
    hepmc, run_id, event_ids, legs = reference_run

    convert_hepmc_to_tables(
        [hepmc], tmp_path, format="both", particles="both", jets=True,
        jet_radius=0.4, jet_ptmin=20, jet_eta_max=3.1, chunk=2,
    )

    event_keys = ["run_id", "event_id", *EVENT_FIELDS]
    events = pq.read_table(tmp_path / "events.events.parquet", columns=event_keys).to_pydict()
    geometry = pq.read_table(tmp_path / "events.geometry.parquet")
    matches = pq.read_table(tmp_path / "events.jet_matches.parquet")
    jets = pq.read_table(tmp_path / "events.jets.parquet").to_pylist()
    jets_all = pq.read_table(tmp_path / "events.jets_all.parquet")
    assert events["run_id"] == [run_id] * len(event_ids)
    assert events["event_id"] == event_ids
    for key in EVENT_FIELDS:
        assert events[key] == [row[key] for row in legs[::2]]
    assert geometry.to_pylist() == legs
    assert matches.select(LEG_KEY).to_pydict() == geometry.select(LEG_KEY).to_pydict()
    with uproot.open(tmp_path / "events.root") as root:
        assert _root_columns(root["events"], event_keys) == events
        assert _root_columns(root["geometry"], geometry.column_names) == geometry.to_pydict()
        match_keys = [*LEG_KEY, "analysis_selected"]
        assert _root_columns(root["jet_matches"], match_keys) == matches.select(match_keys).to_pydict()
        assert _root_columns(root["jets_all"], jets_all.column_names) == jets_all.to_pydict()

    all_jet_rows = jets_all.to_pylist()
    full_collection = {(row["run_id"], row["event_id"], row["jet_id"]): row for row in all_jet_rows}
    assert len(full_collection) == len(all_jet_rows)
    assert all(row["analysis_selected"] == (row["pt"] >= 20 and abs(row["eta"]) <= 3.1) for row in all_jet_rows)
    assert jets == [row for row in all_jet_rows if row["analysis_selected"]]
    matched = []
    for row in matches.to_pylist():
        if row["matched"]:
            assert row["n_candidates"] > 0
            assert 0 <= row["delta_r"] <= 0.3
            key = (row["run_id"], row["event_id"], row["jet_id"])
            jet = full_collection[key]
            assert row["jet_rank"] == jet["jet_rank"]
            assert row["analysis_selected"] == jet["analysis_selected"]
            matched.append(key)
        else:
            assert row["jet_id"] == -1
            assert row["jet_rank"] == -1 and not row["analysis_selected"]
    assert len(set(matched)) == len(matched)


def test_reference_legacy_root_join(reference_run, tmp_path):
    hepmc, run_id, event_ids, legs = reference_run
    output = tmp_path / "legacy.root"
    result = convert_hepmc_to_root(hepmc, output, progress=False)
    assert result["events"] == len(event_ids)

    with uproot.open(output) as root:
        info = _root_columns(root["event_info"], ("run_id", "jewel_event", "eventID"))
        assert info == {"run_id": [run_id] * len(event_ids), "jewel_event": event_ids,
                        "eventID": list(range(len(event_ids)))}
        geometry = _root_columns(root["geometry"], (*legs[0], "eventID"))
        assert geometry.pop("eventID") == [ordinal for ordinal in info["eventID"] for _ in range(2)]
        assert geometry == {key: [row[key] for row in legs] for key in legs[0]}
        tracks = _root_columns(root["tracks"], ("run_id", "eventID"))
        assert set(zip(tracks["run_id"], tracks["eventID"])) == set(zip(info["run_id"], info["eventID"]))
