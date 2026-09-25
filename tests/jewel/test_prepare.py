from pathlib import Path

import yaml
from click.testing import CliRunner

from hepyy_utils.jewel.cli import prepare
from hepyy_utils.jewel.workflow import prepare_runs


def test_prepare_runs_writes_namespaced_medium_and_vacuum_dirs(tmp_path):
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


def test_prepare_cli_creates_vacuum_only(tmp_path):
    result = CliRunner().invoke(
        prepare,
        ["--samples", "vacuum", "--tag", "cli", "--out-dir", str(tmp_path), "--nevents-vacuum", "2"],
    )

    assert result.exit_code == 0, result.output
    assert (tmp_path / "cli" / "jewel_vac" / "params.dat").is_file()
    assert not (tmp_path / "cli" / "jewel_med").exists()
    assert "NEVENT 2" in (tmp_path / "cli" / "jewel_vac" / "params.dat").read_text()


def test_console_entry_names_are_jewel_prefixed():
    pyproject = Path(__file__).parents[2] / "pyproject.toml"
    text = pyproject.read_text()

    assert "jewel_prepare" in text
    assert "jewel_run" in text
    assert "jewel_convert" in text
    assert "jewel_pipeline" in text
