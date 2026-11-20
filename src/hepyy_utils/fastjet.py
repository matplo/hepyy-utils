"""Lazy access to native FastJet through hepyy and cppyy."""

from __future__ import annotations

import sys


def _is_native_fastjet(module):
    try:
        return module.PseudoJet is module.gbl.fastjet.PseudoJet
    except AttributeError:
        return False


def require_fastjet():
    """Load hepyy's cppyy FastJet binding, without a standalone fallback.

    Reuse an already loaded native module. Checking sys.modules rather than
    importing fastjet avoids accidentally loading a separate Python binding.
    Importing this helper alone does not load hepyy or the C++ runtime.
    """
    fastjet = sys.modules.get("fastjet")
    if fastjet is not None:
        if _is_native_fastjet(fastjet):
            return fastjet
        raise RuntimeError(
            "A non-native fastjet module is already imported. Remove the standalone "
            "fastjet Python package and restart Python/the notebook kernel to use "
            "hepyy/cppyy FastJet."
        )

    try:
        import hepyy
    except ImportError as exc:
        raise RuntimeError(
            "Jet finding requires hepyy/cppyy FastJet. Install hepyy with "
            "`python -m pip install 'hepyy-utils[jets]'`, set up the cppyy runtime, "
            "and run `hepyy install fastjet` in the same environment."
        ) from exc
    try:
        hepyy.load("fastjet")
    except Exception as exc:
        raise RuntimeError(
            "Could not load FastJet through hepyy/cppyy. Check the cppyy runtime "
            f"and run `hepyy install fastjet` in this environment. Loader error: {exc}"
        ) from exc

    fastjet = sys.modules.get("fastjet")
    if not _is_native_fastjet(fastjet):
        raise RuntimeError(
            "hepyy did not expose its cppyy FastJet module. Check the cppyy runtime "
            "and FastJet installation (`hepyy install fastjet`). A standalone fastjet "
            "Python package can prevent native loading: remove that package if "
            "installed and restart Python/the notebook kernel."
        )
    return fastjet
