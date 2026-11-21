import json
from pathlib import Path
import sys

import numpy as np
import pytest
from click.testing import CliRunner

from hepyy_utils.jewel.cli import tables
from hepyy_utils.jewel.tables import Tables, convert_hepmc_to_tables

h5py = pytest.importorskip('h5py')
FIXTURES = Path(__file__).resolve().parents[1] / 'fixtures/jewel_geometry'


@pytest.mark.parametrize('sample', ['vac', 'simple', 'recoils', 'long'])
def test_h5_matches_parquet_and_root(sample, tmp_path, native_fastjet):
    pq = pytest.importorskip('pyarrow.parquet')
    uproot = pytest.importorskip('uproot')
    convert_hepmc_to_tables([FIXTURES / sample / 'events.hepmc.gz'], tmp_path,
                            format='all', particles='both', jets=True, chunk=1, double=True)
    with h5py.File(tmp_path / 'events.h5') as h5, uproot.open(tmp_path / 'events.root') as root:
        assert h5.attrs['schema'] == 'hepyy_utils.jewel.tables.v1'
        assert json.loads(h5.attrs['jewel_cs']) == json.loads(str(root['jewel_cs']))
        assert set(h5) == {p.name.split('.')[1] for p in tmp_path.glob('events.*.parquet')}
        for name, group in h5.items():
            parquet = pq.read_table(tmp_path / f'events.{name}.parquet')
            assert set(group) == set(parquet.column_names)
            for key, dataset in group.items():
                actual = dataset.asstr()[:] if h5py.check_string_dtype(dataset.dtype) else dataset[:]
                expected = np.array(parquet[key].to_pylist())
                if actual.dtype.kind in 'f':
                    np.testing.assert_allclose(actual, expected, rtol=0, atol=0, equal_nan=True)
                else:
                    np.testing.assert_array_equal(actual, expected)
                assert len(actual) == root[name].num_entries
                if key in ('matched', 'analysis_selected', 'ambiguous'):
                    assert dataset.dtype == np.dtype(bool)


def test_h5_appends_chunks_and_keeps_empty_table(tmp_path):
    writer = Tables(str(tmp_path / 'chunks'), 'h5', {'test': 'μ'})
    try:
        writer.write('empty', {'id': np.array([], dtype=np.int64), 'run': np.array([], dtype=str)})
        for ids, labels in [([1, 2], ['μ', 'a']), ([3], ['longer string'])]:
            writer.write('events', {'id': np.array(ids, dtype=np.int64), 'run': np.array(labels),
                                    'pt': np.array(ids, dtype=np.float32)})
    finally:
        writer.close()
    with h5py.File(tmp_path / 'chunks.h5') as h5:
        assert h5['events/id'][:].tolist() == [1, 2, 3]
        assert h5['events/run'].asstr()[:].tolist() == ['μ', 'a', 'longer string']
        assert h5['events/pt'].dtype == np.dtype('float32')
        assert h5['empty/id'].shape == (0,)
        assert h5['empty/run'].shape == (0,)
        assert json.loads(h5.attrs['jewel_cs']) == {'test': 'μ'}


def test_h5_cli_without_parquet_or_native_dependencies(tmp_path, monkeypatch):
    for name in ('pyarrow', 'hepyy', 'cppyy', 'fastjet'):
        monkeypatch.setitem(sys.modules, name, None)
    result = CliRunner().invoke(tables, [str(FIXTURES / 'simple/events.hepmc.gz'),
        '--outdir', str(tmp_path), '--format', 'h5', '--particles', 'raw'], catch_exceptions=False)
    assert result.exit_code == 0
    assert {p.suffix for p in tmp_path.iterdir()} == {'.h5'}
    with h5py.File(tmp_path / 'events.h5') as h5:
        assert len(h5['events/event_id']) > 0
        assert 'geometry' in h5


def test_h5_dependency_error_before_creating_output(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, 'h5py', None)
    output = tmp_path / 'absent'
    with pytest.raises(RuntimeError, match='h5py'):
        convert_hepmc_to_tables([], output, format='h5')
    assert not output.exists()


def test_h5_invalid_sidecar_preserves_existing_output(tmp_path):
    source = FIXTURES / 'simple/events.hepmc.gz'
    sidecar = tmp_path / 'wrong.csv'
    sidecar.write_text((FIXTURES / 'vac/events.hepmc.geometry.csv').read_text())
    output = tmp_path / 'events.h5'
    output.write_bytes(b'existing output')
    with pytest.raises(ValueError):
        convert_hepmc_to_tables([source], tmp_path, format='h5', geometry=sidecar)
    assert output.read_bytes() == b'existing output'
