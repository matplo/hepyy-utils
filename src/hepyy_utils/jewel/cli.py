"""Command-line entry points for JEWEL utilities."""

from __future__ import annotations

from pathlib import Path

import click

from .convert import CS_MODES, LEFTOVER_MODES, convert_hepmc_to_root
from .subtraction import THERMAL_PID_MODES
from .workflow import (
    MEDIUM_SAMPLE,
    load_manifest,
    manifest_paths,
    prepare_runs,
    run_manifest,
)


CONTEXT_SETTINGS = {"help_option_names": ["-h", "--help"]}


def _cs_options(command):
    command = click.option("--seed", type=int, default=0, show_default=True, help="Seed for the random --thermal-pid modes (combined with the file name).")(command)
    command = click.option(
        "--thermal-pid",
        type=click.Choice(THERMAL_PID_MODES),
        default="reference",
        show_default=True,
        help="PDG id of leftover thermal momenta: reference = always 211 (the shipped Rivet code), intended = pi+/pi-/pi0 1/3 each, cast = the C++ with the division fixed.",
    )(command)
    command = click.option("--leftovers", type=click.Choice(LEFTOVER_MODES), default="keep", show_default=True, help="Reference mode: keep leftover thermal momenta as particles (tag 2, as the Rivet code) or drop them.")(command)
    command = click.option("--dRmax", "dRmax", type=float, default=0.5, show_default=True, help="Reference mode: maximum particle-thermal distance in (y, phi).")(command)
    command = click.option("--cs-mode", type=click.Choice(CS_MODES), default="reference", show_default=True, help="Constituent subtraction: reference (Rivet SubtractedJewelEvent port) or legacy (earlier hepyy-utils algorithm).")(command)
    return command


def _prepare_options(command):
    command = click.option("--template-dir", type=click.Path(file_okay=False), default=None, help="Directory with JEWEL template .dat files.")(command)
    command = click.option("--vacuum-bin", default="jewel-2.6.0-vac", show_default=True, help="Vacuum JEWEL executable.")(command)
    command = click.option("--medium-bin", default="jewel-2.6.0-simple", show_default=True, help="Medium JEWEL executable.")(command)
    command = click.option("--job-id-vacuum", default=None, help="Override NJOB for the vacuum/pp sample.")(command)
    command = click.option("--job-id-medium", default=None, help="Override NJOB for the medium/PbPb sample.")(command)
    command = click.option("--job-id", default=None, help="Override NJOB for both samples.")(command)
    command = click.option("--etamax", default=None, help="Set or override ETAMAX for both samples.")(command)
    command = click.option("--ptmax", default=None, help="Override PTMAX for both samples.")(command)
    command = click.option("--ptmin", default=None, help="Override PTMIN for both samples.")(command)
    command = click.option("--nevents-vacuum", default=None, help="Override NEVENT for the vacuum/pp sample.")(command)
    command = click.option("--nevents-medium", default=None, help="Override NEVENT for the medium/PbPb sample.")(command)
    command = click.option("--nevents", default=None, help="Override NEVENT for both samples.")(command)
    command = click.option("--clean", is_flag=True, help="Remove selected tag/sample run directories before preparing.")(command)
    command = click.option("--tag", default=None, help="Run tag. Default: current timestamp.")(command)
    command = click.option("--out-dir", default="outputs/jewel_events", show_default=True, help="Output directory.")(command)
    command = click.option(
        "--samples",
        default="both",
        show_default=True,
        help="Samples to prepare: both, medium/PbPb, or vacuum/pp.",
    )(command)
    return command


@click.command(context_settings=CONTEXT_SETTINGS)
@_prepare_options
def prepare(**kwargs) -> None:
    """Prepare self-contained JEWEL run directories."""

    prepared = prepare_runs(**kwargs)
    for item in prepared:
        click.echo(f"prepared {item.sample}: {item.run_dir}")
        click.echo(f"  params:   {item.params_path}")
        click.echo(f"  manifest: {item.manifest_path}")
        click.echo(f"  hepmc:    {item.hepmc_path}")


@click.command(context_settings=CONTEXT_SETTINGS)
@click.argument("run_path", type=click.Path(exists=True))
@click.option("--samples", default="both", show_default=True, help="Samples to run when RUN_PATH is a tag/root directory.")
@click.option("--no-output-check", is_flag=True, help="Do not require a non-empty HepMC file after JEWEL exits.")
def run(run_path: str, samples: str, no_output_check: bool) -> None:
    """Run prepared JEWEL sample directories from manifests."""

    for manifest in manifest_paths(run_path, samples=samples):
        click.echo(f"running {manifest}")
        result = run_manifest(manifest, check_output=not no_output_check)
        click.echo(f"done {result['sample']}: {result['hepmc']}")


@click.command(context_settings=CONTEXT_SETTINGS)
@click.argument("input_hepmc", type=click.Path(exists=True, dir_okay=False))
@click.argument("output_root", type=click.Path(dir_okay=False))
@click.option("--subtract-4mom/--no-subtract-4mom", default=False, show_default=True, help="Apply JEWEL 4-momentum recoil subtraction.")
@click.option("--max-events", type=int, default=None, help="Maximum events to convert.")
@click.option("--final-status", type=int, default=1, show_default=True, help="HepMC status used for final particles.")
@click.option("--ghost-status", type=int, default=3, show_default=True, help="HepMC status used for JEWEL thermal ghosts.")
@click.option("--progress/--no-progress", default=True, show_default=True, help="Show a tqdm conversion progress bar.")
@click.option("--event-info/--no-event-info", default=True, show_default=True, help="Write the event_info tree.")
@_cs_options
def convert(
    input_hepmc: str,
    output_root: str,
    subtract_4mom: bool,
    max_events: int | None,
    final_status: int,
    ghost_status: int,
    progress: bool,
    event_info: bool,
    cs_mode: str,
    dRmax: float,
    leftovers: str,
    thermal_pid: str,
    seed: int,
) -> None:
    """Convert HepMC to ROOT track TTrees using uproot."""

    result = convert_hepmc_to_root(
        input_hepmc,
        output_root,
        subtract_4mom=subtract_4mom,
        max_events=max_events,
        final_status=final_status,
        ghost_status=ghost_status,
        progress=progress,
        write_event_info=event_info,
        cs_mode=cs_mode,
        dRmax=dRmax,
        leftovers=leftovers,
        thermal_pid=thermal_pid,
        seed=seed,
    )
    click.echo(f"converted {result['events']} events, {result['tracks']} tracks")
    click.echo(f"  output: {result['output']}")


@click.command(context_settings=CONTEXT_SETTINGS)
@_prepare_options
@click.option("--convert/--no-convert", "do_convert", default=False, show_default=True, help="Convert generated HepMC files to ROOT after running.")
@click.option(
    "--subtract-4mom-medium/--no-subtract-4mom-medium",
    default=True,
    show_default=True,
    help="Apply 4-momentum subtraction when converting medium/PbPb samples.",
)
@click.option("--no-output-check", is_flag=True, help="Do not require a non-empty HepMC file after JEWEL exits.")
@_cs_options
def pipeline(
    do_convert: bool,
    subtract_4mom_medium: bool,
    no_output_check: bool,
    cs_mode: str,
    dRmax: float,
    leftovers: str,
    thermal_pid: str,
    seed: int,
    **kwargs,
) -> None:
    """Prepare and run JEWEL, optionally converting HepMC to ROOT."""

    prepared = prepare_runs(**kwargs)
    for item in prepared:
        click.echo(f"running {item.sample}: {item.run_dir}")
        run_manifest(item.manifest_path, check_output=not no_output_check)
        if do_convert:
            manifest = load_manifest(item.manifest_path)
            root_path = Path(item.run_dir) / manifest["root"]
            subtract = item.sample == MEDIUM_SAMPLE and subtract_4mom_medium
            result = convert_hepmc_to_root(
                item.hepmc_path,
                root_path,
                subtract_4mom=subtract,
                cs_mode=cs_mode,
                dRmax=dRmax,
                leftovers=leftovers,
                thermal_pid=thermal_pid,
                seed=seed,
            )
            click.echo(f"converted {result['events']} events to {result['output']}")


@click.command(context_settings=CONTEXT_SETTINGS)
@click.argument("inputs", nargs=-1, required=True, type=click.Path(exists=True, dir_okay=False))
@click.option("--outdir", default=".", show_default=True, type=click.Path(file_okay=False), help="Output directory.")
@click.option("--format", "fmt", type=click.Choice(["parquet", "root", "both"]), default="parquet", show_default=True)
@click.option("--particles", type=click.Choice(["cs", "raw", "both"]), default="cs", show_default=True, help="Subtracted particles, the raw record, or both.")
@click.option("--dRmax", "dRmax", type=float, default=0.5, show_default=True, help="Maximum particle-thermal distance in (y, phi).")
@click.option("--thermal-pid", type=click.Choice(THERMAL_PID_MODES), default="reference", show_default=True, help="PDG id of leftover thermal momenta (tags 2, 3).")
@click.option("--seed", type=int, default=0, show_default=True, help="Seed for the random --thermal-pid modes.")
@click.option("--chunk", type=int, default=5000, show_default=True, help="Events per write.")
@click.option("--double", is_flag=True, help="float64 momenta (JEWEL writes 6 digits).")
def tables(inputs, outdir, fmt, particles, dRmax, thermal_pid, seed, chunk, double) -> None:
    """Convert JEWEL HepMC to flat events/particles tables (parquet and/or ROOT).

    The particles are subtracted with the reference constituent subtraction and keep every tag,
    so the leftover convention is chosen at analysis time.
    """

    from .tables import convert_hepmc_to_tables

    convert_hepmc_to_tables(
        inputs, outdir, format=fmt, particles=particles, dRmax=dRmax, thermal_pid=thermal_pid,
        seed=seed, chunk=chunk, double=double,
    )


@click.group(context_settings=CONTEXT_SETTINGS)
def main() -> None:
    """JEWEL utilities."""


main.add_command(prepare, "prepare")
main.add_command(run, "run")
main.add_command(convert, "convert")
main.add_command(pipeline, "pipeline")
main.add_command(tables, "tables")


def prepare_main() -> None:
    prepare.main(standalone_mode=True)


def run_main() -> None:
    run.main(standalone_mode=True)


def convert_main() -> None:
    convert.main(standalone_mode=True)


def pipeline_main() -> None:
    pipeline.main(standalone_mode=True)


def tables_main() -> None:
    tables.main(standalone_mode=True)


if __name__ == "__main__":
    main()
