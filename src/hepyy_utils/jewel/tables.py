"""
JEWEL HepMC2 (.hepmc / .hepmc.gz) -> flat tables in Parquet, ROOT or HDF5.

Per input file <stem>.hepmc[.gz] it writes (rows in event order, join on event_id):
  events         one row per event: event_id, ievent, weight, pthat, xsec_pb, xsec_err_pb, the other
                 E/H/F header numbers, beam1_pid/beam2_pid (PDG ids of the first two particle records:
                 JEWEL's colliding nucleons, which identify the pp/pn/np/nn isospin channel),
                 counts n_final/n_thermal/n_dummy/n_cs/n_raw, cs_thermal_pt, cs_left_pt
  particles      constituent-subtracted event (subtraction.subtract): event_id, px, py, pz, e, pid, tag
  particles_raw  raw record, HepMC status 1/3/4 (dummies included, beams removed): event_id, px, py, pz, e, pid, status
  partons        outgoing hard partons, HepMC status 23, written by JEWEL patched with
                 patch_jewel_partons.py (two per event, before the final-state shower):
                 event_id, ipart, px, py, pz, e, pid. Written only when the input has them.
  geometry       two leg rows from an associated JEWEL geometry sidecar, keyed by run_id,
                 event_id and leg_id. The events table gains run_id and production geometry.
  jets_all       optional full collection of positive-pT anti-k_t jets, keyed by run_id, event_id and jet_id.
  jets           subset of jets_all passing the analysis pT and pseudorapidity cuts.
  jet_matches    optional shower-start leg to jets_all assignments, keyed like geometry.
Parquet: <stem>.events.parquet, <stem>.particles.parquet, ...  ROOT: <stem>.root with one TTree per table.
HDF5: <stem>.h5 with one group per table and one resizable dataset per column.

  jewel_tables run*.hepmc.gz [--format parquet|root|both|h5|all] [--particles cs|raw|both]
                         [--dRmax 0.5] [--thermal-pid reference|intended|cast] [--seed 0]
                         [--chunk 5000] [--outdir .] [--double] [--geometry FILE] [--jets]

--thermal-pid: PDG id of leftover thermal momenta (tags 2, 3); see subtraction.py. Random modes are
reproducible: one generator per input file, seeded from (--seed, file name).
The settings are stored with the output (Parquet metadata key 'jewel_cs'; ROOT TObjString
'jewel_cs'; HDF5 root attribute 'jewel_cs'). 'both' means Parquet + ROOT; 'all' adds HDF5.

pthat: taken from the HepMC event scale (E line). Stock JEWEL writes 0 there (stored as NaN);
JEWEL patched with patch_jewel_partons.py writes PARI(17).
"""
import gzip
import json
import math
import os
import time
import zlib
from contextlib import nullcontext
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np

from . import geometry as geometry_csv
from . import subtraction

E_KEYS = ("event_id", "n_mpi", "scale", "alpha_qcd", "alpha_qed", "process_id")
H_KEYS = ("hi_n_hard", "hi_npart_proj", "hi_npart_targ", "hi_ncoll", "hi_nspec_n", "hi_nspec_p",
          "hi_n_nwounded", "hi_nwounded_n", "hi_nwounded_nwounded", "hi_b", "hi_psi", "hi_ecc",
          "hi_sigma_nn")
F_KEYS = ("pdf_id1", "pdf_id2", "pdf_x1", "pdf_x2", "pdf_scale", "pdf_xf1", "pdf_xf2")
INT_KEYS = {"event_id", "ievent", "n_mpi", "process_id", "n_final", "n_thermal", "n_dummy", "n_cs", "n_raw",
            "beam1_pid", "beam2_pid", "n_partons"}
JET_IDS = ("event_id", "jet_id", "jet_rank")
JET_FIELDS = (*JET_IDS, "run_id", "px", "py", "pz", "e", "pt", "eta", "phi", "analysis_selected")


def read_hepmc2(path):
    """Yield (header dict, particle array [status, pid, px, py, pz, e] in GeV) per event."""
    path = os.fspath(path)
    opener = gzip.open if path.endswith(".gz") else open
    unit, hdr, parts, beams = 1.0, None, None, []

    def done():
        a = np.array(parts, dtype=np.float64).reshape(-1, 6)
        a[:, 2:] *= unit
        # JEWEL writes the two colliding nucleons first. Each job generates the pp, pn, np, nn
        # channels one after the other, each with its own running cross section in the C line,
        # while the event number runs on: this pair marks the channel. JEWEL 2.6.0 writes 2212 for
        # both and marks a neutron only by its mass, hence nucleon_pid.
        b = beams + [(0, 0.0)] * (2 - len(beams))
        hdr["beam1_pid"], hdr["beam2_pid"] = (subtraction.nucleon_pid(*b[0]), subtraction.nucleon_pid(*b[1]))
        return hdr, a

    with opener(path, "rt") as f:
        for line in f:
            c = line[:1]
            if c == "P":
                t = line.split()
                parts.append((t[8], t[2], t[3], t[4], t[5], t[6]))
                if len(beams) < 2:
                    beams.append((int(t[2]), float(t[7])))
            elif c == "E":
                if hdr is not None:
                    yield done()
                t = line.split()
                nrand = int(t[11])
                hdr = {k: np.nan for k in ("xsec_pb", "xsec_err_pb") + H_KEYS + F_KEYS}
                hdr["event_id"] = int(t[1])
                hdr.update(zip(E_KEYS[1:], map(float, t[2:7])))
                hdr["weight"] = float(t[13 + nrand]) if int(t[12 + nrand]) > 0 else 1.0
                parts, beams = [], []
            elif c == "U":
                unit = 1.0 if line.split()[1].upper() == "GEV" else 1e-3
            elif c == "C":
                t = line.split()
                hdr["xsec_pb"], hdr["xsec_err_pb"] = float(t[1]), float(t[2])
            elif line[:2] == "H ":
                hdr.update(zip(H_KEYS, map(float, line.split()[1:14])))
            elif c == "F":
                hdr.update(zip(F_KEYS, map(float, line.split()[1:8])))
        if hdr is not None:
            yield done()


def validate_geometry_event(path, hdr, particles, legs):
    """Check the sidecar event against the HepMC header and matrix-element particles."""
    event_id = hdr["event_id"]
    if legs is None or legs[0]["event_id"] != event_id:
        found = "end of sidecar" if legs is None else f"event {legs[0]['event_id']}"
        raise ValueError(f"{path}: expected geometry for HepMC event {event_id}, found {found}")
    # JEWEL writes weight with E0.6 and status-23 four-vectors with E0.8.
    if not math.isclose(hdr["weight"], legs[0]["weight"], rel_tol=5.1e-6):
        raise ValueError(f"{path}: geometry weight disagrees with HepMC for event {event_id}")
    hard = particles[particles[:, 0] == 23]
    if len(hard):
        me = [[leg[key] for key in geometry_csv.ME_FIELDS] for leg in legs]
        if (len(hard) != 2 or not np.array_equal(hard[:, 1], [leg["pid"] for leg in legs])
                or not np.allclose(hard[:, 2:], me, rtol=5.1e-8, atol=0)):
            raise ValueError(f"{path}: geometry matrix-element legs disagree with HepMC for event {event_id}")


def iter_events_with_geometry(path, geometry_events):
    """Yield (HepMC header, particles, two geometry legs), validating correspondence."""
    geometry_events = iter(geometry_events)
    for hdr, particles in read_hepmc2(path):
        legs = next(geometry_events, None)
        validate_geometry_event(path, hdr, particles, legs)
        yield hdr, particles, legs
    extra = next(geometry_events, None)
    if extra is not None:
        raise ValueError(f"{path}: geometry has extra event {extra[0]['event_id']} absent from HepMC")


class Tables:
    """Chunked Parquet, ROOT and HDF5 writer, with the same columns in each format."""

    def __init__(self, stem, fmt, meta):
        self.stem, self.fmt, self.pq, self.root, self.trees = stem, fmt, {}, None, set()
        self.h5 = None
        self.meta = json.dumps(meta)

    def write(self, name, cols):
        if self.fmt in ("parquet", "both", "all"):
            import pyarrow as pa
            import pyarrow.parquet as pq
            table = pa.table(cols).replace_schema_metadata({"jewel_cs": self.meta})
            if name not in self.pq:
                self.pq[name] = pq.ParquetWriter(f"{self.stem}.{name}.parquet", table.schema,
                                                 compression="zstd")
            self.pq[name].write_table(table)
        if self.fmt in ("root", "both", "all"):
            import uproot
            if self.root is None:
                self.root = uproot.recreate(f"{self.stem}.root")
                self.root["jewel_cs"] = self.meta                 # TObjString
            if name not in self.trees:
                self.root.mktree(name, {k: "string" if v.dtype.kind == "U" else v.dtype
                                       for k, v in cols.items()})
                self.trees.add(name)
            if len(next(iter(cols.values()))):
                self.root[name].extend(cols)
        if self.fmt in ("h5", "all"):
            import h5py
            if self.h5 is None:
                self.h5 = h5py.File(f"{self.stem}.h5", "w")
                self.h5.attrs["jewel_cs"] = self.meta
                self.h5.attrs["schema"] = "hepyy_utils.jewel.tables.v1"
            group = self.h5.require_group(name)
            for key, values in cols.items():
                strings = values.dtype.kind == "U"
                if key not in group:
                    group.create_dataset(
                        key, shape=(0,), maxshape=(None,), chunks=True,
                        dtype=h5py.string_dtype("utf-8") if strings else values.dtype,
                        compression="gzip", shuffle=not strings,
                    )
                dataset = group[key]
                start = len(dataset)
                dataset.resize((start + len(values),))
                if len(values):
                    dataset[start:] = values.astype(object) if strings else values

    def close(self):
        for w in self.pq.values():
            w.close()
        if self.root is not None:
            self.root.close()
        if self.h5 is not None:
            self.h5.close()


def _columns(rows, ints, strings=(), bools=(), *, fields=None):
    dtypes = dict.fromkeys(ints, np.int64) | dict.fromkeys(strings, str) | dict.fromkeys(bools, bool)
    return {key: np.asarray([row[key] for row in rows], dtype=dtypes.get(key, np.float64))
            for key in (rows[0] if fields is None else fields)}


def _append_jet_tables(buf, a, event_id, run_id, legs, px, py, pz, energy, pid):
    from .matching import cluster_final_jets, match_hard_legs

    visible = ~np.isin(np.abs(pid), (12, 14, 16))
    jets = cluster_final_jets(px[visible], py[visible], pz[visible], energy[visible],
                             radius=a.jet_radius, min_pt=0.0)
    matches = match_hard_legs(legs, jets, max_delta_r=a.match_delta_r)
    keys = {"event_id": event_id, "run_id": run_id}
    jet_rows = [dict(keys | jet, analysis_selected=jet["pt"] >= a.jet_ptmin and abs(jet["eta"]) <= a.jet_eta_max)
                for jet in jets]
    selected = [jet for jet in jet_rows if jet["analysis_selected"]]
    selected_ids = {jet["jet_id"] for jet in selected}
    buf["jets_all"].append(_columns(jet_rows, JET_IDS, ("run_id",), ("analysis_selected",), fields=JET_FIELDS))
    buf["jets"].append(_columns(selected, JET_IDS, ("run_id",), ("analysis_selected",), fields=JET_FIELDS))
    for match in matches:
        match["analysis_selected"] = match["jet_id"] in selected_ids
        if not match["matched"]:
            match.update(jet_id=-1, jet_rank=-1, delta_r=np.nan)
    buf["jet_matches"].append(_columns([keys | match for match in matches],
                                        (*JET_IDS, "leg_id", "n_candidates"), ("run_id",),
                                        ("matched", "ambiguous", "analysis_selected")))


def _write_events(path, a, out, records, geometry_meta):
    ftype = np.float64 if a.double else np.float32
    rng = np.random.default_rng([a.seed, zlib.crc32(os.path.basename(path).encode())])
    buf = {"events": [], "particles": [], "particles_raw": [], "partons": []}
    if geometry_meta:
        buf["geometry"] = []
    if a.jets:
        buf.update(jets_all=[], jets=[], jet_matches=[])
    nev = 0

    def flush():
        for name, rows in buf.items():
            if rows:
                out.write(name, {k: np.concatenate([r[k] for r in rows]) for k in rows[0]})
                rows.clear()

    for ievent, (hdr, p, legs) in enumerate(records):
        p = p[~subtraction.beam_mask(p[:, 0], p[:, 2], p[:, 3])]              # the two beam nucleons
        st, pid = p[:, 0].astype(np.int64), p[:, 1].astype(np.int64)
        good = p[:, 5] - np.abs(p[:, 4]) > 0.0
        dummy = ((st == 1) | (st == 4)) & subtraction._fuzzy_equals(p[:, 5], 1e-6)
        ev = dict(hdr, ievent=ievent, pthat=hdr["scale"] if hdr["scale"] > 0 else np.nan,
                  n_final=int((((st == 1) | (st == 4)) & ~dummy).sum()), n_thermal=int((st == 3).sum()),
                  n_dummy=int(dummy.sum()),
                  cs_thermal_pt=float(np.hypot(p[:, 2], p[:, 3])[(st == 3) & good].sum()))
        eid = int(hdr["event_id"])
        if legs:
            ev["run_id"] = geometry_meta["run_id"]
            ev.update({key: legs[0][key] for key in geometry_csv.EVENT_FIELDS})
            buf["geometry"].append(_columns([leg | {"run_id": ev["run_id"]} for leg in legs],
                                             geometry_csv.INT_FIELDS, ("run_id",)))
        hard = st == 23
        ev["n_partons"] = int(hard.sum())
        if hard.any():
            buf["partons"].append(dict(event_id=np.full(hard.sum(), eid, np.int64),
                                       ipart=np.arange(hard.sum(), dtype=np.int8),
                                       **{k: p[hard, c].astype(np.float64) for k, c in
                                          zip(("px", "py", "pz", "e"), range(2, 6))},
                                       pid=pid[hard].astype(np.int32)))
        if a.particles in ("cs", "both"):
            o = subtraction.subtract(st, pid, p[:, 2], p[:, 3], p[:, 4], p[:, 5], dRmax=a.dRmax,
                                   thermal_pid=a.thermal_pid, rng=rng)
            ev["n_cs"] = len(o["tag"])
            ev["cs_left_pt"] = float(np.hypot(o["px"], o["py"])[o["tag"] == subtraction.TAG_THERMAL_LEFT].sum())
            buf["particles"].append(dict(event_id=np.full(len(o["tag"]), eid, np.int64),
                                         **{k: o[k].astype(ftype) for k in ("px", "py", "pz", "e")},
                                         pid=o["pid"], tag=o["tag"]))
            if a.jets:
                _append_jet_tables(buf, a, eid, ev["run_id"], legs,
                                   o["px"], o["py"], o["pz"], o["e"], o["pid"])
        if a.particles in ("raw", "both"):
            s = (st == 1) | (st == 3) | (st == 4)
            ev["n_raw"] = int(s.sum())
            buf["particles_raw"].append(dict(event_id=np.full(s.sum(), eid, np.int64),
                                             **{k: p[s, c].astype(ftype) for k, c in
                                                zip(("px", "py", "pz", "e"), range(2, 6))},
                                             pid=pid[s].astype(np.int32), status=st[s].astype(np.int8)))
            if a.jets and a.particles == "raw":
                final = ((st == 1) | (st == 4)) & ~dummy
                _append_jet_tables(buf, a, eid, ev["run_id"], legs, *p[final, 2:].T, pid[final])
        buf["events"].append(_columns([ev], INT_KEYS, ("run_id",)))
        nev += 1
        if nev % a.chunk == 0:
            flush()
    flush()
    return nev


def convert(path, a, geometry_path=None):
    name = os.path.basename(path).replace(".gz", "").replace(".hepmc", "")
    stem = os.path.join(a.outdir, name)
    meta = dict(source=os.path.basename(path), dRmax=a.dRmax,
                thermal_pid=a.thermal_pid, seed=a.seed, particles=a.particles)
    t0 = time.time()
    geometry_context = geometry_csv.open_geometry(geometry_path) if geometry_path else nullcontext((None, None))
    # Stage sidecar conversions until the last HepMC/geometry record has been validated.
    with geometry_context as (geometry_meta, geometry_events):
        if geometry_meta:
            geometry_csv.verify_geometry_digest(path, geometry_meta)
            meta["geometry"] = geometry_meta
            records = iter_events_with_geometry(path, geometry_events)
        else:
            records = ((hdr, p, None) for hdr, p in read_hepmc2(path))
        if a.jets:
            inputs = "raw_final" if a.particles == "raw" else "constituent_subtracted"
            meta["jets"] = dict(algorithm="antikt", radius=a.jet_radius, pt_min=a.jet_ptmin,
                                abs_eta_max=a.jet_eta_max, match_delta_r=a.match_delta_r,
                                axis="shower_start", inputs=inputs, exclude_abs_pid=[12, 14, 16],
                                include_thermal_leftovers=inputs == "constituent_subtracted",
                                jet_rank="one-based pt order across all clustered jets with positive pt",
                                matching_phase_space="all positive-pt clustered jets; no pt/eta analysis cuts",
                                analysis_selection="after_matching",
                                match_strategy="max cardinality, minimum total delta_r, jet rank ties",
                                unmatched_jet_id=-1, unmatched_jet_rank=-1)
        staging = TemporaryDirectory(dir=a.outdir) if geometry_path else nullcontext(a.outdir)
        with staging as workdir:
            out = Tables(os.path.join(workdir, name), a.format, meta)
            try:
                nev = _write_events(path, a, out, records, geometry_meta)
            finally:
                out.close()
            if geometry_path:
                for output in Path(workdir).iterdir():
                    output.replace(Path(a.outdir) / output.name)
    print(f"{path}: {nev} events -> {stem}.* ({a.format}) in {time.time() - t0:.1f} s")


def convert_hepmc_to_tables(inputs, outdir=".", *, format="parquet", particles="cs", dRmax=0.5,
                            thermal_pid="reference", seed=0, chunk=5000, double=False, geometry=None,
                            jets=False, jet_radius=0.4, jet_ptmin=20.0, jet_eta_max=2.0, match_delta_r=0.3):
    """Convert JEWEL HepMC2 files and any associated geometry to flat tables."""

    from types import SimpleNamespace

    if format not in ("parquet", "root", "both", "h5", "all"):
        raise ValueError(f"format must be parquet, root, both, h5 or all, not {format!r}")
    if format in ("h5", "all"):
        try:
            import h5py
        except ImportError as exc:
            raise RuntimeError("HDF5 output requires h5py: install h5py or hepyy-utils[h5].") from exc
    if particles not in ("cs", "raw", "both"):
        raise ValueError(f"particles must be cs, raw or both, not {particles!r}")
    if thermal_pid not in subtraction.THERMAL_PID_MODES:
        raise ValueError(f"thermal_pid must be one of {subtraction.THERMAL_PID_MODES}")
    inputs = list(inputs)
    stems = [os.path.basename(path).replace(".gz", "").replace(".hepmc", "") for path in inputs]
    if len(set(stems)) != len(stems):
        raise ValueError("HepMC inputs have duplicate output names; convert them into separate output directories")
    if geometry is not None and len(inputs) != 1:
        raise ValueError("an explicit geometry sidecar requires exactly one HepMC input")
    geometry_paths = [geometry_csv.resolve_geometry_path(path, geometry) for path in inputs]
    if jets:
        if any(path is None for path in geometry_paths):
            raise ValueError("jet matching requires a geometry sidecar for all input files")
        if not all(math.isfinite(x) and x > 0 for x in (jet_radius, jet_eta_max, match_delta_r)):
            raise ValueError("jet_radius, jet_eta_max and match_delta_r must be positive and finite")
        if not math.isfinite(jet_ptmin) or jet_ptmin < 0:
            raise ValueError("jet_ptmin must be finite and nonnegative")
        from ..fastjet import require_fastjet

        require_fastjet()
    os.makedirs(outdir, exist_ok=True)
    a = SimpleNamespace(outdir=str(outdir), format=format, particles=particles, dRmax=float(dRmax),
                        thermal_pid=thermal_pid, seed=int(seed), chunk=int(chunk), double=bool(double),
                        jets=jets, jet_radius=jet_radius, jet_ptmin=jet_ptmin,
                        jet_eta_max=jet_eta_max, match_delta_r=match_delta_r)
    for path, geometry_path in zip(inputs, geometry_paths):
        convert(os.fspath(path), a, geometry_path)
