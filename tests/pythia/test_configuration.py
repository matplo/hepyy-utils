import argparse
import sys
import types

import pytest

from hepyy_utils.pythia import (
    PythiaConfig,
    PythiaConfigError,
    PythiaInitializationError,
    add_pythia_args,
    build_settings,
    configure_pythia,
    create_pythia,
)


class FakePythia:
    def __init__(self, init_ok=True):
        self.files = []
        self.strings = []
        self.initialized = False
        self.init_ok = init_ok

    def readFile(self, path):
        self.files.append(path)

    def readString(self, setting):
        self.strings.append(setting)

    def init(self):
        self.initialized = True
        return self.init_ok


def test_build_settings_from_dataclass_pp_hard_qcd():
    settings = build_settings(PythiaConfig.pp_hard_qcd(ecm=13000.0, pthat_min=20.0, seed=7))

    assert "HardQCD:all = on" in settings
    assert "Beams:eCM = 13000" in settings
    assert "PhaseSpace:pTHatMin = 20" in settings
    assert "Random:seed = 7" in settings
    assert "Print:quiet = on" in settings


def test_build_settings_supports_beauty_and_uds_presets():
    beauty_settings = build_settings(PythiaConfig.pp_hard_qcd_beauty(ecm=13000.0, pthat_min=20.0))
    uds_settings = build_settings(PythiaConfig.pp_hard_qcd_uds(ecm=13000.0, pthat_min=20.0))

    assert "HardQCD:hardbbbar = on" in beauty_settings
    assert "HardQCD:all = off" in uds_settings
    assert "HardQCD:gg2qqbar = on" in uds_settings
    assert "HardQCD:qq2qq = on" in uds_settings
    assert "HardQCD:qqbar2qqbarNew = on" in uds_settings
    assert "HardQCD:hardbbbar = on" not in uds_settings


def test_build_settings_supports_light_flavor_aliases():
    uds_settings = build_settings({"process": "uds"})
    light_settings = build_settings({"process": "light"})

    assert "HardQCD:gg2qqbar = on" in uds_settings
    assert "HardQCD:hardbbbar = on" not in uds_settings
    assert "HardQCD:qg2qg = on" in light_settings
    assert "HardQCD:hardbbbar = off" in light_settings


def test_build_settings_from_mapping_supports_raw_options_and_toggles():
    settings = build_settings(
        {
            "process": None,
            "ecm": 5020,
            "no_mpi": True,
            "no_isr": True,
            "no_hadron": True,
            "extra_settings": ["SoftQCD:all = on"],
        }
    )

    assert "HardQCD:all = on" not in settings
    assert "Beams:eCM = 5020" in settings
    assert "PartonLevel:MPI = off" in settings
    assert "PartonLevel:ISR = off" in settings
    assert "HadronLevel:all = off" in settings
    assert settings[-1] == "SoftQCD:all = on"


def test_build_settings_from_legacy_argparse_namespace():
    args = argparse.Namespace(
        py_cmnd=["base.cmnd"],
        py_hardQCD=True,
        py_pthatmin=30.0,
        py_pthatmax=-1,
        py_seed=11,
        py_noMPI=True,
        py_noISR=True,
        py_noHadron=True,
        pythiaopts="Tune:pp_=_14,MultipartonInteractions:pT0Ref_=_2.28",
    )

    config = PythiaConfig.from_namespace(args)
    settings = build_settings(config)

    assert config.cmnd_files == ("base.cmnd",)
    assert "HardQCD:all = on" in settings
    assert "PhaseSpace:pTHatMin = 30" in settings
    assert "PhaseSpace:pTHatMax" not in "\n".join(settings)
    assert "Random:seed = 11" in settings
    assert "PartonLevel:MPI = off" in settings
    assert "PartonLevel:ISR = off" in settings
    assert "HadronLevel:all = off" in settings
    assert settings[-2:] == ["Tune:pp = 14", "MultipartonInteractions:pT0Ref = 2.28"]


def test_build_settings_from_legacy_uds_flag():
    args = argparse.Namespace(py_hardQCDuds=True, process="hard_qcd")

    config = PythiaConfig.from_namespace(args)
    settings = build_settings(config)

    assert config.process == ("hard_qcd_uds",)
    assert "HardQCD:all = off" in settings
    assert "HardQCD:gg2qqbar = on" in settings


def test_configure_pythia_applies_files_before_strings():
    fake = FakePythia()

    settings = configure_pythia(
        fake,
        {
            "cmnd_files": ["base.cmnd"],
            "process": None,
            "extra_settings": ["HardQCD:all = on"],
        },
    )

    assert fake.files == ["base.cmnd"]
    assert fake.strings == settings
    assert settings[-1] == "HardQCD:all = on"


def test_create_pythia_uses_lazy_import(monkeypatch):
    fake_module = types.SimpleNamespace(Pythia=FakePythia)
    monkeypatch.setitem(sys.modules, "pythia8", fake_module)

    pythia = create_pythia({"process": None, "extra_settings": ["HardQCD:all = on"]})

    assert pythia.initialized is True
    assert pythia.strings[-1] == "HardQCD:all = on"


def test_create_pythia_raises_on_init_failure(monkeypatch):
    class FailingPythia(FakePythia):
        def __init__(self):
            super().__init__(init_ok=False)

    monkeypatch.setitem(sys.modules, "pythia8", types.SimpleNamespace(Pythia=FailingPythia))

    with pytest.raises(PythiaInitializationError):
        create_pythia({"process": None})


def test_add_pythia_args_can_feed_create_config():
    parser = argparse.ArgumentParser()
    add_pythia_args(parser)

    args = parser.parse_args(["--py-ecm", "13000", "--py-pthatmin", "20", "--py-noMPI"])
    settings = build_settings(args)

    assert "HardQCD:all = on" in settings
    assert "Beams:eCM = 13000" in settings
    assert "PhaseSpace:pTHatMin = 20" in settings
    assert "PartonLevel:MPI = off" in settings


def test_add_pythia_args_supports_light_flavor_switches():
    parser = argparse.ArgumentParser()
    add_pythia_args(parser)

    args = parser.parse_args(["--py-ecm", "13000", "--py-hardQCDuds"])
    settings = build_settings(args)

    assert "HardQCD:all = off" in settings
    assert "HardQCD:gg2qqbar = on" in settings
    assert "Beams:eCM = 13000" in settings


def test_unknown_process_is_rejected():
    with pytest.raises(PythiaConfigError):
        build_settings({"process": "not-a-process"})
