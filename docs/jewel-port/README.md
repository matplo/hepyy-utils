# JEWEL 2.6.0 → standalone C++ with Pythia8

This is a source-based implementation plan, not an implemented or validated C++ generator. The target is a standalone C++ JEWEL evolution engine with Pythia8 input and hadronization adapters. A later JETSCAPE adapter should call the same engine. Pythia8's standard final-state shower is not a replacement for JEWEL's coupled radiation/scattering evolution.

## Audited baseline and reproducibility

The inventory uses the unmodified `.stock` copies in the unpacked JEWEL 2.6.0 source used for our custom build. [source-manifest.json](source-manifest.json) records SHA-256 hashes and line counts of the actual files, including the modified Pythia6 distributed by JEWEL. The core and medium hashes must match the stock hashes in `hepyy-recipes/jewel/2.6.0-custom.sh` before implementation starts. The local custom build adds `partons-v1`, `geometry-v1`, and optional `perf-v1`; these are separate from the upstream physics baseline.

The index covers **81 core Fortran units, 24 simple-medium units, 20 vacuum-medium units and one exponential-integral helper**. [routines.csv](routines.csv) gives every routine's source span, proposed C++ component, COMMON blocks, direct CALL statements and direct Pythia references. [pythia6-call-sites.csv](pythia6-call-sites.csv) identifies **281 reference sites involving 11 Pythia symbols**, with each symbol's definition line in the distributed Pythia6 file. The source spans are bounded by the next routine declaration and may include separator comments.

Regenerate from an unpacked release/build directory:

```bash
python tools/inventory_jewel.py /path/to/jewel-2.6.0 --outdir docs/jewel-port
```

This is a lexical source index, not a compiler-resolved transitive call graph. It excludes commented code and prefers `.stock` backups. COMMON usage, Pythia's internal calls, and indirect state dependence require semantic review. A count of 11 directly referenced APIs does **not** imply a small port: JEWEL directly manipulates Pythia's event arrays throughout its evolution.

The compatibility target for Pythia8 interfaces was checked against the locally installed **8.317** headers and manual. Pin the actual version/build and data files in reference manifests. The package version of a native wheel is distinct from its physics-library version.

## What the source actually does

`GENEVENT` samples the medium and vertex, calls `PYEVNT`, imports/reorganizes its event, finds hard-process lines, establishes colour, initializes hard and MPI virtualities, calls `MAKECASCADE`, constructs strings, and finally calls `PYEXEC`. Optional thermal subtraction and on-shell projection precede HepMC output.

`INITPYTHIA` enables ISR, controls MPI, disables Pythia final-state showering (`MSTP(71)=0`) and immediate hadronization (`MSTP(111)=0`), requests retained history (`MSTP(125)=2`), and sets PDFs, process selection, decay switches, weighting and a fragmentation tune. Do not translate these integer settings blindly into an arbitrary modern Pythia tune.

`INTERPRETPYTHIAEVENT` contains explicit assumptions about entries 101–106 and subsequent records. It walks ISR ancestry, derives production/formation times and handles emitted-parton virtualities. `FINDSPECLINES` uses process-dependent hard-record conventions. A Pythia8 adapter must recover their **physical meaning** from process/event history; matching array offsets or copying status codes is invalid.

JEWEL 2.6.0's release notes explicitly add colour coherence (`COHLENGTHFAC`, `PCOHREJ`, `COHSCAT`), six angular-ordering settings (0–5), changed time keeping and LPM handling, different shower/scattering couplings, optional event subtraction, and updated fragmentation settings. These belong in the port and validation matrix. LPM radiation coherence and unresolved colour-dipole scattering are distinct requirements.

## Routine ownership and porting work

Each entry in the linked inventory is assigned to one of these components; names below refer to the original routines.

| Component | Routines / responsibilities | Port and acceptance test |
|---|---|---|
| RunDriver | `JEWEL`, `INIT`, `GENEVENT`, `PRINTLOGO`, `PRINTTIME` | Typed configuration, event lifecycle, rejection counters, weights, checkpointing. Match accepted/rejected bookkeeping and channel normalization. |
| Pythia8InputAdapter | `INITPYTHIA`, `INTERPRETPYTHIAEVENT`, `FINDSPECLINES`, `SETCOLOUR` | Rewrite around Pythia8 process/event history; stable IDs instead of offsets. Validate hard legs, ancestry, incoming/outgoing identities, beam remnants and colour before evolving anything. |
| InitialVirtualities | `FINDVIRTUALITIES`, `FINDMPIVIRTUALITIES`, `GETTHETAM`, `MAKEMASSLESS` | Port virtuality assignment, first-splitting and momentum reshuffling rules. Compare controlled two-leg and MPI inputs, including kinematic rejection and massless limits. |
| ShowerEvolution | `MAKECASCADE`, `MAKEBRANCH`, `MAKESPLITTING`, `REJECTSPLITTING`, `MAKEINSPLIT` | Preserve scheduling, branching, daughter-mass rejection, angular ordering and resets. Replay tagged random draws and compare complete state after each accepted transition. |
| ScatteringEvolution | `DOINSTATESCAT`, `DOCOHSCATTERING`, `DOFISTATESCAT`, `GETNEWMASS`, `GETPNORAD1`, `GETQVEC`, `DOKINEMATICS`, `GETDELTAT` | Port scattering competition, recoil kinematics, formation-time/LPM treatment and unresolved dipoles. Test no-medium, one-scatter, multiple-scatter and unresolved/resolved dipole limits. |
| SplittingKernels | `GETPROBA`, `GETSUDAKOV`, `GETINSUDAKOV`, `DERIV`, `GETSPLITI`, `GETINSPLITI`, `GETINSUDAFAST`, `GETINSUDARED`, `GETMASS`, `GENERATEZ`, five `INTP*` integrals, `PQQ`, `PGQ`, `PGG`, `PQG`, `ALPHAS`, `SPLITFNCINT`, `INSUDAINT` | Preserve formulae, integration limits, tables, interpolation and acceptance envelopes first. Validate deterministic grids and sampled splitting distributions before optimizing. |
| PartonicPdfKernels | `GETPDF`, `GETPDFXINT`, `GETPDFXINTEXACT`, `PDFINT` | These are JEWEL's parton-in-parton evolution integrals, **not proton PDFs from LHAPDF**. Port them; compare all QQ/GQ/QG/GG channels and grid boundaries. |
| ScatteringKernels | `GETXSECINT`, `GETSSCAT`, `SCATPRIMFUNC`, `GETT`, `XSECINT` | Port screened scattering and transfer sampling; compare integrated/differential rates, support and rejection probabilities. |
| Numerics | `EI`, `EIX`, `EIXINT`, `ODEINT`, `RKSTEPPER`, `RK4STEP`, `POISSONIAN` | Initially preserve numerical algorithms and tolerances. Test tails, endpoints, interpolation/extrapolation and special-function domains; library replacements need independent comparisons. |
| EventState | `CLEANUP`, `COPYLINE`, `COMPRESSEVENT`, `GETPOSITION`, `ISHADRON`, `ISDIQUARK`, `ISLEPTON`, `ISPARTON`, `ISQORG` | Replace shared arrays with owned state and stable references. Check genealogy after compaction, classifications and propagation units. |
| ColourBuilder | `MAKESTRINGS`, `MAKESTRINGS_VAC`, `MAKESTRINGS_MINL`, `ISPRIMSTRING`, `ISSECSTRING`, `ISPRIMHADRON` | Preserve string-construction choices and recoil colour handling; produce valid Pythia8 colour tags. Compare endpoints/topology before comparing hadrons. |
| OutputAdapter | `PEVREC`, `PUTPARTICLESONSHELL`, `CONVERTTOHEPMC` | Explicit diagnostic output, optional on-shell projection and HepMC mapping. Preserve thermal references, event weights and beam channel; compare four-momenta and flags before/after projection. |
| SimpleMedium / VacuumMedium | All routines in their respective files, individually indexed | Keep the 20 common entry points, including temperature, density, screening, scatterer sampling, geometry and bounds. The simple medium additionally has `NPART`, `NTHICK`, `CALCTA`, `CALCXSECTION`. Port the optical geometry first; vacuum must exercise the same engine with zero scattering. |

`subtraction.C` is already C++ and can be adapted instead of translated. Its eight functions are `MyDistComp` (line 28), `sqr` (36), `readEvent` (40), `readThermals` (69), `buildPairs` (93), `doSubtraction` (116), `collectResult` (150), and the Fortran entry point `subtract_thmom_` (201). Separate its array/ABI adapters from the subtraction kernel. Preserve the source convention with golden fixtures; do not assume all utility subtraction options and on-shell projections are interchangeable. The first C++ milestone can emit unsubtracted events and use existing hepyy-utils analysis.

## Pythia6 → Pythia8 replacement map

| Existing dependency | Replacement | Compatibility work |
|---|---|---|
| `PYINIT` | Pythia8 settings + `Pythia::init()` | Map beam species, energy, processes, PDFs, cuts, decay controls, tune and coupling choices explicitly. |
| `PYEVNT` | `Pythia::next()` + input adapter | Disable native final-state evolution owned by JEWEL and hadronization at this stage; configure ISR/MPI deliberately. Pythia8 ISR/MPI and its event history are not Pythia6 equivalents. |
| `PYEXEC` | Separate Pythia8 hadronization instance with a populated event and `forceHadronLevel()` | Supply a colour-complete state including appropriate remnants/recoils. Do not call `next()` on this instance and generate a new collision. Match decays and string parameters separately. |
| `PYROBO` | Tested four-vector rotation/boost helper (Pythia8 `Vec4`/`RotBstMatrix` or engine-owned math) | Preserve boost signs, rotation order, ranges, masses and transformed vertices. Golden tests for every operation pattern. |
| `PYR` | Engine RNG interface; optionally Pythia8 `RndmEngine` adapter | Reference runs use recorded draws or a compatible reference RNG. Separate streams only after parity, because changing draw order changes histories. |
| `PYRGET`, `PYRSET` | Explicit RNG state serialization/checkpoint | Version and checksum the state; test restart equivalence. Old Fortran checkpoint files need a separate importer if retained. |
| `PYMASS` | `ParticleData::m0` or matched particle table | Compare masses and thresholds explicitly; different defaults change kinematics. |
| `PYCOMP` | PDG-keyed Pythia8 particle/decay configuration | Compressed Pythia6 table indices have no portable correspondence. |
| `PYP` | Typed kinematic getters/computations | Map each requested selector (mass, pT, rapidity/pseudorapidity, etc.) from its definition, not just its integer value. |
| `PYLIST` | Engine diagnostics / Pythia8 event listing | Diagnostics only; no physics substitution. |

Beyond those direct calls, the bundled `pythia6425mod-lhapdf6.f` identifies three customizations in its header: 23,000-entry records, LHAPDF/nuclear-PDF support, and event weighting. Its active `PYEVWT` at line 80201 implements `WTXS = (pT²)^(WEIGHTEX/2)` via `/WEXPO/`. Preserve selection bias and compensating weights together. Pythia8 exposes `UserHooks::canBiasSelection`, `biasSelectionBy`, and `biasedSelectionWeight`; test weighted cross sections, not just normalized shapes. Do not replace an importance-sampling bias with a modification of the physical cross section.

Use LHAPDF's C++ API/Pythia8 PDF interface for **beam** PDFs. Preserve proton/neutron isospin mapping, nuclear-PDF conventions, member IDs, scales and alpha_s. Do not double-apply nuclear averaging/isospin. Test pp, pn, np and nn channels separately, including their weights and cross sections.

### Concrete first Pythia8 input configuration

For the reduced hard-dijet adapter milestone, start with explicit settings
`HadronLevel:all = off`, `PartonLevel:FSR = off`, `PartonLevel:ISR = off`
and `PartonLevel:MPI = off`. Enable the required hard-QCD subprocesses and
set beam IDs, energy, pT-hat range and PDF member explicitly. This is a
controlled adapter test, not the JEWEL 2.6.0 default physics configuration.
Keep event consistency checks enabled. Turn ISR and MPI on only in their
separate validation stages; native FSR remains disabled for partons evolved
by JEWEL. Handle resonance radiation/decays as an explicit later policy.

Create an input snapshot with hard-process role labels, incoming fractions,
weights, cross-section metadata, full required ancestry and colour tags.
Do not infer the hard pair by simply choosing the two highest-pT partons.
For ISR, explicitly map each imported branch's energy-sharing variable,
virtuality, partners and production/formation time to the JEWEL convention.
Pythia8's shower recoil/ordering scheme differs, so unsupported histories
must fail visibly during development rather than silently losing branches.

Use a separate hadronization instance. Set its fragmentation, particle-mass,
decay and colour-reconnection policy explicitly; preserve the assembled
JEWEL string topology before exploring alternative reconnection models.
Implement closure tests before enabling full-event fragmentation. Do not
claim identical hadrons simply because both versions use string fragmentation.

### Shared state that must disappear from the engine

- `/PYJETS/`: event count and K/P/V arrays. Replace with a stable-ID graph, explicit statuses, PDG IDs, momentum, production point, parents/daughters, and colour/anticolour. Preserve references during deletion/compaction.
- `/PYDAT1/`, `/PYDAT3/`: settings and particle/decay tables. Split physics configuration from runtime counters and particle properties.
- `/PYSUBS/`, `/PYPARS/`: subprocess selection, cuts, generator metadata and weights. Replace with adapter configuration and per-event metadata.
- `/PYDATR/`: RNG state. Own explicitly.
- JEWEL-owned `/PYTHIAPARAMS/` is not a Pythia common block despite its name. `/TIME/`, `/ANGOR/`, `/EVOLTIMES/`, `/COLOUR/`, `/STORESCATCEN/`, `/SPECLINES/` and `/DISC/` become engine state; numerical grids become immutable shared tables where possible. `/WEXPO/` crosses the Pythia weighting boundary.

## Standalone interfaces and first executable

Build a CMake C++17 library plus a CLI. Core dependencies should be standard C++ and a small tested numerical layer. Pythia8, LHAPDF and HepMC3 belong in adapters; ROOT/TGlauberMC and JETSCAPE are optional integrations. Python/cppyy can expose the C++ engine later but must not be required to run the executable.

The proposed contracts are:

```cpp
struct Medium { virtual MediumSample sample(const SpaceTime&) const = 0; };
struct Random { virtual double uniform() = 0; };
struct InitialEvent;  // stable IDs, ancestry, colour, momenta, vertices, weights
struct EvolutionResult; // evolved graph, recoils, thermal references, history
EvolutionResult evolve(const InitialEvent&, const Medium&, Random&, const Config&);
```

These are interface sketches, not complete compilable declarations. The engine must also expose medium sampling bounds, event geometry and per-run tabulation dependencies represented by the current medium interface. Avoid a Pythia8 event object as the engine's persistent storage.

Store optional branch/scatter history with stable ancestor IDs, space-time points, emitted/recoiling momenta and formation intervals. Keep our existing `geometry-v1` reference-ray estimates separately. Even with richer histories, a reconstructed jet still has no unique trajectory; any constituent/ancestor-based path observable must state its weighting and matching definition.

## Ordered milestones and acceptance gates

| Stage | Deliverable | Gate before proceeding |
|---|---|---|
| 0 — reference harness | Frozen stock/custom binaries, hashes, cards, PDF sets, deterministic numerical probes, initial-state snapshots and RNG trace protocol | Reproducible weighted baseline; distinguish stock, instrumentation and performance patches. Existing five events are smoke data, not a physics-validation sample. |
| 1 — state, medium, kernels | C++ event state, RNG adapter, vacuum/simple-medium interfaces, splitting/scattering tables and math | Differential tests against Fortran for every public kernel; endpoint and out-of-domain behavior accounted for. |
| 2 — evolution | Standalone executable consuming controlled partonic snapshots; vacuum, static medium, then simple expanding medium | Step-level replay agreement where the same algorithm/draw sequence is used; conservation including scatterer input and recoil output, genealogy and colour consistency. |
| 3 — hadronization | Pythia8 colour-complete event export and separate hadronizer | No unexplained failures; quantify Pythia6→8 fragmentation/decay differences using equivalent partonic states. These differences are not evidence that the core port failed. |
| 4 — collision input | Pythia8 hard dijets, initially ISR/MPI disabled; then ISR import, ISR quenching and MPI support in distinct steps | Hard-process distributions first; next history/formation-time assignments and colour; finally full observables. An ISR/MPI-off milestone is explicitly reduced functionality. |
| 5 — feature completion | Required colour-coherence and angular-ordering modes, recoil modes, EEJJ, photon/Z/W+jet and Drell–Yan channels, weighted generation, optional generation subtraction | Feature matrix with supported/unsupported settings and channel-specific regression suites. Do not advertise complete 2.6.0 equivalence before these gates. |
| 6 — alternative integrations | TGlauberMC geometry adapter and later JETSCAPE module | Compare against the validated optical-medium baseline; document the separate model change introduced by fluctuating geometry or different transport scheduling. |

TGlauberMC provides geometry, not by itself the temperature field, thermal momentum distribution, screening, flow or time evolution needed by JEWEL. Preserve those interfaces and calibrate the geometry-to-medium prescription separately. A JETSCAPE wrapper must preserve formation-time state, colour, medium queries and recoil ownership across scheduling boundaries; it is not merely a build-system plugin.

## Validation matrix and acceptance policy

1. **Numerical parity:** probe physically supported parameter grids, thresholds and boundaries. Record absolute and relative errors; choose kernel-specific tolerances based on the Fortran integrator/interpolation accuracy. Do not silently “improve” an approximation before parity.
2. **Event invariants:** enforce finite values, valid graph links and colour closure. Check energy–momentum with the correct system boundary: a jet alone need not conserve momentum while exchanging it with the medium. Include thermal inputs, recoils, discarded records and optional projection in accounting. Test positive formation intervals and time ordering.
3. **Physics switches:** vacuum/zero density; static slabs of several lengths and temperatures; expanding simple medium; elastic-only controlled tests where supported by an instrumented harness; coherence on/off; all ANGORD modes; ISR/MPI on/off; recoils kept/removed. Document any harness-only switch rather than claiming stock support.
4. **Parton-level comparisons:** scattering counts and transfer distributions, flavour changes, radiation multiplicity, z/virtuality/angle/formation-time distributions, energy loss and broadening conditional on initial energy/flavour/path. Separate changing Pythia input from changing the engine.
5. **Hadron/jet comparisons:** pp spectra, multiplicities and fragmentation first; then medium/vacuum ratios, dijet imbalance, acoplanarity, radial shapes and recoil-sensitive substructure. Use several jet radii, hard scales, geometries/centralities and independent seeds. Reuse hepyy-utils thermal subtraction and match full jet phase space before analysis cuts.
6. **Statistics and normalization:** retain event weights, sums of weights and squared weights, cross sections, rejected-event accounting and effective sample sizes. Predefine binning, covariance treatment and tolerances. Increase samples until reference statistical uncertainty is smaller than the desired fidelity; five events or a common seed is insufficient. Avoid tuning away a coding discrepancy.
7. **Separate judgments:** core-port parity, Pythia6→8 generator differences, medium-model changes, and agreement with experimental data are four different validation questions. A good fit to data cannot establish faithful translation.

No release date or event-count promise follows from this inventory. The largest unresolved design work is the Pythia8 ISR/MPI history mapping and colour-complete hadronization boundary. The first implementation should target stages 0–2, with explicit reduced scope; preserve a Fortran reference executable throughout development.

## References and reuse constraints

- Audited source files and exact hashes: [source-manifest.json](source-manifest.json); release-provided `release_note-2.6.0.txt`, `README`, `GUIDELINES`, `gpl-2.0.txt` and the Pythia modification header must accompany the implementation review. This plan does not redistribute upstream source.
- [JEWEL perturbative framework](https://arxiv.org/abs/1212.1599), [geometry](https://arxiv.org/abs/1312.5536), [medium response](https://arxiv.org/abs/1707.01539), [subtraction](https://arxiv.org/abs/2207.14814). The 2.6.0 release source/notes take precedence over older descriptions when they differ.
- [Pythia8 guide](https://arxiv.org/abs/2203.11601) and [Pythia API](https://pythia.org/doxygen/pythia8307/classPythia8_1_1Pythia.html). Exact signatures were additionally checked in the local 8.317 `Pythia.h`, `UserHooks.h` and bundled `HadronLevelStandalone.html`; freeze the chosen release before coding adapters.
- The distributed Pythia6 is explicitly marked as modified for JEWEL. Keep that implementation as a reference backend; do not treat it as a reusable standalone Pythia distribution. Preserve applicable upstream licenses and acknowledgments when translating/reusing source; distinguish a research port from an official JEWEL release.
