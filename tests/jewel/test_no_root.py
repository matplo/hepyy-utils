from pathlib import Path


def test_jewel_package_does_not_import_root():
    src_dir = Path(__file__).parents[2] / "src" / "hepyy_utils" / "jewel"
    for path in src_dir.rglob("*.py"):
        text = path.read_text()
        assert "import ROOT" not in text
        assert "from ROOT" not in text
