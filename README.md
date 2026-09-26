# hepyy-utils

Workflow utilities for HEP event generators and tools installed with
[hepyy](https://github.com/matplo/hepyy).

The repository is organized by generator/tool namespace. JEWEL utilities live
under `hepyy_utils.jewel`, Pythia8 helpers live under
`hepyy_utils.pythia`, and all JEWEL command-line entry points use a
`jewel_` prefix so future utilities for other generators can coexist cleanly.

## Artifact Caching

`hepyy_utils.cache` provides generator-neutral helpers for local analysis
caches: JSON-safe config normalization, deterministic config hashes, compact
filename tokens, pickle payload read/write, and JSON sidecars.
See [cache/README.md](cache/README.md) for usage patterns, invalidation
guidelines, sidecar conventions, and pickle portability caveats.

## Pythia8

`hepyy_utils.pythia` provides a small library-first layer for building and
applying common Pythia8 settings. It does not import Pythia8, cppyy, or
hepyy at package import time, so the utility package remains installable
without the generator stack loaded.

Install/load Pythia8 separately when you want to run generation:

```bash
hepyy install pythia8 fastjet hepyy-utils
module load pythia8 fastjet hepyy-utils
```

Create a standard pp hard-QCD setup with a dataclass:

```python
from hepyy_utils.pythia import PythiaConfig, create_pythia

config = PythiaConfig.pp_hard_qcd(ecm=13000.0, pthat_min=20.0)
pythia = create_pythia(config)
```

The same helper accepts dictionaries:

```python
from hepyy_utils.pythia import create_pythia

pythia = create_pythia({
    "ecm": 13000.0,
    "process": "hard_qcd",
    "pthat_min": 20.0,
    "seed": 12345,
})
```

Useful hard-QCD process presets include:

- `hard_qcd`: inclusive `HardQCD:all`
- `hard_qcd_beauty`: `HardQCD:hardbbbar`
- `hard_qcd_charm`: `HardQCD:hardccbar`
- `hard_qcd_uds`: uds outgoing channels
- `hard_qcd_lf`: uds plus gluon channels, with hard c/b disabled
- `hard_qcd_gluons`: gluon outgoing channels
- `hard_qcd_quarks`: quark outgoing channels, including c/b

The same choices are available through aliases such as `beauty`, `uds`,
`light`, and `gluons`, or through compatibility flags such as
`--py-hardQCDbeauty`, `--py-hardQCDuds`, and `--py-hardQCDlf`.

It can also consume `argparse.Namespace` objects. The added options use the
historical `--py-*` flag style, while the generated namespace is normalized by
the utility:

```python
import argparse

from hepyy_utils.pythia import add_pythia_args, create_pythia

parser = argparse.ArgumentParser()
add_pythia_args(parser)
args = parser.parse_args()

pythia = create_pythia(args)
```

Raw Pythia command strings remain supported through `extra_settings` or the
legacy `--pythiaopts` option. Extra settings are applied last so they can
override generated defaults.

If Pythia8 is not already importable through a shell module, pass `load=True`
to call `hepyy.load("pythia8")` before creating the generator:

```python
pythia = create_pythia(config, load=True)
```

A local FastJet example is provided at `examples/demo_pythia_fastjet.py`.

### Pythia Flavor Tagging

`hepyy_utils.pythia.flavor` provides reusable truth-flavor helpers for
Pythia/FastJet workflows. The helpers are importable without Pythia8 or FastJet
loaded; runtime objects are passed in by the caller.

Hard-parton matching works at hadron and parton level:

```python
from hepyy_utils.pythia.flavor import extract_hard_partons, tag_jet_by_hard_parton

partons = extract_hard_partons(pythia.event)
tag = tag_jet_by_hard_parton(jet, partons, match_radius=0.3)
```

By default, `b` means `|pdg| == 5`, `light` means `|pdg| in {1, 2, 3}`,
and charm/gluon jets are kept separate from the light-quark category. The
matching radius is always caller-configurable through `match_radius`.

Heavy-hadron ghost tagging is also available for hadron-level events:

```python
from hepyy_utils.pythia.flavor import (
    append_ghosts,
    make_heavy_hadron_ghosts,
    tag_jet_by_heavy_hadron_ghosts,
)

ghosts, labels = make_heavy_hadron_ghosts(pythia.event, fastjet)
append_ghosts(particles, ghosts)
# Cluster particles with FastJet, then:
tag = tag_jet_by_heavy_hadron_ghosts(jet, labels)
```

Ghost tagging requires hadronization. For parton-level generation, use
hard-parton matching instead.

## JEWEL

V1 provides helpers for staging, running, and converting JEWEL event generation.
The utilities are split into four commands:

- `jewel_prepare`: create self-contained run directories and patched JEWEL
  parameter files. It does not run JEWEL.
- `jewel_run`: run JEWEL inside directories previously created by
  `jewel_prepare`.
- `jewel_convert`: convert one HepMC file to a ROOT track TTree using `pyhepmc`
  and `uproot`.
- `jewel_pipeline`: do `prepare` and `run` in one command, with optional
  conversion.
- `jewel_tables`: convert HepMC files to flat events/particles tables (parquet
  and/or ROOT) with the reference thermal-momentum subtraction.

Install the utility package:

```bash
hepyy recipe update
hepyy install hepyy-utils
module load hepyy-utils
```

The default executables are `jewel-2.6.0-simple` and `jewel-2.6.0-vac`
(`--medium-bin`/`--vacuum-bin` select another version). JEWEL 2.6.0 runs with
colour coherence ON by default; the PbPb template sets `PCOHREJ`, `COHSCAT` and
`COHLENGTHFAC` explicitly (coherence OFF: `PCOHREJ 0`, `COHSCAT F`).

`hepyy-utils` itself does not hard-depend on JEWEL. This keeps the package
installable for future non-JEWEL utilities; only the `jewel_` commands require
JEWEL/LHAPDF at runtime.

For JEWEL production, install/load the generator stack separately:

```bash
hepyy install jewel lhapdf
module load jewel lhapdf
```

The required LHAPDF sets for the bundled JEWEL templates are:

- pp/vacuum: `CT14nlo` (`PDFSET 13100`)
- PbPb/medium: `EPPS16nlo_CT14nlo_Pb208` (`PDFSET 901300`)

Install the PDF sets through LHAPDF if they are not already present:

```bash
lhapdf install CT14nlo
lhapdf install EPPS16nlo_CT14nlo_Pb208
```

## JEWEL Workflows

Prepare both PbPb and pp run directories without running JEWEL:

```bash
jewel_prepare --tag pt100 --samples both --nevents 10000
```

Run JEWEL from the generated manifests:

```bash
jewel_run outputs/jewel_events/pt100
```

Convert one HepMC file to a ROOT TTree of final-particle track arrays:

```bash
jewel_convert events.hepmc events.root
```

For medium/PbPb JEWEL output with recoil subtraction enabled in the JEWEL
params, use 4-momentum subtraction during conversion:

```bash
jewel_convert jewel_med.hepmc jewel_med.root --subtract-4mom
```

Run prepare, JEWEL execution, and conversion in one command:

```bash
jewel_pipeline --tag pt100 --samples both --nevents 10000 --convert
```

Run one sample at a time:

```bash
jewel_prepare --tag pbpb_001 --samples medium --job-id 1
jewel_prepare --tag pp_001 --samples vacuum --job-id 1
```

Conversion reads HepMC with `pyhepmc` and writes ROOT TTrees with `uproot`.
It does not use PyROOT or native ROOT libraries. The default tree name is
`tracks`, with array branches for event id, momentum components, energy,
particle id (`label`) and `tag`.

## Thermal-momentum (constituent) subtraction

JEWEL with `KEEPRECOILS T` and `WRITESCATCEN T` writes the recoiling medium
partons as final-state particles and the thermal momenta they came from as
status-3 records. The subtraction removes the thermal momenta from nearby
particles. `jewel_convert --subtract-4mom` offers two modes.

**`--cs-mode reference` (default)** is `hepyy_utils.jewel.subtraction`, a
step-by-step port of the JEWEL authors' Rivet projection `SubtractedJewelEvent`
(Milhano and Zapp, Eur. Phys. J. C 82 (2022), arXiv:2207.14814). It was checked
against a C++ port of that projection: identical rows, tags and PDG ids, and
four-momenta equal to 4×10⁻¹⁴. It uses numba when installed (`.[fast]`).

**`--cs-mode legacy`** is the earlier algorithm of this package, kept to
reproduce older samples.

| | reference | legacy |
|---|---|---|
| final state | status 1 and 4 | status 1 only |
| particle–thermal pairs | ΔR ≤ `--dRmax` (0.5), in increasing ΔR | every pair of the event, no distance cut |
| equal pT or m_δ | the thermal momentum is reduced | the particle is reduced |
| leftover thermal momenta | kept as particles, tag 2 (`--leftovers keep`), or dropped (`--leftovers drop`) | dropped |
| thermal momenta with E ≤ \|p_z\| | kept as particles, tag 3 | dropped |
| negative m² from rounding | used as is | clipped to 0 |
| PDG id of leftovers | `--thermal-pid reference` (211, as the shipped C++), `intended` or `cast` | – |

The missing distance cut is the important difference. In legacy mode a thermal
momentum anywhere in the event can reduce a particle inside a jet.

The `tag` branch records what each track is:

| tag | meaning |
|---|---|
| 0 | subtracted particle |
| 1 | particle with E ≤ \|p_z\|, passed through |
| 2 | leftover thermal momentum, kept as a particle |
| 3 | thermal momentum with E ≤ \|p_z\|, kept as a particle |
| -1 | no subtraction |

With `--leftovers keep`, the leftover convention can still be chosen at
analysis time (tags 0–1 only, or all tags). The settings are stored in the
ROOT file as the TObjString `jewel_cs`.

`event_info` also has:

- `jewel_event`: the JEWEL event number;
- `beam1_pid` and `beam2_pid`: 2212 or 2112;
- `cs_left_pt`: the leftover thermal pT per event.

Each JEWEL job generates the pp, pn, np and nn isospin channels one after the
other. Each channel has its own running cross section in `xsec`, while the event
number runs on. The beam ids tell the channels apart, so the cross section can be
normalised per channel. JEWEL 2.6.0 writes 2212 for both beams and marks a neutron
only by its mass; the converters read the mass. They also remove the two beam
records (status 4 in 2.6.0, pT = 0) before the subtraction.

With JEWEL 2.6.0, keep `DOSUBTRACTION F` (the default) when you use these
converters. With `DOSUBTRACTION T`, JEWEL subtracts internally and stops writing
the scattering centres (status 3) that the converters need.

### Outgoing hard partons

Stock JEWEL does not write the hard-process partons. `tools/patch_jewel_partons.py`
patches the JEWEL 2.6.0 source (short HepMC output, the default) so that each
event also carries:

- the two outgoing matrix-element partons, as HepMC status 23, taken after
  PYTHIA's initial-state shower and before JEWEL's vacuum or medium final-state
  shower (the same definition in `jewel-*-vac` and `jewel-*-simple`);
- p̂_T (`PARI(17)`) in the event-scale field.

The hepyy recipe `jewel/2.6.0-custom` applies this patch and installs
`jewel-2.6.0-custom-simple` and `jewel-2.6.0-custom-vac` next to the stock
binaries:

```bash
hepyy install jewel/2.6.0-custom
jewel_prepare --tag partons --medium-bin jewel-2.6.0-custom-simple --vacuum-bin jewel-2.6.0-custom-vac
```

For a JEWEL built by hand, `python tools/patch_jewel_partons.py jewel-2.6.0.f
jewel-2.6.0-partons.f` makes the same change; rebuild afterwards.

Both converters then write the partons: `jewel_convert` as a `partons` tree
(eventID, pid, px, py, pz, energy) and `jewel_tables` as `<stem>.partons`; the
events table gets `pthat` and `n_partons`. Readers that select status 1, 3 and 4
(Rivet, both converters) are unaffected by the extra records.

### Flat tables: `jewel_tables`

`jewel_tables` writes the same subtraction as flat tables in parquet and/or
ROOT. Each input gives `<stem>.events` (one row per event) and
`<stem>.particles` (the subtracted particles with `tag`), and optionally
`<stem>.particles_raw` (status 1, 3 and 4 records). It needs `pyarrow` for
parquet (`.[parquet]`). It reads the HepMC2 text directly and is faster than the
pyhepmc path.

```bash
jewel_tables jewel_med_*.hepmc.gz --outdir tables/          # parquet, subtracted
jewel_tables run.hepmc --format both --particles both --dRmax 0.3
```

On the same file, `jewel_tables` and `jewel_convert --subtract-4mom` give
identical particles, tags and `cs_left_pt`; a test checks this.

## Run Directory Layout

For `--tag pt100 --samples both`, `jewel_prepare` writes:

```text
outputs/jewel_events/pt100/
  jewel_med/
    params.dat
    medium.params.dat
    manifest.yaml
    events/jewel_med_pt100.hepmc
    logs/jewel_med_pt100.log
    logs/jewel_med_pt100.stdout.log
    roots/jewel_med_pt100.root
    splitint/jewel_med_pt100.dat
    xsecs/jewel_med_pt100.dat
  jewel_vac/
    params.dat
    manifest.yaml
    events/jewel_vac_pt100.hepmc
    logs/jewel_vac_pt100.log
    logs/jewel_vac_pt100.stdout.log
    roots/jewel_vac_pt100.root
    splitint/jewel_vac_pt100.dat
    xsecs/jewel_vac_pt100.dat
```

`params.dat` is the patched JEWEL parameter file. `manifest.yaml` records the
executable, parameter file, HepMC output, ROOT output, logs, and PDF set names.
`jewel_run` reads this manifest instead of re-deriving paths.

## Command Help

`jewel_prepare --help`:

```text
Usage: python -m hepyy_utils.jewel.cli prepare [OPTIONS]

  Prepare self-contained JEWEL run directories.

Options:
  --samples TEXT            Samples to prepare: both, medium/PbPb, or
                            vacuum/pp.  [default: both]
  --out-dir TEXT            Output directory.  [default: outputs/jewel_events]
  --tag TEXT                Run tag. Default: current timestamp.
  --clean                   Remove selected tag/sample run directories before
                            preparing.
  --nevents TEXT            Override NEVENT for both samples.
  --nevents-medium TEXT     Override NEVENT for the medium/PbPb sample.
  --nevents-vacuum TEXT     Override NEVENT for the vacuum/pp sample.
  --ptmin TEXT              Override PTMIN for both samples.
  --ptmax TEXT              Override PTMAX for both samples.
  --etamax TEXT             Set or override ETAMAX for both samples.
  --job-id TEXT             Override NJOB for both samples.
  --job-id-medium TEXT      Override NJOB for the medium/PbPb sample.
  --job-id-vacuum TEXT      Override NJOB for the vacuum/pp sample.
  --medium-bin TEXT         Medium JEWEL executable.  [default:
                            jewel-2.6.0-simple]
  --vacuum-bin TEXT         Vacuum JEWEL executable.  [default:
                            jewel-2.6.0-vac]
  --template-dir DIRECTORY  Directory with JEWEL template .dat files.
  -h, --help                Show this message and exit.
```

`jewel_run --help`:

```text
Usage: python -m hepyy_utils.jewel.cli run [OPTIONS] RUN_PATH

  Run prepared JEWEL sample directories from manifests.

Options:
  --samples TEXT     Samples to run when RUN_PATH is a tag/root directory.
                     [default: both]
  --no-output-check  Do not require a non-empty HepMC file after JEWEL exits.
  -h, --help         Show this message and exit.
```

`jewel_convert --help`:

```text
Usage: python -m hepyy_utils.jewel.cli convert [OPTIONS] INPUT_HEPMC
                                               OUTPUT_ROOT

  Convert HepMC to ROOT track TTrees using uproot.

Options:
  --subtract-4mom / --no-subtract-4mom
                                  Apply JEWEL 4-momentum recoil subtraction.
                                  [default: no-subtract-4mom]
  --max-events INTEGER            Maximum events to convert.
  --final-status INTEGER          HepMC status used for final particles.
                                  [default: 1]
  --ghost-status INTEGER          HepMC status used for JEWEL thermal ghosts.
                                  [default: 3]
  --progress / --no-progress      Show a tqdm conversion progress bar.
                                  [default: progress]
  --event-info / --no-event-info  Write the event_info tree.  [default: event-
                                  info]
  --cs-mode [reference|legacy]    Constituent subtraction: reference (Rivet
                                  SubtractedJewelEvent port) or legacy
                                  (earlier hepyy-utils algorithm).  [default:
                                  reference]
  --dRmax FLOAT                   Reference mode: maximum particle-thermal
                                  distance in (y, phi).  [default: 0.5]
  --leftovers [keep|drop]         Reference mode: keep leftover thermal
                                  momenta as particles (tag 2, as the Rivet
                                  code) or drop them.  [default: keep]
  --thermal-pid [reference|intended|cast]
                                  PDG id of leftover thermal momenta:
                                  reference = always 211 (the shipped Rivet
                                  code), intended = pi+/pi-/pi0 1/3 each, cast
                                  = the C++ with the division fixed.
                                  [default: reference]
  --seed INTEGER                  Seed for the random --thermal-pid modes
                                  (combined with the file name).  [default: 0]
  -h, --help                      Show this message and exit.
```

`jewel_pipeline --help`:

```text
Usage: python -m hepyy_utils.jewel.cli pipeline [OPTIONS]

  Prepare and run JEWEL, optionally converting HepMC to ROOT.

Options:
  --samples TEXT                  Samples to prepare: both, medium/PbPb, or
                                  vacuum/pp.  [default: both]
  --out-dir TEXT                  Output directory.  [default:
                                  outputs/jewel_events]
  --tag TEXT                      Run tag. Default: current timestamp.
  --clean                         Remove selected tag/sample run directories
                                  before preparing.
  --nevents TEXT                  Override NEVENT for both samples.
  --nevents-medium TEXT           Override NEVENT for the medium/PbPb sample.
  --nevents-vacuum TEXT           Override NEVENT for the vacuum/pp sample.
  --ptmin TEXT                    Override PTMIN for both samples.
  --ptmax TEXT                    Override PTMAX for both samples.
  --etamax TEXT                   Set or override ETAMAX for both samples.
  --job-id TEXT                   Override NJOB for both samples.
  --job-id-medium TEXT            Override NJOB for the medium/PbPb sample.
  --job-id-vacuum TEXT            Override NJOB for the vacuum/pp sample.
  --medium-bin TEXT               Medium JEWEL executable.  [default:
                                  jewel-2.6.0-simple]
  --vacuum-bin TEXT               Vacuum JEWEL executable.  [default:
                                  jewel-2.6.0-vac]
  --template-dir DIRECTORY        Directory with JEWEL template .dat files.
  --convert / --no-convert        Convert generated HepMC files to ROOT after
                                  running.  [default: no-convert]
  --subtract-4mom-medium / --no-subtract-4mom-medium
                                  Apply 4-momentum subtraction when converting
                                  medium/PbPb samples.  [default:
                                  subtract-4mom-medium]
  --no-output-check               Do not require a non-empty HepMC file after
                                  JEWEL exits.
  --cs-mode [reference|legacy]    Constituent subtraction: reference (Rivet
                                  SubtractedJewelEvent port) or legacy
                                  (earlier hepyy-utils algorithm).  [default:
                                  reference]
  --dRmax FLOAT                   Reference mode: maximum particle-thermal
                                  distance in (y, phi).  [default: 0.5]
  --leftovers [keep|drop]         Reference mode: keep leftover thermal
                                  momenta as particles (tag 2, as the Rivet
                                  code) or drop them.  [default: keep]
  --thermal-pid [reference|intended|cast]
                                  PDG id of leftover thermal momenta:
                                  reference = always 211 (the shipped Rivet
                                  code), intended = pi+/pi-/pi0 1/3 each, cast
                                  = the C++ with the division fixed.
                                  [default: reference]
  --seed INTEGER                  Seed for the random --thermal-pid modes
                                  (combined with the file name).  [default: 0]
  -h, --help                      Show this message and exit.
```

`jewel_tables --help`:

```text
Usage: python -m hepyy_utils.jewel.cli tables [OPTIONS] INPUTS...

  Convert JEWEL HepMC to flat events/particles tables (parquet and/or ROOT).

  The particles are subtracted with the reference constituent subtraction and
  keep every tag, so the leftover convention is chosen at analysis time.

Options:
  --outdir DIRECTORY              Output directory.  [default: .]
  --format [parquet|root|both]    [default: parquet]
  --particles [cs|raw|both]       Subtracted particles, the raw record, or
                                  both.  [default: cs]
  --dRmax FLOAT                   Maximum particle-thermal distance in (y,
                                  phi).  [default: 0.5]
  --thermal-pid [reference|intended|cast]
                                  PDG id of leftover thermal momenta (tags 2,
                                  3).  [default: reference]
  --seed INTEGER                  Seed for the random --thermal-pid modes.
                                  [default: 0]
  --chunk INTEGER                 Events per write.  [default: 5000]
  --double                        float64 momenta (JEWEL writes 6 digits).
  -h, --help                      Show this message and exit.
```

## Development

```bash
python -m pip install -e '.[test]'
python -m pytest
```
