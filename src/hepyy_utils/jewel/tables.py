"""
JEWEL HepMC2 (.hepmc / .hepmc.gz) -> flat tables in parquet and/or ROOT.

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
Parquet: <stem>.events.parquet, <stem>.particles.parquet, ...  ROOT: <stem>.root with one TTree per table.

  jewel_tables run*.hepmc.gz [--format parquet|root|both] [--particles cs|raw|both]
                         [--dRmax 0.5] [--thermal-pid reference|intended|cast] [--seed 0]
                         [--chunk 5000] [--outdir .] [--double]

--thermal-pid: PDG id of leftover thermal momenta (tags 2, 3); see subtraction.py. Random modes are
reproducible: one generator per input file, seeded from (--seed, file name).
The settings are stored with the output (parquet metadata key 'jewel_cs'; TObjString 'jewel_cs').

pthat: taken from the HepMC event scale (E line). Stock JEWEL writes 0 there (stored as NaN);
JEWEL patched with patch_jewel_partons.py writes PARI(17).
"""
import gzip
import json
import os
import time
import zlib

import numpy as np

from . import subtraction

E_KEYS = ("event_id", "n_mpi", "scale", "alpha_qcd", "alpha_qed", "process_id")
H_KEYS = ("hi_n_hard", "hi_npart_proj", "hi_npart_targ", "hi_ncoll", "hi_nspec_n", "hi_nspec_p",
          "hi_n_nwounded", "hi_nwounded_n", "hi_nwounded_nwounded", "hi_b", "hi_psi", "hi_ecc",
          "hi_sigma_nn")
F_KEYS = ("pdf_id1", "pdf_id2", "pdf_x1", "pdf_x2", "pdf_scale", "pdf_xf1", "pdf_xf2")
INT_KEYS = {"event_id", "ievent", "n_mpi", "process_id", "n_final", "n_thermal", "n_dummy", "n_cs", "n_raw",
            "beam1_pid", "beam2_pid", "n_partons"}


def read_hepmc2(path):
    """Yield (header dict, particle array [status, pid, px, py, pz, e] in GeV) per event."""
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
                hdr.update(zip(E_KEYS, map(float, t[1:7])))
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


class Tables:
    """Chunked writer: parquet (pyarrow) and/or ROOT (uproot), one table/TTree per name."""

    def __init__(self, stem, fmt, meta):
        self.stem, self.fmt, self.pq, self.root, self.trees = stem, fmt, {}, None, set()
        self.meta = json.dumps(meta)

    def write(self, name, cols):
        if self.fmt in ("parquet", "both"):
            import pyarrow as pa
            import pyarrow.parquet as pq
            table = pa.table(cols).replace_schema_metadata({"jewel_cs": self.meta})
            if name not in self.pq:
                self.pq[name] = pq.ParquetWriter(f"{self.stem}.{name}.parquet", table.schema,
                                                 compression="zstd")
            self.pq[name].write_table(table)
        if self.fmt in ("root", "both"):
            import uproot
            if self.root is None:
                self.root = uproot.recreate(f"{self.stem}.root")
                self.root["jewel_cs"] = self.meta                 # TObjString
            if name not in self.trees:
                self.root.mktree(name, {k: v.dtype for k, v in cols.items()})
                self.trees.add(name)
            self.root[name].extend(cols)

    def close(self):
        for w in self.pq.values():
            w.close()
        if self.root is not None:
            self.root.close()


def convert(path, a):
    stem = os.path.join(a.outdir, os.path.basename(path).replace(".gz", "").replace(".hepmc", ""))
    ftype = np.float64 if a.double else np.float32
    rng = np.random.default_rng([a.seed, zlib.crc32(os.path.basename(path).encode())])
    out = Tables(stem, a.format, dict(source=os.path.basename(path), dRmax=a.dRmax,
                                      thermal_pid=a.thermal_pid, seed=a.seed, particles=a.particles))
    buf = {"events": [], "particles": [], "particles_raw": [], "partons": []}
    nev, t0 = 0, time.time()

    def flush():
        for name, rows in buf.items():
            if rows:
                out.write(name, {k: np.concatenate([r[k] for r in rows]) for k in rows[0]})
                rows.clear()

    for ievent, (hdr, p) in enumerate(read_hepmc2(path)):
        p = p[~subtraction.beam_mask(p[:, 0], p[:, 2], p[:, 3])]              # the two beam nucleons
        st, pid = p[:, 0].astype(np.int64), p[:, 1].astype(np.int64)
        good = p[:, 5] - np.abs(p[:, 4]) > 0.0
        dummy = ((st == 1) | (st == 4)) & subtraction._fuzzy_equals(p[:, 5], 1e-6)
        ev = dict(hdr, ievent=ievent, pthat=hdr["scale"] if hdr["scale"] > 0 else np.nan,
                  n_final=int((((st == 1) | (st == 4)) & ~dummy).sum()), n_thermal=int((st == 3).sum()),
                  n_dummy=int(dummy.sum()),
                  cs_thermal_pt=float(np.hypot(p[:, 2], p[:, 3])[(st == 3) & good].sum()))
        eid = int(hdr["event_id"])
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
        if a.particles in ("raw", "both"):
            s = (st == 1) | (st == 3) | (st == 4)
            ev["n_raw"] = int(s.sum())
            buf["particles_raw"].append(dict(event_id=np.full(s.sum(), eid, np.int64),
                                             **{k: p[s, c].astype(ftype) for k, c in
                                                zip(("px", "py", "pz", "e"), range(2, 6))},
                                             pid=pid[s].astype(np.int32), status=st[s].astype(np.int8)))
        buf["events"].append({k: np.array([v], dtype=np.int64 if k in INT_KEYS else np.float64)
                              for k, v in ev.items()})
        nev += 1
        if nev % a.chunk == 0:
            flush()
    flush()
    out.close()
    print(f"{path}: {nev} events -> {stem}.* ({a.format}) in {time.time() - t0:.1f} s")


def convert_hepmc_to_tables(inputs, outdir=".", *, format="parquet", particles="cs", dRmax=0.5,
                            thermal_pid="reference", seed=0, chunk=5000, double=False):
    """Convert JEWEL HepMC2 files to flat tables; one set of outputs per input file."""

    from types import SimpleNamespace

    if format not in ("parquet", "root", "both"):
        raise ValueError(f"format must be parquet, root or both, not {format!r}")
    if particles not in ("cs", "raw", "both"):
        raise ValueError(f"particles must be cs, raw or both, not {particles!r}")
    if thermal_pid not in subtraction.THERMAL_PID_MODES:
        raise ValueError(f"thermal_pid must be one of {subtraction.THERMAL_PID_MODES}")
    os.makedirs(outdir, exist_ok=True)
    a = SimpleNamespace(outdir=str(outdir), format=format, particles=particles, dRmax=float(dRmax),
                        thermal_pid=thermal_pid, seed=int(seed), chunk=int(chunk), double=bool(double))
    for path in inputs:
        convert(str(path), a)
