"""Library-first helpers for configuring and initializing Pythia8."""

from __future__ import annotations

import argparse
import importlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


class PythiaConfigError(ValueError):
    """Raised when a Pythia configuration cannot be normalized."""


class PythiaInitializationError(RuntimeError):
    """Raised when ``pythia.init()`` returns false."""


_MISSING = object()

_QUIET_SETTINGS = (
    "Next:numberCount = 0",
    "Next:numberShowEvent = 0",
    "Next:numberShowInfo = 0",
    "Next:numberShowProcess = 0",
    "Print:quiet = on",
)

_PROCESS_SETTINGS = {
    "hard_qcd": ("HardQCD:all = on",),
    "hard_qcd_charm": ("HardQCD:hardccbar = on",),
    "hard_qcd_beauty": ("HardQCD:hardbbbar = on",),
    "hard_qcd_lf": (
        "HardQCD:all = off",
        "HardQCD:gg2gg = on",
        "HardQCD:qg2qg = on",
        "HardQCD:qqbar2gg = on",
        "HardQCD:gg2qqbar = on",
        "HardQCD:qq2qq = on",
        "HardQCD:qqbar2qqbarNew = on",
        "HardQCD:hardccbar = off",
        "HardQCD:hardbbbar = off",
    ),
    "hard_qcd_gluons": (
        "HardQCD:all = off",
        "HardQCD:gg2gg = on",
        "HardQCD:qqbar2gg = on",
    ),
    "hard_qcd_quarks": (
        "HardQCD:all = off",
        "HardQCD:gg2qqbar = on",
        "HardQCD:qq2qq = on",
        "HardQCD:qqbar2qqbarNew = on",
        "HardQCD:hardccbar = on",
        "HardQCD:hardbbbar = on",
    ),
    "hard_qcd_uds": (
        "HardQCD:all = off",
        "HardQCD:gg2qqbar = on",
        "HardQCD:qq2qq = on",
        "HardQCD:qqbar2qqbarNew = on",
    ),
    "prompt_photon": ("PromptPhoton:all = on",),
    "soft_qcd": ("SoftQCD:all = on",),
    "minbias": ("SoftQCD:all = on",),
    "inelastic": (
        "HardQCD:all = off",
        "PromptPhoton:all = off",
        "SoftQCD:all = off",
        "SoftQCD:inelastic = on",
    ),
    "non_diffractive": (
        "HardQCD:all = off",
        "PromptPhoton:all = off",
        "SoftQCD:all = off",
        "SoftQCD:nonDiffractive = on",
    ),
    "elastic": (
        "HardQCD:all = off",
        "PromptPhoton:all = off",
        "SoftQCD:all = off",
        "SoftQCD:elastic = on",
    ),
    "diffractive": (
        "HardQCD:all = off",
        "PromptPhoton:all = off",
        "SoftQCD:all = off",
        "SoftQCD:singleDiffractive = on",
        "SoftQCD:doubleDiffractive = on",
        "SoftQCD:centralDiffractive = on",
    ),
}

_PROCESS_ALIASES = {
    "hardqcd": "hard_qcd",
    "hard-qcd": "hard_qcd",
    "hard_qcd": "hard_qcd",
    "hardqcdcharm": "hard_qcd_charm",
    "hard-qcd-charm": "hard_qcd_charm",
    "hard_qcd_charm": "hard_qcd_charm",
    "charm": "hard_qcd_charm",
    "hardqcdbeauty": "hard_qcd_beauty",
    "hard-qcd-beauty": "hard_qcd_beauty",
    "hard_qcd_beauty": "hard_qcd_beauty",
    "beauty": "hard_qcd_beauty",
    "bottom": "hard_qcd_beauty",
    "hardqcdlf": "hard_qcd_lf",
    "hard-qcd-lf": "hard_qcd_lf",
    "hard_qcd_lf": "hard_qcd_lf",
    "lf": "hard_qcd_lf",
    "light": "hard_qcd_lf",
    "hardqcdgluons": "hard_qcd_gluons",
    "hard-qcd-gluons": "hard_qcd_gluons",
    "hard_qcd_gluons": "hard_qcd_gluons",
    "gluons": "hard_qcd_gluons",
    "gluon": "hard_qcd_gluons",
    "hardqcdquarks": "hard_qcd_quarks",
    "hard-qcd-quarks": "hard_qcd_quarks",
    "hard_qcd_quarks": "hard_qcd_quarks",
    "quarks": "hard_qcd_quarks",
    "quark": "hard_qcd_quarks",
    "hardqcduds": "hard_qcd_uds",
    "hard-qcd-uds": "hard_qcd_uds",
    "hard_qcd_uds": "hard_qcd_uds",
    "uds": "hard_qcd_uds",
    "promptphoton": "prompt_photon",
    "prompt-photon": "prompt_photon",
    "prompt_photon": "prompt_photon",
    "softqcd": "soft_qcd",
    "soft-qcd": "soft_qcd",
    "soft_qcd": "soft_qcd",
    "minbias": "minbias",
    "minimum_bias": "minbias",
    "inelastic": "inelastic",
    "inel": "inelastic",
    "non-diffractive": "non_diffractive",
    "non_diffractive": "non_diffractive",
    "nd": "non_diffractive",
    "elastic": "elastic",
    "el": "elastic",
    "diffractive": "diffractive",
    "diff": "diffractive",
    "none": "",
    "off": "",
}


@dataclass(frozen=True)
class PythiaConfig:
    """Common Pythia8 settings with raw-string escape hatches.

    ``process`` may be a string, a sequence of process names, or ``None``.
    ``extra_settings`` are applied last so callers can override defaults.
    """

    ecm: float | None = None
    process: str | Sequence[str] | None = "hard_qcd"
    pthat_min: float | None = None
    pthat_max: float | None = None
    seed: int | None = None
    time_seed: bool = False
    quiet: bool = True
    tune: str | int | None = None
    isr: bool = True
    mpi: bool = True
    hadronization: bool = True
    cmnd_files: tuple[str, ...] = field(default_factory=tuple)
    extra_settings: tuple[str, ...] = field(default_factory=tuple)

    @classmethod
    def pp_hard_qcd(
        cls,
        *,
        ecm: float = 13000.0,
        pthat_min: float | None = None,
        pthat_max: float | None = None,
        **kwargs: Any,
    ) -> "PythiaConfig":
        """Create a pp hard-QCD configuration."""

        return cls(
            ecm=ecm,
            process="hard_qcd",
            pthat_min=pthat_min,
            pthat_max=pthat_max,
            **kwargs,
        )

    @classmethod
    def pp_hard_qcd_charm(
        cls,
        *,
        ecm: float = 13000.0,
        pthat_min: float | None = None,
        pthat_max: float | None = None,
        **kwargs: Any,
    ) -> "PythiaConfig":
        """Create a pp hard-QCD charm configuration."""

        return cls(
            ecm=ecm,
            process="hard_qcd_charm",
            pthat_min=pthat_min,
            pthat_max=pthat_max,
            **kwargs,
        )

    @classmethod
    def pp_hard_qcd_beauty(
        cls,
        *,
        ecm: float = 13000.0,
        pthat_min: float | None = None,
        pthat_max: float | None = None,
        **kwargs: Any,
    ) -> "PythiaConfig":
        """Create a pp hard-QCD beauty configuration."""

        return cls(
            ecm=ecm,
            process="hard_qcd_beauty",
            pthat_min=pthat_min,
            pthat_max=pthat_max,
            **kwargs,
        )

    @classmethod
    def pp_hard_qcd_lf(
        cls,
        *,
        ecm: float = 13000.0,
        pthat_min: float | None = None,
        pthat_max: float | None = None,
        **kwargs: Any,
    ) -> "PythiaConfig":
        """Create a pp hard-QCD light-flavor plus gluon configuration."""

        return cls(
            ecm=ecm,
            process="hard_qcd_lf",
            pthat_min=pthat_min,
            pthat_max=pthat_max,
            **kwargs,
        )

    @classmethod
    def pp_hard_qcd_gluons(
        cls,
        *,
        ecm: float = 13000.0,
        pthat_min: float | None = None,
        pthat_max: float | None = None,
        **kwargs: Any,
    ) -> "PythiaConfig":
        """Create a pp hard-QCD gluon-channel configuration."""

        return cls(
            ecm=ecm,
            process="hard_qcd_gluons",
            pthat_min=pthat_min,
            pthat_max=pthat_max,
            **kwargs,
        )

    @classmethod
    def pp_hard_qcd_quarks(
        cls,
        *,
        ecm: float = 13000.0,
        pthat_min: float | None = None,
        pthat_max: float | None = None,
        **kwargs: Any,
    ) -> "PythiaConfig":
        """Create a pp hard-QCD quark-channel configuration including c/b."""

        return cls(
            ecm=ecm,
            process="hard_qcd_quarks",
            pthat_min=pthat_min,
            pthat_max=pthat_max,
            **kwargs,
        )

    @classmethod
    def pp_hard_qcd_uds(
        cls,
        *,
        ecm: float = 13000.0,
        pthat_min: float | None = None,
        pthat_max: float | None = None,
        **kwargs: Any,
    ) -> "PythiaConfig":
        """Create a pp hard-QCD uds-channel configuration."""

        return cls(
            ecm=ecm,
            process="hard_qcd_uds",
            pthat_min=pthat_min,
            pthat_max=pthat_max,
            **kwargs,
        )

    @classmethod
    def from_namespace(cls, args: argparse.Namespace) -> "PythiaConfig":
        """Create a config from an ``argparse.Namespace``."""

        return cls.from_mapping(vars(args))

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "PythiaConfig":
        """Create a config from canonical or legacy ``py_*`` option names."""

        cmnd_files = _paths_tuple(_lookup(data, "cmnd_files", "py_cmnd", "cmnd"))
        extra_settings = _settings_tuple(_lookup(data, "extra_settings", "settings", "py_settings"))
        extra_settings += _settings_tuple(_lookup(data, "pythiaopts", "pythia_opts"), comma_encoded=True)

        process_value = _lookup(data, "process", "processes")
        legacy_processes = _legacy_processes(data)
        if process_value is _MISSING:
            if legacy_processes:
                process: str | Sequence[str] | None = legacy_processes
            elif cmnd_files or _settings_tuple(_lookup(data, "pythiaopts", "pythia_opts"), comma_encoded=True):
                process = None
            else:
                process = "hard_qcd"
        elif legacy_processes and _normalize_process_value(process_value) == "hard_qcd":
            process = legacy_processes
        else:
            process = _normalize_process_value(process_value)

        isr = _enabled_from_negative_flags(
            data,
            enabled_key="isr",
            disabled_keys=("no_isr", "py_noISR", "py_no_isr"),
            default=True,
        )
        mpi = _enabled_from_negative_flags(
            data,
            enabled_key="mpi",
            disabled_keys=("no_mpi", "py_noMPI", "py_no_mpi"),
            default=True,
        )
        if _as_bool(_lookup(data, "no_underlying_event", "py_noue", default=False)):
            isr = False
            mpi = False

        hadronization = _enabled_from_negative_flags(
            data,
            enabled_key="hadronization",
            disabled_keys=("no_hadron", "py_noHadron", "py_no_hadron", "py_hadronization_off"),
            default=True,
        )

        tune = _lookup(data, "tune", default=None)
        if _as_bool(_lookup(data, "py_monash", "monash", default=False)):
            tune = "monash"

        return cls(
            ecm=_positive_float_or_none(_lookup(data, "ecm", "py_ecm", "py_ecms", default=None)),
            process=process,
            pthat_min=_positive_float_or_none(
                _lookup(data, "pthat_min", "py_pthatmin", "py_pthat_min", default=None)
            ),
            pthat_max=_positive_float_or_none(
                _lookup(data, "pthat_max", "py_pthatmax", "py_pthat_max", default=None)
            ),
            seed=_nonnegative_int_or_none(_lookup(data, "seed", "py_seed", default=None)),
            time_seed=_as_bool(_lookup(data, "time_seed", "py_time_seed", default=False)),
            quiet=_as_bool(_lookup(data, "quiet", "py_quiet", default=True)),
            tune=tune,
            isr=isr,
            mpi=mpi,
            hadronization=hadronization,
            cmnd_files=cmnd_files,
            extra_settings=extra_settings,
        )


def build_settings(config: PythiaConfig | Mapping[str, Any] | argparse.Namespace | None = None) -> list[str]:
    """Return Pythia ``readString`` settings for the supplied configuration."""

    cfg = normalize_config(config)
    settings: list[str] = []

    for process in _process_names(cfg.process):
        settings.extend(_PROCESS_SETTINGS[process])

    if cfg.ecm is not None:
        settings.append(f"Beams:eCM = {_format_number(cfg.ecm)}")
    if cfg.pthat_min is not None:
        settings.append(f"PhaseSpace:pTHatMin = {_format_number(cfg.pthat_min)}")
    if cfg.pthat_max is not None:
        settings.append(f"PhaseSpace:pTHatMax = {_format_number(cfg.pthat_max)}")

    if cfg.tune is not None:
        if str(cfg.tune).lower() == "monash":
            settings.append("Tune:pp = 14")
        else:
            settings.append(f"Tune:pp = {cfg.tune}")

    if cfg.time_seed:
        settings.extend(("Random:setSeed = on", "Random:seed = 0"))
    elif cfg.seed is not None:
        settings.extend(("Random:setSeed = on", f"Random:seed = {cfg.seed}"))

    if not cfg.isr:
        settings.append("PartonLevel:ISR = off")
    if not cfg.mpi:
        settings.append("PartonLevel:MPI = off")
    if not cfg.hadronization:
        settings.append("HadronLevel:all = off")

    if cfg.quiet:
        settings.extend(_QUIET_SETTINGS)

    settings.extend(cfg.extra_settings)
    return [setting for setting in settings if setting]


def configure_pythia(
    pythia: Any,
    config: PythiaConfig | Mapping[str, Any] | argparse.Namespace | None = None,
) -> list[str]:
    """Apply command files and settings to an existing ``pythia8.Pythia`` object."""

    cfg = normalize_config(config)
    for cmnd_file in cfg.cmnd_files:
        pythia.readFile(str(cmnd_file))

    settings = build_settings(cfg)
    for setting in settings:
        pythia.readString(setting)
    return settings


def create_pythia(
    config: PythiaConfig | Mapping[str, Any] | argparse.Namespace | None = None,
    *,
    init: bool = True,
    load: bool = False,
    verbose: bool = False,
) -> Any:
    """Create, configure, and optionally initialize a ``pythia8.Pythia`` object.

    Set ``load=True`` to call ``heppyyier.load("pythia8")`` before importing
    the ``pythia8`` module. The default assumes module loading or an earlier
    ``heppyyier.load("pythia8")`` already made it importable.
    """

    if load:
        try:
            import heppyyier
        except ImportError as exc:
            raise ImportError("load=True requires the heppyyier Python package") from exc
        heppyyier.load("pythia8")

    try:
        pythia8 = importlib.import_module("pythia8")
    except ImportError as exc:
        raise ImportError(
            "pythia8 is not importable. Load it first with a module command, "
            "call heppyyier.load('pythia8'), or pass load=True."
        ) from exc

    pythia = pythia8.Pythia()
    configure_pythia(pythia, config)
    if init and not pythia.init():
        if verbose:
            settings = getattr(pythia, "settings", None)
            list_changed = getattr(settings, "listChanged", None)
            if callable(list_changed):
                list_changed()
        raise PythiaInitializationError("pythia.init() failed")
    return pythia


def add_pythia_args(parser: argparse.ArgumentParser, prefix: str = "py") -> argparse.ArgumentParser:
    """Add common Pythia options to an ``argparse`` parser.

    The default flags are compatible with the historical ``--py-*`` pattern,
    while destinations use canonical names understood by ``PythiaConfig``.
    """

    flag_prefix = f"{prefix}-" if prefix else ""
    parser.add_argument(f"--{flag_prefix}ecm", dest="ecm", default=None, type=float, help="Pythia Beams:eCM in GeV.")
    parser.add_argument(
        f"--{flag_prefix}pthatmin",
        f"--{flag_prefix}pthat-min",
        dest="pthat_min",
        default=None,
        type=float,
        help="Pythia PhaseSpace:pTHatMin.",
    )
    parser.add_argument(
        f"--{flag_prefix}pthatmax",
        f"--{flag_prefix}pthat-max",
        dest="pthat_max",
        default=None,
        type=float,
        help="Pythia PhaseSpace:pTHatMax.",
    )
    parser.add_argument(f"--{flag_prefix}seed", dest="seed", default=None, type=int, help="Fixed Pythia random seed.")
    parser.add_argument(
        f"--{flag_prefix}time-seed",
        dest="time_seed",
        default=False,
        action="store_true",
        help="Use Pythia's time-dependent seed.",
    )
    parser.add_argument(
        f"--{flag_prefix}process",
        dest="process",
        default="hard_qcd",
        help=(
            "Process preset: hard_qcd, hard_qcd_charm, hard_qcd_beauty, hard_qcd_lf, "
            "hard_qcd_gluons, hard_qcd_quarks, hard_qcd_uds, minbias, inelastic, "
            "non_diffractive, prompt_photon, or none."
        ),
    )
    parser.add_argument(
        f"--{flag_prefix}hardQCD",
        f"--{flag_prefix}hard-qcd",
        dest="hard_qcd",
        default=False,
        action="store_true",
        help="Enable HardQCD:all.",
    )
    parser.add_argument(
        f"--{flag_prefix}hardQCDcharm",
        f"--{flag_prefix}hard-qcd-charm",
        dest="hard_qcd_charm",
        default=False,
        action="store_true",
        help="Enable HardQCD:hardccbar.",
    )
    parser.add_argument(
        f"--{flag_prefix}hardQCDbeauty",
        f"--{flag_prefix}hard-qcd-beauty",
        dest="hard_qcd_beauty",
        default=False,
        action="store_true",
        help="Enable HardQCD:hardbbbar.",
    )
    parser.add_argument(
        f"--{flag_prefix}hardQCDlf",
        f"--{flag_prefix}hard-qcd-lf",
        dest="hard_qcd_lf",
        default=False,
        action="store_true",
        help="Enable hard-QCD light flavor plus gluon channels.",
    )
    parser.add_argument(
        f"--{flag_prefix}hardQCDgluons",
        f"--{flag_prefix}hard-qcd-gluons",
        dest="hard_qcd_gluons",
        default=False,
        action="store_true",
        help="Enable hard-QCD gluon outgoing channels.",
    )
    parser.add_argument(
        f"--{flag_prefix}hardQCDquarks",
        f"--{flag_prefix}hard-qcd-quarks",
        dest="hard_qcd_quarks",
        default=False,
        action="store_true",
        help="Enable hard-QCD quark outgoing channels, including c/b.",
    )
    parser.add_argument(
        f"--{flag_prefix}hardQCDuds",
        f"--{flag_prefix}hard-qcd-uds",
        dest="hard_qcd_uds",
        default=False,
        action="store_true",
        help="Enable hard-QCD uds outgoing channels.",
    )
    parser.add_argument(
        f"--{flag_prefix}minbias",
        dest="minbias",
        default=False,
        action="store_true",
        help="Enable SoftQCD:all.",
    )
    parser.add_argument(
        f"--{flag_prefix}noISR",
        f"--{flag_prefix}no-isr",
        dest="no_isr",
        default=False,
        action="store_true",
        help="Disable ISR.",
    )
    parser.add_argument(
        f"--{flag_prefix}noMPI",
        f"--{flag_prefix}no-mpi",
        dest="no_mpi",
        default=False,
        action="store_true",
        help="Disable MPI.",
    )
    parser.add_argument(
        f"--{flag_prefix}noHadron",
        f"--{flag_prefix}no-hadron",
        dest="no_hadron",
        default=False,
        action="store_true",
        help="Disable hadronization.",
    )
    parser.add_argument(
        f"--{flag_prefix}cmnd",
        dest="cmnd_files",
        nargs="+",
        default=None,
        help="Pythia command file(s) to read before generated settings.",
    )
    parser.add_argument(
        "--pythiaopts",
        f"--{flag_prefix}opts",
        dest="pythiaopts",
        default="",
        help="Comma-separated raw Pythia settings; underscores are converted to spaces.",
    )
    parser.add_argument(
        f"--{flag_prefix}quiet",
        dest="quiet",
        default=True,
        action=argparse.BooleanOptionalAction,
        help="Apply quiet Pythia printout settings.",
    )
    return parser


def normalize_config(config: PythiaConfig | Mapping[str, Any] | argparse.Namespace | None) -> PythiaConfig:
    if config is None:
        return PythiaConfig()
    if isinstance(config, PythiaConfig):
        return config
    if isinstance(config, argparse.Namespace):
        return PythiaConfig.from_namespace(config)
    if isinstance(config, Mapping):
        return PythiaConfig.from_mapping(config)
    raise TypeError(f"unsupported Pythia config type: {type(config).__name__}")


def _lookup(data: Mapping[str, Any], *names: str, default: Any = _MISSING) -> Any:
    normalized = {_normalize_key(key): key for key in data}
    for name in names:
        key = normalized.get(_normalize_key(name))
        if key is not None:
            return data[key]
    return default


def _normalize_key(key: Any) -> str:
    return str(key).replace("-", "_").lower()


def _as_bool(value: Any) -> bool:
    if value is _MISSING or value is None:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _positive_float_or_none(value: Any) -> float | None:
    if value is _MISSING or value is None or value == "":
        return None
    number = float(value)
    return number if number >= 0 else None


def _nonnegative_int_or_none(value: Any) -> int | None:
    if value is _MISSING or value is None or value == "":
        return None
    number = int(value)
    return number if number >= 0 else None


def _format_number(value: float | int) -> str:
    return f"{value:g}"


def _paths_tuple(value: Any) -> tuple[str, ...]:
    if value is _MISSING or value is None or value == "":
        return ()
    if isinstance(value, (str, Path)):
        return (str(value),)
    return tuple(str(item) for item in value if item)


def _settings_tuple(value: Any, *, comma_encoded: bool = False) -> tuple[str, ...]:
    if value is _MISSING or value is None or value == "":
        return ()
    if isinstance(value, str):
        chunks = value.split(",") if comma_encoded else value.splitlines()
        if not chunks:
            chunks = [value]
        return tuple(_decode_setting(chunk, comma_encoded=comma_encoded) for chunk in chunks if chunk.strip())
    return tuple(str(item) for item in value if str(item).strip())


def _decode_setting(value: str, *, comma_encoded: bool) -> str:
    setting = value.strip()
    if comma_encoded:
        setting = setting.replace("_", " ")
    return setting


def _enabled_from_negative_flags(
    data: Mapping[str, Any],
    *,
    enabled_key: str,
    disabled_keys: Sequence[str],
    default: bool,
) -> bool:
    enabled = _lookup(data, enabled_key)
    if enabled is not _MISSING:
        return _as_bool(enabled)
    return not any(_as_bool(_lookup(data, key, default=False)) for key in disabled_keys) if default else False


def _legacy_processes(data: Mapping[str, Any]) -> tuple[str, ...]:
    flags = (
        ("hard_qcd", ("hard_qcd", "py_hardQCD", "py_hard_qcd")),
        ("hard_qcd_charm", ("hard_qcd_charm", "py_hardQCDcharm", "py_hard_qcd_charm")),
        ("hard_qcd_beauty", ("hard_qcd_beauty", "py_hardQCDbeauty", "py_hard_qcd_beauty")),
        ("hard_qcd_lf", ("hard_qcd_lf", "py_hardQCDlf", "py_hard_qcd_lf")),
        ("hard_qcd_gluons", ("hard_qcd_gluons", "py_hardQCDgluons", "py_hard_qcd_gluons")),
        ("hard_qcd_quarks", ("hard_qcd_quarks", "py_hardQCDquarks", "py_hard_qcd_quarks")),
        ("hard_qcd_uds", ("hard_qcd_uds", "py_hardQCDuds", "py_hard_qcd_uds")),
        ("prompt_photon", ("prompt_photon", "py_promptPhoton", "py_prompt_photon")),
        ("minbias", ("minbias", "py_minbias")),
        ("inelastic", ("inelastic", "py_inel")),
        ("non_diffractive", ("non_diffractive", "py_nd")),
        ("elastic", ("elastic", "py_el")),
        ("diffractive", ("diffractive", "py_diff")),
    )
    processes: list[str] = []
    for process, aliases in flags:
        if any(_as_bool(_lookup(data, alias, default=False)) for alias in aliases):
            processes.append(process)
    return tuple(processes)


def _normalize_process_value(value: Any) -> str | tuple[str, ...] | None:
    if value is _MISSING or value is None or value == "":
        return None
    if isinstance(value, str):
        process = _normalize_process_name(value)
        return process or None
    return tuple(process for item in value if (process := _normalize_process_name(item)))


def _process_names(process: str | Sequence[str] | None) -> tuple[str, ...]:
    normalized = _normalize_process_value(process)
    if normalized is None:
        return ()
    if isinstance(normalized, str):
        return (normalized,)
    return normalized


def _normalize_process_name(value: Any) -> str:
    key = str(value).strip()
    if not key:
        return ""
    normalized = _PROCESS_ALIASES.get(key.replace(" ", "_").lower())
    if normalized is None:
        allowed = ", ".join(sorted(name for name in _PROCESS_SETTINGS))
        raise PythiaConfigError(f"unknown Pythia process preset {key!r}; expected one of: {allowed}, none")
    return normalized
