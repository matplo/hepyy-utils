"""JEWEL run-directory staging and execution."""

from __future__ import annotations

import importlib.resources as resources
import os
import re
import shutil
import subprocess
import warnings
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

import yaml

from .params import set_param_text


MEDIUM_SAMPLE = "jewel_med"
VACUUM_SAMPLE = "jewel_vac"

SAMPLE_ALIASES = {
    "medium": [MEDIUM_SAMPLE],
    "pbpb": [MEDIUM_SAMPLE],
    "aa": [MEDIUM_SAMPLE],
    "med": [MEDIUM_SAMPLE],
    "jewel_med": [MEDIUM_SAMPLE],
    "vacuum": [VACUUM_SAMPLE],
    "pp": [VACUUM_SAMPLE],
    "vac": [VACUUM_SAMPLE],
    "jewel_vac": [VACUUM_SAMPLE],
    "both": [MEDIUM_SAMPLE, VACUUM_SAMPLE],
}


@dataclass(frozen=True)
class PreparedSample:
    sample: str
    run_dir: Path
    manifest_path: Path
    hepmc_path: Path
    params_path: Path


def default_tag() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def resolve_samples(selection: str) -> list[str]:
    try:
        return SAMPLE_ALIASES[selection.lower()]
    except KeyError as exc:
        allowed = ", ".join(sorted(SAMPLE_ALIASES))
        raise ValueError(f"unknown sample selection {selection!r}; expected one of: {allowed}") from exc


def _template_text(name: str, template_dir: str | Path | None = None) -> str:
    if template_dir is not None:
        return (Path(template_dir).expanduser().resolve() / name).read_text()
    return resources.files("hepyy_utils.jewel.templates").joinpath(name).read_text()


def _write_template(name: str, destination: Path, template_dir: str | Path | None = None) -> None:
    destination.write_text(_template_text(name, template_dir=template_dir))


def _sample_kind(sample: str) -> str:
    if sample == MEDIUM_SAMPLE:
        return "medium"
    if sample == VACUUM_SAMPLE:
        return "vacuum"
    raise ValueError(f"unknown canonical sample: {sample}")


def _sample_executable(sample: str, medium_bin: str, vacuum_bin: str) -> str:
    return medium_bin if sample == MEDIUM_SAMPLE else vacuum_bin


def _sample_executable_pattern(sample: str) -> str:
    return "jewel-*-simple" if sample == MEDIUM_SAMPLE else "jewel-*-vac"


def _version_tokens(text: str) -> tuple[tuple[int, int | str], ...]:
    return tuple((0, int(part)) if part.isdigit() else (1, part.lower()) for part in re.findall(r"\d+|[A-Za-z]+", text))


def _jewel_version_key(path: str | Path) -> tuple[tuple[tuple[int, int | str], ...], int, tuple[tuple[int, int | str], ...], str, str]:
    candidate = Path(path)
    match = re.fullmatch(r"jewel-(.+)-(?:simple|vac)", candidate.name)
    if match is None:
        raise ValueError(f"invalid JEWEL executable name: {candidate.name!r}")
    version = match.group(1)
    release, _, prerelease = version.partition("-")
    return _version_tokens(release), 1 if not prerelease else 0, _version_tokens(prerelease), candidate.name, str(candidate)


def _resolve_executable(requested: str, pattern: str) -> tuple[str, str | None]:
    if shutil.which(requested) is not None:
        return requested, None

    candidates: list[Path] = []
    seen: set[Path] = set()
    for entry in os.environ.get("PATH", "").split(os.pathsep):
        if not entry:
            continue
        directory = Path(entry).expanduser()
        if not directory.is_dir():
            continue
        for path in directory.glob(pattern):
            if path.is_file() and os.access(path, os.X_OK):
                resolved_path = path.resolve()
                if resolved_path not in seen:
                    seen.add(resolved_path)
                    candidates.append(resolved_path)

    if not candidates:
        raise FileNotFoundError(
            f"requested JEWEL executable {requested!r} was not found and no executables matching {pattern!r} were found in PATH"
        )

    resolved = max(candidates, key=_jewel_version_key)
    return str(resolved), (
        f"requested JEWEL executable {requested!r} was not found; using {resolved.name!r} from PATH"
    )


def _resolved_sample_executable(sample: str, medium_bin: str, vacuum_bin: str) -> tuple[str, str | None]:
    requested = _sample_executable(sample, medium_bin=medium_bin, vacuum_bin=vacuum_bin)
    return _resolve_executable(requested, _sample_executable_pattern(sample))


def _sample_template(sample: str) -> str:
    return "params.PbPb.template.dat" if sample == MEDIUM_SAMPLE else "params.pp.template.dat"


def _set_if_present(text: str, key: str, value: str | int | float | None) -> str:
    if value is None or value == "":
        return text
    return set_param_text(text, key, value)


def prepare_sample(
    *,
    sample: str,
    tag: str,
    out_dir: str | Path = "outputs/jewel_events",
    clean: bool = False,
    nevents: str | int | None = None,
    ptmin: str | float | None = None,
    ptmax: str | float | None = None,
    etamax: str | float | None = None,
    job_id: str | int | None = None,
    medium_bin: str = "jewel-2.4.0-simple",
    vacuum_bin: str = "jewel-2.4.0-vac",
    template_dir: str | Path | None = None,
) -> PreparedSample:
    """Prepare one self-contained JEWEL sample run directory."""

    sample = sample.lower()
    if sample not in (MEDIUM_SAMPLE, VACUUM_SAMPLE):
        raise ValueError(f"prepare_sample expects canonical sample name, got {sample!r}")

    run_root = Path(out_dir).expanduser().resolve() / tag
    run_dir = run_root / sample
    if run_dir.exists():
        if clean:
            shutil.rmtree(run_dir)
        else:
            raise FileExistsError(f"run directory exists: {run_dir}; use clean=True or a new tag")

    for rel in ("events", "logs", "splitint", "xsecs", "roots"):
        (run_dir / rel).mkdir(parents=True, exist_ok=True)

    hepmc_rel = f"events/{sample}_{tag}.hepmc"
    log_rel = f"logs/{sample}_{tag}.log"
    stdout_rel = f"logs/{sample}_{tag}.stdout.log"
    splitint_rel = f"splitint/{sample}_{tag}.dat"
    xsec_rel = f"xsecs/{sample}_{tag}.dat"
    root_rel = f"roots/{sample}_{tag}.root"

    params_text = _template_text(_sample_template(sample), template_dir=template_dir)
    params_text = set_param_text(params_text, "LOGFILE", log_rel)
    params_text = set_param_text(params_text, "HEPMCFILE", hepmc_rel)
    params_text = set_param_text(params_text, "SPLITINTFILE", splitint_rel)
    params_text = set_param_text(params_text, "XSECFILE", xsec_rel)
    params_text = _set_if_present(params_text, "NEVENT", nevents)
    params_text = _set_if_present(params_text, "PTMIN", ptmin)
    params_text = _set_if_present(params_text, "PTMAX", ptmax)
    params_text = _set_if_present(params_text, "ETAMAX", etamax)
    params_text = _set_if_present(params_text, "NJOB", job_id)

    if sample == MEDIUM_SAMPLE:
        _write_template("medium.params.dat", run_dir / "medium.params.dat", template_dir=template_dir)
        params_text = set_param_text(params_text, "MEDIUMPARAMS", "medium.params.dat")

    params_path = run_dir / "params.dat"
    params_path.write_text(params_text)
    executable, warning_message = _resolved_sample_executable(sample, medium_bin=medium_bin, vacuum_bin=vacuum_bin)
    if warning_message is not None:
        warnings.warn(warning_message, RuntimeWarning, stacklevel=2)

    manifest = {
        "schema_version": 1,
        "sample": sample,
        "kind": _sample_kind(sample),
        "tag": tag,
        "executable": executable,
        "params": "params.dat",
        "hepmc": hepmc_rel,
        "root": root_rel,
        "log": log_rel,
        "stdout": stdout_rel,
        "splitint": splitint_rel,
        "xsec": xsec_rel,
        "pdf_sets": {
            "pp": {"name": "CT14nlo", "pdfset": 13100},
            "pbpb": {"name": "EPPS16nlo_CT14nlo_Pb208", "pdfset": 901300},
        },
    }
    manifest_path = run_dir / "manifest.yaml"
    manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False))

    return PreparedSample(
        sample=sample,
        run_dir=run_dir,
        manifest_path=manifest_path,
        hepmc_path=run_dir / hepmc_rel,
        params_path=params_path,
    )


def prepare_runs(
    *,
    samples: str = "both",
    tag: str | None = None,
    out_dir: str | Path = "outputs/jewel_events",
    clean: bool = False,
    nevents: str | int | None = None,
    nevents_medium: str | int | None = None,
    nevents_vacuum: str | int | None = None,
    ptmin: str | float | None = None,
    ptmax: str | float | None = None,
    etamax: str | float | None = None,
    job_id: str | int | None = None,
    job_id_medium: str | int | None = None,
    job_id_vacuum: str | int | None = None,
    medium_bin: str = "jewel-2.4.0-simple",
    vacuum_bin: str = "jewel-2.4.0-vac",
    template_dir: str | Path | None = None,
) -> list[PreparedSample]:
    run_tag = tag or default_tag()
    prepared: list[PreparedSample] = []
    for sample in resolve_samples(samples):
        sample_nevents = nevents_medium if sample == MEDIUM_SAMPLE else nevents_vacuum
        sample_job_id = job_id_medium if sample == MEDIUM_SAMPLE else job_id_vacuum
        prepared.append(
            prepare_sample(
                sample=sample,
                tag=run_tag,
                out_dir=out_dir,
                clean=clean,
                nevents=sample_nevents if sample_nevents not in (None, "") else nevents,
                ptmin=ptmin,
                ptmax=ptmax,
                etamax=etamax,
                job_id=sample_job_id if sample_job_id not in (None, "") else job_id,
                medium_bin=medium_bin,
                vacuum_bin=vacuum_bin,
                template_dir=template_dir,
            )
        )
    return prepared


def load_manifest(manifest_path: str | Path) -> dict:
    return yaml.safe_load(Path(manifest_path).read_text())


def manifest_paths(run_path: str | Path, samples: str = "both") -> list[Path]:
    path = Path(run_path).expanduser().resolve()
    if path.name == "manifest.yaml" and path.is_file():
        return [path]
    if (path / "manifest.yaml").is_file():
        return [path / "manifest.yaml"]
    paths = [path / sample / "manifest.yaml" for sample in resolve_samples(samples)]
    missing = [str(p) for p in paths if not p.is_file()]
    if missing:
        raise FileNotFoundError("missing JEWEL manifest(s): " + ", ".join(missing))
    return paths


def run_manifest(manifest_path: str | Path, *, check_output: bool = True) -> dict:
    manifest_path = Path(manifest_path).expanduser().resolve()
    manifest = load_manifest(manifest_path)
    run_dir = manifest_path.parent
    executable = manifest["executable"]
    params = manifest["params"]
    stdout_path = run_dir / manifest["stdout"]
    stdout_path.parent.mkdir(parents=True, exist_ok=True)

    with stdout_path.open("w") as log:
        process = subprocess.Popen(
            [executable, params],
            cwd=run_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        assert process.stdout is not None
        for line in process.stdout:
            print(line, end="")
            log.write(line)
        returncode = process.wait()

    if returncode != 0:
        raise RuntimeError(f"{executable} failed with exit code {returncode}; see {stdout_path}")

    hepmc_path = run_dir / manifest["hepmc"]
    if check_output and (not hepmc_path.is_file() or hepmc_path.stat().st_size <= 0):
        raise RuntimeError(f"expected HepMC output missing or empty: {hepmc_path}")

    return {
        "sample": manifest["sample"],
        "run_dir": str(run_dir),
        "hepmc": str(hepmc_path),
        "stdout": str(stdout_path),
    }


def run_manifests(paths: Iterable[str | Path], *, check_output: bool = True) -> list[dict]:
    return [run_manifest(path, check_output=check_output) for path in paths]
