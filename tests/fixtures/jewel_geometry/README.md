# JEWEL geometry reference samples

These are generated events from JEWEL 2.6.0 with the `partons-v1+geometry-v1`
patches in `hepyy-recipes/jewel/2.6.0-custom.sh`. The recoil and long-output
samples also use `perf-v1`. They were built and checked on macOS arm64 with
GNU Fortran 16.2.0 and LHAPDF 6.5.5, using CT14nlo (PDFSET 13100).

Each directory contains the exact parameter cards, a gzip-compressed HepMC2
file, and its direct generator CSV output. The CSV is intentionally unsealed:
the workflow adds the optional HepMC digest after validating the complete pair.
`validation.json` records the recipe hash, uncompressed HepMC hashes, saved RNG
hashes, and the paired-run results. `CUSTOM-PATCHES.txt` records source hashes.

| Sample | Accepted events | Settings |
|--------|-----------------|----------|
| `vac` | 3 | Vacuum, short HepMC, NJOB 901 |
| `simple` | 1 | Medium, short HepMC, NJOB 902 |
| `recoils` | 1 | Medium, weighted, retained recoils/thermal records/dummies, NJOB 903 |
| `long` | 1 | Medium, long HepMC without added status-23 records, NJOB 902 |

The native validation additionally checked the performance builds and mixed
isospin (7 accepted events from 8 attempts). All seven export-on/off pairs
had identical HepMC bytes and final RNG state. Halving the integration time
step from 0.02 to 0.01 fm/c changed the largest `L_hot` by 0.0151 fm in the
medium reference event. Refusing an existing CSV preserved existing HepMC.

These small samples test instrumentation and I/O, not statistical physics
agreement. The older installed custom binary and the new export-disabled
binary both stalled after one event for the three-event NJOB 902 medium run.
Weighted recoil seeds 901/902 also stalled with export disabled; the reference
uses seed 903. This separate generator issue was not changed by this work.

Regenerate with `hepyy-recipes/tests/validate_jewel_geometry.py`, supplying a
stock JEWEL source, LHAPDF prefix, a new work directory, and `--fixtures-dir`.
The helper can reuse matching numerical tables with `--tables-dir`; otherwise
JEWEL computes them. Run `tests/jewel/test_geometry_reference.py` to check the
fixture joins, ROOT/Parquet conversion, and final-jet matching.
