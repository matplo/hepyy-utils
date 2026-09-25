from pathlib import Path
import warnings

import pytest
import yaml
from click.testing import CliRunner

from hepyy_utils.jewel.cli import prepare
from hepyy_utils.jewel.workflow import prepare_runs


def _make_executable(directory: Path, name: str) -> Path:
    path = directory / name
    path.write_text("#!/bin/sh\nexit 0\n")
    path.chmod(path.stat().st_mode | 0o111)
    return path


def test_prepare_runs_writes_namespaced_medium_and_vacuum_dirs(tmp_path, monkeypatch):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    _make_executable(bindir, "jewel-2.4.0-simple")
    _make_executable(bindir, "jewel-2.4.0-vac")
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

    assert (tmp_path / "smoke" / "jewel_med" / "medium.params.dat").is_file()


def test_prepare_cli_creates_vacuum_only(tmp_path, monkeypatch):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    _make_executable(bindir, "jewel-2.4.0-vac")
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
    assert manifest["executable"] == "jewel-2.4.0-simple"


def test_prepare_runs_falls_back_to_latest_matching_executable(tmp_path, monkeypatch):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    _make_executable(bindir, "jewel-2.4.1-vac")
    _make_executable(bindir, "jewel-2.10.0-vac")
    monkeypatch.setenv("PATH", str(bindir))

    with pytest.warns(RuntimeWarning, match=r"jewel-2\.4\.0-vac.*jewel-2\.10\.0-vac"):
        prepared = prepare_runs(samples="vacuum", tag="fallback", out_dir=tmp_path)

    manifest = yaml.safe_load(prepared[0].manifest_path.read_text())
    assert manifest["executable"] == "jewel-2.10.0-vac"


def test_prepare_runs_raises_when_no_matching_executable_exists(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", "")

    with pytest.raises(FileNotFoundError, match=r"jewel-2\.4\.0-vac"):
        prepare_runs(samples="vacuum", tag="missing", out_dir=tmp_path)


def test_console_entry_names_are_jewel_prefixed():
    pyproject = Path(__file__).parents[2] / "pyproject.toml"
    text = pyproject.read_text()

    assert "jewel_prepare" in text
    assert "jewel_run" in text
    assert "jewel_convert" in text
    assert "jewel_pipeline" in text
