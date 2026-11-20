import gzip
import hashlib
import json

import pytest

from hepyy_utils.jewel import geometry
from hepyy_utils.jewel.geometry import FIELDS, hepmc_digest, open_geometry, seal_geometry, verify_geometry_digest
from hepyy_utils.jewel.tables import convert_hepmc_to_tables


RUN_ID = "geometry-smoke." + "abcdef" * 18
META = f"""# schema=jewel_geometry_v1
# medium=simple
# run_id={RUN_ID}
# axis=shower_start
# step_fm=5.0D-2
# scheme=midpoint
"""


def _legs(event_id):
    return [
        [event_id, 1, 21, 1.2345689, 3.5, 0.25, 1.25, -2, 0, 0,
         30, 0, 0, 30, 28, 0, 0, 28, 6, 4, 4, 0.25],
        [event_id, 2, 2, 1.2345689, 3.5, 0.25, 1.25, -2, 0, 0,
         -30, 0, 0, 30, -28, 0, 0, 28, 3, 2, 2, 0.125],
    ]


def _write_geometry(path, rows, metadata=META):
    header = ",".join(FIELDS) + "\n"
    path.write_text(metadata + header + "".join(",".join(map(str, row)) + "\n" for row in rows))


def _write_hepmc(path, event_ids=(3, 5), visible_particles="P 5 211 26 0 0 26.001 0.14 1 0 0 0 0\n"):
    with gzip.open(path, "wt") as stream:
        for event_id in event_ids:
            stream.write(f"""E {event_id} -1 30 0 0 0 0 1 1 2 0 1 0.123457E+1
U GEV MM
H 0 0 0 0 0 0 0 0 0 99 0 0 0
P 1 2212 0 0 100 100 0.93827 4 0 0 0 0
P 2 2212 0 0 -100 100 0.93827 4 0 0 0 0
P 3 21 30 0 0 30 0 23 0 0 0 0
P 4 2 -30 0 0 30 0 23 0 0 0 0
{visible_particles}P 6 12 -40 0 0 40 0 1 0 0 0 0
P 7 211 -42 0 0 42.001 0.14 3 0 0 0 0
""")


def test_hepmc_digest_reads_same_bytes_from_plain_and_gzip(tmp_path):
    content = b"E 42 -1 30 0 0 0 0 1 1 2 0 1 1\n"
    plain, compressed = tmp_path / "run.hepmc", tmp_path / "run.hepmc.gz"
    plain.write_bytes(content)
    compressed.write_bytes(gzip.compress(content))

    assert hepmc_digest(plain) == hepmc_digest(compressed) == hashlib.sha256(content).hexdigest()


def test_seal_geometry_is_idempotent_and_detects_changed_hepmc(tmp_path):
    hepmc, sidecar = tmp_path / "run.hepmc.gz", tmp_path / "run.geometry.csv"
    _write_hepmc(hepmc)
    _write_geometry(sidecar, _legs(3) + _legs(5))
    original = sidecar.read_bytes()

    seal_geometry(sidecar, hepmc)
    sealed = sidecar.read_bytes()
    assert sealed == f"# hepmc_sha256={hepmc_digest(hepmc)}\n".encode() + original
    seal_geometry(sidecar, hepmc)
    assert sidecar.read_bytes() == sealed
    with open_geometry(sidecar) as (metadata, _):
        verify_geometry_digest(hepmc, metadata)
    # Change a particle record while keeping the events, hard legs, and weights the same.
    hepmc.write_bytes(gzip.compress(gzip.decompress(hepmc.read_bytes()).replace(b"26.001", b"27.001")))

    with pytest.raises(ValueError, match="digest does not match"):
        verify_geometry_digest(hepmc, metadata)
    with pytest.raises(ValueError, match="digest does not match"):
        seal_geometry(sidecar, hepmc)
    assert sidecar.read_bytes() == sealed


def test_seal_geometry_preserves_original_when_replacement_fails(tmp_path, monkeypatch):
    hepmc, sidecar = tmp_path / "run.hepmc.gz", tmp_path / "run.geometry.csv"
    _write_hepmc(hepmc)
    _write_geometry(sidecar, _legs(3) + _legs(5))
    original = sidecar.read_bytes()

    def fail_replace(*args):
        raise OSError("test replacement failure")

    with monkeypatch.context() as patch:
        patch.setattr(geometry.os, "replace", fail_replace)
        with pytest.raises(OSError, match="test replacement failure"):
            seal_geometry(sidecar, hepmc)

    assert sidecar.read_bytes() == original
    assert set(tmp_path.iterdir()) == {sidecar, hepmc}


@pytest.mark.parametrize("invalid", ["", "0" * 63, "A" * 64, None])
def test_geometry_digest_rejects_malformed_metadata(tmp_path, invalid):
    with pytest.raises(ValueError, match="64 lowercase hexadecimal"):
        verify_geometry_digest(tmp_path / "unused.hepmc", {"hepmc_sha256": invalid})


def test_both_converters_refuse_to_publish_for_a_swapped_sealed_hepmc(tmp_path):
    from hepyy_utils.jewel.convert import convert_hepmc_to_root

    hepmc = tmp_path / "run.hepmc.gz"
    sidecar = tmp_path / "run.hepmc.geometry.csv"
    _write_hepmc(hepmc)
    _write_geometry(sidecar, _legs(3) + _legs(5))
    seal_geometry(sidecar, hepmc)
    # Simulate a different shower with the same event IDs, hard legs, and weights.
    hepmc.write_bytes(gzip.compress(gzip.decompress(hepmc.read_bytes()).replace(b"26.001", b"27.001")))

    output = tmp_path / "legacy.root"
    with pytest.raises(ValueError, match="digest does not match"):
        convert_hepmc_to_root(hepmc, output, progress=False)
    assert not output.exists()

    outdir = tmp_path / "tables"
    with pytest.raises(ValueError, match="digest does not match"):
        convert_hepmc_to_tables([hepmc], outdir, format="root", particles="raw")
    assert list(outdir.iterdir()) == []


def test_geometry_tables_roundtrip(tmp_path):
    uproot = pytest.importorskip("uproot")
    pq = pytest.importorskip("pyarrow.parquet")
    hepmc = tmp_path / "run.hepmc.gz"
    event_ids = (3, 2**53 + 1)
    _write_hepmc(hepmc, event_ids)
    _write_geometry(tmp_path / "run.hepmc.geometry.csv", sum(map(_legs, event_ids), []))
    outdir = tmp_path / "out"
    convert_hepmc_to_tables([hepmc], outdir, format="both", particles="raw", chunk=1)

    events = pq.read_table(outdir / "run.events.parquet")
    legs = pq.read_table(outdir / "run.geometry.parquet")
    metadata = json.loads(legs.schema.metadata[b"jewel_cs"])["geometry"]
    assert metadata == dict(schema="jewel_geometry_v1", medium="simple", run_id=RUN_ID,
                            axis="shower_start", step_fm=0.05, scheme="midpoint")
    assert events["event_id"].to_pylist() == list(event_ids)
    assert events["run_id"].to_pylist() == [RUN_ID] * 2
    assert events["b_fm"].to_pylist() == [3.5] * 2
    assert events["hi_b"].to_pylist() == [99.0] * 2
    assert events["x0_fm"].to_pylist() == [1.25] * 2
    assert legs["leg_id"].to_pylist() == [1, 2, 1, 2]
    assert legs["event_id"].to_pylist() == [3, 3, event_ids[1], event_ids[1]]
    assert legs["L_hot_fm"].to_pylist() == [4, 2, 4, 2]
    assert legs["me_px"].to_pylist() == [30, -30, 30, -30]
    assert legs["px"].to_pylist() == [28, -28, 28, -28]
    with uproot.open(outdir / "run.root") as root:
        assert root["geometry"].classname == "TTree"
        assert json.loads(str(root["jewel_cs"]))["geometry"] == metadata
        for name, table in (("events", events), ("geometry", legs)):
            assert root[name]["run_id"].array(library="np").tolist() == table["run_id"].to_pylist()
            assert root[name]["event_id"].array(library="np").tolist() == table["event_id"].to_pylist()


@pytest.mark.parametrize(
    ("key", "value", "error"),
    [("leg_id", 1, "duplicate geometry leg"), ("x0_fm", 4, "disagree"),
     ("e", 0, "must be positive"), ("L_hot_fm", -1, "must be nonnegative"),
     ("px", "NaN", "finite number"), ("pid", "2.0", "signed 64-bit integer")],
)
def test_invalid_leg(tmp_path, key, value, error):
    sidecar = tmp_path / "geometry.csv"
    rows = _legs(3)
    rows[1][FIELDS.index(key)] = value
    _write_geometry(sidecar, rows)
    with pytest.raises(ValueError, match=error), open_geometry(sidecar) as (_, events):
        list(events)


@pytest.mark.parametrize(
    ("edit", "error"),
    [(lambda rows: rows[:-2], "expected geometry for HepMC event 5"),
     (lambda rows: rows[:-1], "missing its second leg"),
     (lambda rows: rows + _legs(6), "extra event 6"),
     (lambda rows: rows + _legs(5), "repeated or out of order")],
)
def test_rejects_sidecar_coverage_mismatch_without_publishing(tmp_path, edit, error):
    pytest.importorskip("pyarrow.parquet")
    hepmc = tmp_path / "run.hepmc.gz"
    sidecar = tmp_path / "geometry.csv"
    _write_hepmc(hepmc)
    _write_geometry(sidecar, edit(_legs(3) + _legs(5)))
    outdir = tmp_path / "out"
    with pytest.raises(ValueError, match=error):
        convert_hepmc_to_tables([hepmc], outdir, geometry=sidecar, particles="raw", chunk=1)
    assert list(outdir.iterdir()) == []


@pytest.mark.parametrize(("key", "value", "error"), [
    ("weight", 3, "geometry weight disagrees"), ("pid", 3, "matrix-element legs disagree"),
    ("me_px", 10, "matrix-element legs disagree"),
])
def test_rejects_sidecar_identity_mismatch(tmp_path, key, value, error):
    hepmc = tmp_path / "run.hepmc.gz"
    sidecar = tmp_path / "geometry.csv"
    _write_hepmc(hepmc)
    rows = _legs(3) + _legs(5)
    rows[0][FIELDS.index(key)] = value
    if key == "weight":
        rows[1][FIELDS.index(key)] = value
    _write_geometry(sidecar, rows)
    with pytest.raises(ValueError, match=error):
        convert_hepmc_to_tables([hepmc], tmp_path / "out", geometry=sidecar)


def test_jet_tables_join_to_geometry_and_filter_raw_constituents(tmp_path):
    pytest.importorskip("fastjet")
    pq = pytest.importorskip("pyarrow.parquet")
    hepmc = tmp_path / "run.hepmc.gz"
    sidecar = tmp_path / "run.hepmc.geometry.csv"
    _write_hepmc(hepmc, (3,))
    _write_geometry(sidecar, _legs(3))
    convert_hepmc_to_tables([hepmc], tmp_path, particles="raw", jets=True)

    jets = pq.read_table(tmp_path / "run.jets.parquet").to_pylist()
    jets_all = pq.read_table(tmp_path / "run.jets_all.parquet").to_pylist()
    matches = pq.read_table(tmp_path / "run.jet_matches.parquet").to_pylist()
    assert len(jets) == 1
    assert jets_all == jets
    assert jets[0]["analysis_selected"] is True
    assert jets[0]["run_id"] == RUN_ID and jets[0]["event_id"] == 3
    assert jets[0]["pt"] == 26 and jets[0]["jet_rank"] == 1
    assert [m["leg_id"] for m in matches] == [1, 2]
    assert [m["matched"] for m in matches] == [True, False]
    assert [m["analysis_selected"] for m in matches] == [True, False]
    assert [m["jet_id"] for m in matches] == [jets[0]["jet_id"], -1]


def test_rejects_output_name_collision_before_writing(tmp_path):
    out = tmp_path / "out"
    with pytest.raises(ValueError, match="duplicate output names"):
        convert_hepmc_to_tables([tmp_path / "a/run.hepmc", tmp_path / "b/run.hepmc.gz"], out)
    assert not out.exists()


def test_jet_tables_include_empty_collection_and_unmatched_legs(tmp_path):
    pytest.importorskip("fastjet")
    uproot = pytest.importorskip("uproot")
    pa = pytest.importorskip("pyarrow")
    pq = pytest.importorskip("pyarrow.parquet")
    hepmc = tmp_path / "run.hepmc.gz"
    _write_hepmc(hepmc, (3,), visible_particles="")
    _write_geometry(tmp_path / "run.hepmc.geometry.csv", _legs(3))
    convert_hepmc_to_tables([hepmc], tmp_path, particles="raw", format="both", jets=True)

    with uproot.open(tmp_path / "run.root") as root:
        for name in ("jets", "jets_all"):
            jets = pq.read_table(tmp_path / f"run.{name}.parquet")
            assert jets.num_rows == root[name].num_entries == 0
            assert jets.schema.field("analysis_selected").type == pa.bool_()
            assert root[name]["analysis_selected"].array(library="np").dtype.kind == "b"
        matches = pq.read_table(tmp_path / "run.jet_matches.parquet")
        for key, expected in (("matched", [False, False]), ("analysis_selected", [False, False]),
                              ("jet_id", [-1, -1]), ("jet_rank", [-1, -1])):
            assert matches[key].to_pylist() == root["jet_matches"][key].array(library="np").tolist() == expected


@pytest.mark.parametrize("analysis_cuts", [{"jet_ptmin": 30}, {"jet_eta_max": 0.15}])
def test_matching_precedes_analysis_cuts(tmp_path, analysis_cuts):
    pytest.importorskip("fastjet")
    uproot = pytest.importorskip("uproot")
    pq = pytest.importorskip("pyarrow.parquet")
    hepmc = tmp_path / "run.hepmc.gz"
    # Both jets are near leg 1. Its closer jet is softer and at larger absolute eta.
    _write_hepmc(hepmc, (3,), visible_particles=(
        "P 5 211 26 0 5 27 0.14 1 0 0 0 0\n"
        "P 8 211 48 11 0 50 0.14 1 0 0 0 0\n"
    ))
    _write_geometry(tmp_path / "run.hepmc.geometry.csv", _legs(3))
    inclusive, restricted = tmp_path / "inclusive", tmp_path / "restricted"
    options = dict(particles="raw", format="both", jets=True, jet_radius=0.1)
    convert_hepmc_to_tables([hepmc], inclusive, **options)
    convert_hepmc_to_tables([hepmc], restricted, **options, **analysis_cuts)

    baseline = pq.read_table(inclusive / "run.jet_matches.parquet").to_pylist()
    matches = pq.read_table(restricted / "run.jet_matches.parquet").to_pylist()
    jets_all = pq.read_table(restricted / "run.jets_all.parquet").to_pylist()
    jets = pq.read_table(restricted / "run.jets.parquet").to_pylist()
    assert len(jets_all) == 2
    assert [jet["analysis_selected"] for jet in jets_all] == [True, False]
    assert jets == jets_all[:1]
    assert baseline[0]["analysis_selected"] is True
    assert matches[0] == dict(baseline[0], analysis_selected=False)
    assert matches[0]["n_candidates"] == 2 and matches[0]["ambiguous"]
    assert matches[0]["matched"] and matches[0]["jet_rank"] == 2
    assert matches[0]["jet_id"] == jets_all[1]["jet_id"]
    assert matches[0]["delta_r"] == pytest.approx(jets_all[1]["eta"])
    assert not matches[1]["matched"] and not matches[1]["analysis_selected"]

    metadata = json.loads(pq.read_schema(restricted / "run.jet_matches.parquet").metadata[b"jewel_cs"])
    assert metadata["jets"]["matching_phase_space"] == "all positive-pt clustered jets; no pt/eta analysis cuts"
    assert metadata["jets"]["analysis_selection"] == "after_matching"
    with uproot.open(restricted / "run.root") as root:
        assert json.loads(str(root["jewel_cs"])) == metadata
        for name, rows in (("jets_all", jets_all), ("jets", jets), ("jet_matches", matches)):
            assert root[name]["analysis_selected"].array(library="np").tolist() == [
                row["analysis_selected"] for row in rows
            ]


def test_legacy_root_retains_sidecar_with_original_and_ordinal_event_ids(tmp_path):
    pyhepmc = pytest.importorskip("pyhepmc")
    uproot = pytest.importorskip("uproot")
    from hepyy_utils.jewel.convert import convert_hepmc_to_root

    hepmc = tmp_path / "run.hepmc"
    sidecar = tmp_path / "run.hepmc.geometry.csv"
    with pyhepmc.open(hepmc, "w", format="hepmc2") as writer:
        for event_id in (3, 5):
            event = pyhepmc.GenEvent(pyhepmc.Units.GEV, pyhepmc.Units.MM)
            event.event_number = event_id
            event.weights = [1.2345689]
            vertex = pyhepmc.GenVertex()
            for pz in (99.99, -99.99):
                vertex.add_particle_in(pyhepmc.GenParticle((0, 0, pz, 100), 2212, 4))
            for pid, px in ((21, 30), (2, -30)):
                vertex.add_particle_out(pyhepmc.GenParticle((px, 0, 0, 30), pid, 23))
            vertex.add_particle_out(pyhepmc.GenParticle((26, 0, 0, 26.001), 211, 1))
            event.add_vertex(vertex)
            writer.write(event)
    _write_geometry(sidecar, _legs(3) + _legs(5))
    output = tmp_path / "legacy.root"
    convert_hepmc_to_root(hepmc, output, progress=False, max_events=1)

    with uproot.open(output) as root:
        assert root["geometry"]["event_id"].array(library="np").tolist() == [3, 3]
        assert root["geometry"]["eventID"].array(library="np").tolist() == [0, 0]
        assert root["geometry"]["run_id"].array(library="np").tolist() == [RUN_ID] * 2
        assert root["event_info"]["jewel_event"].array(library="np").tolist() == [3]
        assert root["event_info"]["b_fm"].array(library="np").tolist() == [3.5]

    _write_geometry(sidecar, _legs(3))
    bad_output = tmp_path / "legacy-bad.root"
    with pytest.raises(ValueError, match="expected geometry for HepMC event 5"):
        convert_hepmc_to_root(hepmc, bad_output, progress=False, max_events=1)
    assert not bad_output.exists()
