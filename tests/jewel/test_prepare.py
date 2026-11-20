from pathlib import Path
import warnings

import pytest
import yaml
from click.testing import CliRunner

from hepyy_utils.jewel.cli import prepare
from hepyy_utils.jewel.geometry import FIELDS, hepmc_digest
from hepyy_utils.jewel.workflow import prepare_runs, run_manifest


def _make_executable(directory: Path, name: str, body="exit 0\n") -> Path:
    path = directory / name
    path.write_text("#!/bin/sh\n" + body)
    path.chmod(path.stat().st_mode | 0o111)
    return path


def test_prepare_runs_writes_namespaced_medium_and_vacuum_dirs(tmp_path, monkeypatch):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    _make_executable(bindir, "jewel-2.6.0-simple")
    _make_executable(bindir, "jewel-2.6.0-vac")
    monkeypatch.setenv("PATH", str(bindir))
    prepared = prepare_runs(
        samples="both",
        tag="smoke",
        out_dir=tmp_path,
        nevents=3,
        ptmin="100.",
        etamax="2.5",
        job_id=7,
    )

    assert [item.sample for item in prepared] == ["jewel_med", "jewel_vac"]
    for item in prepared:
        assert item.params_path.is_file()
        assert item.manifest_path.is_file()
        params = item.params_path.read_text()
        assert "NEVENT 3" in params
        assert "PTMIN 100." in params
        assert "ETAMAX 2.5" in params
        assert "NJOB 7" in params
        manifest = yaml.safe_load(item.manifest_path.read_text())
        assert manifest["hepmc"] == f"events/{item.sample}_smoke.hepmc"
        assert manifest["root"] == f"roots/{item.sample}_smoke.root"
        assert "geometry" not in manifest
        assert item.geometry_path is None

    assert (tmp_path / "smoke" / "jewel_med" / "medium.params.dat").is_file()


def test_prepare_cli_creates_vacuum_only(tmp_path, monkeypatch):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    _make_executable(bindir, "jewel-2.6.0-vac")
    monkeypatch.setenv("PATH", str(bindir))
    result = CliRunner().invoke(
        prepare,
        ["--samples", "vacuum", "--tag", "cli", "--out-dir", str(tmp_path), "--nevents-vacuum", "2"],
    )

    assert result.exit_code == 0, result.output
    assert (tmp_path / "cli" / "jewel_vac" / "params.dat").is_file()
    assert not (tmp_path / "cli" / "jewel_med").exists()
    assert "NEVENT 2" in (tmp_path / "cli" / "jewel_vac" / "params.dat").read_text()


def test_prepare_runs_keeps_requested_executable_when_present(tmp_path, monkeypatch):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    _make_executable(bindir, "jewel-2.4.0-simple")
    _make_executable(bindir, "jewel-2.9.0-simple")
    monkeypatch.setenv("PATH", str(bindir))

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        prepared = prepare_runs(samples="medium", tag="direct", out_dir=tmp_path, medium_bin="jewel-2.4.0-simple")

    assert not caught
    manifest = yaml.safe_load(prepared[0].manifest_path.read_text())
    assert manifest["executable"] == str((bindir / "jewel-2.4.0-simple").resolve())


def test_prepare_runs_falls_back_to_latest_matching_executable(tmp_path, monkeypatch):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    _make_executable(bindir, "jewel-2.4.1-vac")
    _make_executable(bindir, "jewel-2.10.0-vac")
    monkeypatch.setenv("PATH", str(bindir))

    with pytest.warns(
        RuntimeWarning,
        match=r"requested JEWEL executable 'jewel-2\.4\.0-vac' was not found; using 'jewel-2\.10\.0-vac' from PATH",
    ):
        prepared = prepare_runs(samples="vacuum", tag="fallback", out_dir=tmp_path, vacuum_bin="jewel-2.4.0-vac")

    manifest = yaml.safe_load(prepared[0].manifest_path.read_text())
    assert manifest["executable"] == str((bindir / "jewel-2.10.0-vac").resolve())


def test_prepare_runs_raises_when_no_matching_executable_exists(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", "")

    with pytest.raises(FileNotFoundError, match=r"jewel-2\.4\.0-vac"):
        prepare_runs(samples="vacuum", tag="missing", out_dir=tmp_path, vacuum_bin="jewel-2.4.0-vac")


def test_geometry_requires_the_requested_executable(tmp_path, monkeypatch):
    _make_executable(tmp_path, "jewel-2.6.0-vac")
    monkeypatch.setenv("PATH", str(tmp_path))

    with pytest.raises(FileNotFoundError, match=r"jewel-2\.6\.0-custom-vac.*geometry"):
        prepare_runs(samples="vacuum", tag="missing", out_dir=tmp_path, geometry=True,
                     vacuum_bin="jewel-2.6.0-custom-vac")
    assert not (tmp_path / "missing").exists()


@pytest.mark.parametrize("step", [0.0, -0.1, float("nan"), float("inf")])
def test_geometry_prepare_rejects_invalid_step(tmp_path, step):
    with pytest.raises(ValueError, match="step must be positive and finite"):
        prepare_runs(samples="vacuum", tag="invalid", out_dir=tmp_path, geometry=True, geometry_step_fm=step)


def test_geometry_manifests_namespace_sidecars_and_run_ids(tmp_path):
    medium = _make_executable(tmp_path, "jewel-2.6.0-custom-simple")
    vacuum = _make_executable(tmp_path, "jewel-2.6.0-custom-vac")
    prepared = prepare_runs(samples="both", tag="geo", out_dir=tmp_path, geometry=True,
                            medium_bin=str(medium), vacuum_bin=str(vacuum))
    ids = set()
    for item in prepared:
        settings = yaml.safe_load(item.manifest_path.read_text())["geometry"]
        assert settings["scheme"] == "jewel_geometry_v1"
        assert settings["step_fm"] == 0.02
        assert settings["path"] == f"events/{item.sample}_geo.hepmc.geometry.csv"
        assert item.geometry_path == item.run_dir / settings["path"]
        assert not item.geometry_path.exists()
        ids.add(settings["run_id"])
    assert len(ids) == 2


def _fake_geometry_body(*, run_id='"$JEWEL_GEOMETRY_RUN_ID"', write_sidecar=True, extra_hepmc_event=False):
    hepmc = "events/jewel_vac_geo.hepmc"
    body = f"printf '%s\\n' 'E 1 -1 30 0 0 0 0 1 1 2 0 1 1' > {hepmc}\n"
    if extra_hepmc_event:
        body += f"printf '%s\\n' 'E 2 -1 30 0 0 0 0 1 1 2 0 1 1' >> {hepmc}\n"
    if write_sidecar:
        body += rf"""printf '# schema=jewel_geometry_v1\n# axis=shower_start\n# medium=vac\n# run_id=%s\n# step_fm=%s\n' {run_id} "$JEWEL_GEOMETRY_STEP_FM" > "$JEWEL_GEOMETRY_FILE"
printf '%s\n' '{','.join(FIELDS)}' \
  '1,1,21,1,0,0,0,0,0,0,30,0,0,30,28,0,0,28,0,0,0,0' \
  '1,2,2,1,0,0,0,0,0,0,-30,0,0,30,-28,0,0,28,0,0,0,0' >> "$JEWEL_GEOMETRY_FILE"
"""
    return body


def _prepare_fake_geometry(tmp_path, body):
    executable = _make_executable(tmp_path, "jewel-2.6.0-custom-vac", body)
    return prepare_runs(samples="vacuum", tag="geo", out_dir=tmp_path, geometry=True,
                        vacuum_bin=str(executable), geometry_step_fm=0.05)[0]


def test_run_geometry_passes_per_run_environment_and_refuses_stale_sidecar(tmp_path, monkeypatch):
    run = _prepare_fake_geometry(tmp_path, _fake_geometry_body())
    monkeypatch.setenv("JEWEL_GEOMETRY_FILE", str(tmp_path / "inherited.csv"))

    result = run_manifest(run.manifest_path)

    assert result["geometry"] == str(run.geometry_path)
    assert run.geometry_path.read_text().startswith(f"# hepmc_sha256={hepmc_digest(run.hepmc_path)}\n")
    assert not (tmp_path / "inherited.csv").exists()
    first_bytes = run.geometry_path.read_bytes()
    with pytest.raises(FileExistsError, match="geometry output already exists"):
        run_manifest(run.manifest_path)
    assert run.geometry_path.read_bytes() == first_bytes


@pytest.mark.parametrize(("body", "error"), [
    (_fake_geometry_body(write_sidecar=False), "geometry output missing"),
    (_fake_geometry_body(run_id="wrong"), "run ID differs"),
    (_fake_geometry_body(extra_hepmc_event=True), "expected geometry for HepMC event 2"),
])
def test_run_geometry_rejects_missing_or_mismatched_output(tmp_path, body, error):
    run = _prepare_fake_geometry(tmp_path, body)

    with pytest.raises(RuntimeError, match=error):
        run_manifest(run.manifest_path, check_output=False)


def test_ordinary_run_does_not_inherit_geometry_settings(tmp_path, monkeypatch):
    executable = _make_executable(
        tmp_path, "jewel-2.6.0-custom-vac",
        'test -z "${JEWEL_GEOMETRY_FILE:-}${JEWEL_GEOMETRY_RUN_ID:-}${JEWEL_GEOMETRY_STEP_FM:-}"\n',
    )
    run = prepare_runs(samples="vacuum", tag="plain", out_dir=tmp_path, vacuum_bin=str(executable))[0]
    monkeypatch.setenv("JEWEL_GEOMETRY_FILE", "inherited.csv")
    monkeypatch.setenv("JEWEL_GEOMETRY_RUN_ID", "inherited")
    monkeypatch.setenv("JEWEL_GEOMETRY_STEP_FM", "1")

    assert "geometry" not in run_manifest(run.manifest_path, check_output=False)


def test_console_entry_names_are_jewel_prefixed():
    pyproject = Path(__file__).parents[2] / "pyproject.toml"
    text = pyproject.read_text()

    assert "jewel_prepare" in text
    assert "jewel_run" in text
    assert "jewel_convert" in text
    assert "jewel_pipeline" in text
