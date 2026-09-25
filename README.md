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

Install the utility package:

```bash
hepyy recipe update
hepyy install hepyy-utils
module load hepyy-utils
```

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
`tracks`, with array branches for event id, momentum components, energy, and
particle id.

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
                            jewel-2.4.0-simple]
  --vacuum-bin TEXT         Vacuum JEWEL executable.  [default:
                            jewel-2.4.0-vac]
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
                                  jewel-2.4.0-simple]
  --vacuum-bin TEXT               Vacuum JEWEL executable.  [default:
                                  jewel-2.4.0-vac]
  --template-dir DIRECTORY        Directory with JEWEL template .dat files.
  --convert / --no-convert        Convert generated HepMC files to ROOT after
                                  running.  [default: no-convert]
  --subtract-4mom-medium / --no-subtract-4mom-medium
                                  Apply 4-momentum subtraction when converting
                                  medium/PbPb samples.  [default:
                                  subtract-4mom-medium]
  --no-output-check               Do not require a non-empty HepMC file after
                                  JEWEL exits.
  -h, --help                      Show this message and exit.
```

## Development

```bash
python -m pip install -e '.[test]'
python -m pytest
```
