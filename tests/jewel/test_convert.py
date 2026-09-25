import numpy as np
import pytest

from hepyy_utils.jewel.convert import RootBuffers, _write_root, const_subtraction_event


def test_write_root_creates_tracks_tree(tmp_path):
    uproot = pytest.importorskip("uproot")
    buffers = RootBuffers()
    buffers.event_id.extend([0, 0])
    buffers.label.extend([211, -211])
    buffers.px.extend([1.0, -1.0])
    buffers.py.extend([0.0, 0.0])
    buffers.pz.extend([0.5, -0.5])
    buffers.energy.extend([1.2, 1.2])
    buffers.info_event_id.append(0)
    buffers.weight.append(1.0)
    buffers.xsec.append(2.0)

    output = tmp_path / "events.root"
    _write_root(output, buffers)

    with uproot.open(output) as root_file:
        arrays = root_file["tracks"].arrays(library="np")
        names = arrays.keys() if hasattr(arrays, "keys") else arrays.dtype.names
        assert set(names) == {"eventID", "label", "px", "py", "pz", "energy"}
        assert arrays["eventID"].tolist() == [0, 0]
        assert arrays["label"].tolist() == [211, -211]
        info = root_file["event_info"].arrays(library="np")
        assert info["xsec"].tolist() == [2.0]


def test_const_subtraction_handles_empty_ghosts():
    parts = np.array(
        [(1.0, 0.0, 0.0, 0.0, 211, 0)],
        dtype=[
            ("pt", float),
            ("mdelta", float),
            ("phi", float),
            ("y", float),
            ("pdg_id", int),
            ("list_id", int),
        ],
    )
    ghosts = np.array([], dtype=parts.dtype)

    assert const_subtraction_event(parts, ghosts) == [(1.0, 0.0, 0.0, 0.0, 211, 0)]
