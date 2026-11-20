# JEWEL geometry analysis with hepyy

[`jewel_geometry_analysis.py`](jewel_geometry_analysis.py) and
[`jewel_geometry_analysis.ipynb`](jewel_geometry_analysis.ipynb) analyze saved
JEWEL HepMC and geometry CSV files. They do not generate new events.

Both examples use the same loader as `jewel_tables`, which calls
`hepyy.load("fastjet")` to load native FastJet through cppyy.
Activate a hepyy environment with a working cppyy runtime and
installed FastJet. If FastJet is missing, run `hepyy install fastjet`. See the
[hepyy installation guide](https://github.com/matplo/hepyy#installation) for
platform-specific runtime setup.

From the `hepyy-utils` checkout, install the analysis dependencies:

```bash
python -m pip install -e '.[parquet,jets]' matplotlib jupyterlab
```

The `jets` extra installs hepyy. FastJet itself is installed with
`hepyy install fastjet` and loaded automatically when jet finding is requested.

## Run the Python example

```bash
# Portable one-event recoil fixture included in this repository:
python examples/jewel_geometry_analysis.py --fixture

# Use completed attempts from the local medium sample when available;
# otherwise use the fixture:
python examples/jewel_geometry_analysis.py

# Your own saved event files, each with its adjacent geometry sidecar:
python examples/jewel_geometry_analysis.py 'runs/*/events/*.hepmc' \
  --outdir outputs/my_geometry_analysis \
  --radius 0.4 --jet-ptmin 20 --jet-eta-max 3.1 --match-delta-r 0.3
```

The default output directory is `outputs/jewel_geometry_example`. It contains
ROOT and Parquet tables, `matches.csv` for all hard legs,
`selected_matches.csv` for the analysis selection, `analysis_metadata.json`
recording the actual FastJet backend and settings, and PNG/PDF figures.
Running again replaces those derived outputs; the input event files are
unchanged. Supply another `--outdir` to keep several analyses.

## Run the notebook

```bash
jupyter lab examples/jewel_geometry_analysis.ipynb
```

Select the kernel belonging to the same hepyy environment. The notebook uses
the sibling Python file for the analysis functions. Its configuration cell
lets you select input files, subtraction, jet radius, matching radius, and
analysis cuts. By default, it uses completed local sample attempts when
available and otherwise the portable fixture. It writes to
`outputs/jewel_geometry_example_notebook`.

## Processing order

1. Validate the event/geometry pair and preserve the run and event IDs.
2. Apply the selected thermal subtraction with `hepyy-utils`.
3. Cluster the visible final-state constituents with hepyy FastJet.
4. Match the two shower-start hard legs to the full positive-pT jet
   collection, before any jet pT or eta analysis cuts.
5. Set `analysis_selected` from the analysis cuts without changing the
   assignments. Retain the complete collection in `jets_all` and its selected
   subset in `jets`.
6. Join each leg's production point and path estimates to its assigned jet.

`matched=true, analysis_selected=false` means a jet was assigned but failed
the analysis cuts. Its kinematics and path association remain available.
`matched=false` means no assignment was found. The ambiguity flag records
multiple or shared candidates. Changing analysis cuts preserves assignments;
changing the jet definition or matching radius can change them.

The path lengths are straight-ray estimates along the initial hard-leg
direction, not a measured shower trajectory or an ancestry tag.
`L_hot_fm` is a collision-frame 3D distance; `L_hot_T_fm` is its transverse
projection. These need not equal a thickness in the local medium rest frame.

## Where recoil subtraction happens

For the default `subtraction="utils"` / `--subtraction utils`, use generation
cards containing:

```text
KEEPRECOILS T
WRITESCATCEN T
WRITEDUMMIES T
DOSUBTRACTION F
```

`KEEPRECOILS T` retains the medium recoil contribution. The analysis uses the
status-3 thermal references to subtract the pre-scattering thermal momentum
from nearby final-state particles before jet finding. It does not simply
delete every recoil particle: the momentum transferred by the jet contributes
to medium response. Beam records and dummy entries are excluded from the jet
constituents, as are neutrinos.

These examples use the utility's reference constituent-subtraction convention,
including thermal leftovers tagged 2/3, with subtraction distance 0.5 in
rapidity/azimuth. This subtraction distance is distinct from the hard-leg to
jet matching radius in pseudorapidity/azimuth. The convention is recorded in
the output metadata. See the [subtraction documentation](../README.md#thermal-momentum-constituent-subtraction).

JEWEL 2.6 also provides generation-side subtraction with `DOSUBTRACTION T`.
That is a separate option; it disables the thermal-reference and dummy output.
For already-subtracted events, choose `SUBTRACTION = "none"` in the notebook
or `--subtraction none` in the script. Check the generation card/log: absence
of thermal records alone does not establish whether subtraction was performed.

The reference constituent-subtraction method is described in
[Milhano and Zapp, EPJC 82 (2022) 1010](https://doi.org/10.1140/epjc/s10052-022-10954-1).
