from importlib.util import find_spec

import pytest

from hepyy_utils.fastjet import require_fastjet


@pytest.fixture(scope="session")
def native_fastjet():
    if find_spec("hepyy") is None:
        pytest.skip("The hepyy package is unavailable.")
    from hepyy.exceptions import PackageNotInstalledError

    try:
        return require_fastjet()
    except RuntimeError as error:
        cause = error.__cause__
        if isinstance(cause, PackageNotInstalledError):
            pytest.skip("Native FastJet is unavailable. Run hepyy install fastjet.")
        while cause is not None:
            if isinstance(cause, ModuleNotFoundError) and cause.name == "cppyy":
                pytest.skip("The cppyy runtime is unavailable.")
            cause = cause.__cause__ or cause.__context__
        raise
