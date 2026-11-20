#!/usr/bin/env python3
"""Post-generation JEWEL analysis with hepyy-loaded native FastJet.

Run from an environment with working hepyy/cppyy and installed FastJet:
    hepyy install fastjet
    python -m pip install -e '.[parquet,jets]' matplotlib
    python examples/jewel_geometry_analysis.py --fixture

Without input arguments, use the completed local medium sample if present,
otherwise the bundled recoil fixture. Supply your own HepMC paths/globs with:
    python examples/jewel_geometry_analysis.py 'runs/*/events/*.hepmc' --outdir outputs/my_analysis

Pipeline: saved HepMC + geometry -> utils thermal subtraction -> native
FastJet -> full-phase-space matching -> independent analysis selection.
Nothing is generated here. Existing output tables in outdir are replaced.
"""

from __future__ import annotations

import argparse
import csv
import glob
import json
from pathlib import Path


def load_hepyy_fastjet():
    """Use the same native FastJet loader as jewel_tables."""
    from hepyy_utils.fastjet import require_fastjet

    fastjet = require_fastjet()
    return {"loader": "hepyy.load('fastjet')", "binding": "cppyy",
            "fastjet_version": str(fastjet.fastjet_version_string())}


def default_inputs(repo_root: Path, use_local_sample: bool = True):
    """Use only completed local attempts, or the small portable recoil fixture."""
    manifest = repo_root / "outputs/jewel_geometry_20261120/attempt_manifest.json"
    if use_local_sample and manifest.is_file():
        attempts = json.loads(manifest.read_text())
        paths = [Path(row["hepmc"]) for row in attempts if row["status"] == "completed"]
        if not paths:
            raise ValueError(f"No completed attempts in {manifest}")
    else:
        paths = [repo_root / "tests/fixtures/jewel_geometry/recoils/events.hepmc.gz"]
    for path in paths:
        if not path.is_file():
            raise FileNotFoundError(path)
    return paths


def _write_csv(path, rows, columns):
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def analyze_inputs(inputs, outdir, *, radius=.4, jet_ptmin=20., jet_eta_max=3.1,
                   match_delta_r=.3, subtraction="utils"):
    """Write native-FastJet ROOT/Parquet tables and return joined hard-leg rows.

    `subtraction='utils'` expects un-subtracted JEWEL events (DOSUBTRACTION F),
    with status-3 thermal references when recoils are retained. Use 'none'
    for a deliberately raw analysis or inputs already subtracted by JEWEL.
    The saved event record alone cannot reliably establish which was used;
    check the generation card/log before choosing this setting.
    """
    if subtraction not in ("utils", "none"):
        raise ValueError("subtraction must be 'utils' or 'none'")
    inputs = [Path(path).expanduser().resolve() for path in inputs]
    if not inputs:
        raise ValueError("At least one HepMC file is required")
    for path in inputs:
        if not path.is_file():
            raise FileNotFoundError(path)
    outdir = Path(outdir).expanduser().resolve()
    backend = load_hepyy_fastjet()
    import pyarrow.parquet as pq
    from hepyy_utils.jewel.geometry import resolve_geometry_path
    from hepyy_utils.jewel.tables import convert_hepmc_to_tables

    if any(resolve_geometry_path(path) is None for path in inputs):
        raise ValueError("Each input needs an adjacent <file>.hepmc.geometry.csv sidecar")
    # All particles needed for subtraction are read first. FastJet uses visible
    # corrected particles, then matches ALL positive-pT jets before pT/eta cuts.
    convert_hepmc_to_tables(inputs, outdir, format="both",
                            particles="both" if subtraction == "utils" else "raw",
                            dRmax=.5, thermal_pid="reference", double=True, jets=True,
                            jet_radius=radius, jet_ptmin=jet_ptmin,
                            jet_eta_max=jet_eta_max, match_delta_r=match_delta_r)

    rows, input_metadata, event_indices = [], [], {}
    selected_jet_count = 0
    for path in inputs:
        stem = path.name.replace(".gz", "").replace(".hepmc", "")
        def read(name):
            return pq.read_table(outdir / f"{stem}.{name}.parquet")
        geometry = read("geometry").to_pylist()
        matches = {(r["run_id"], r["event_id"], r["leg_id"]): r
                   for r in read("jet_matches").to_pylist()}
        # Use jets_all here: assigned jets failing cuts must retain their identity.
        jets = {(r["run_id"], r["event_id"], r["jet_id"]): r
                for r in read("jets_all").to_pylist()}
        selected_jet_count += read("jets").num_rows
        metadata = json.loads(read("events").schema.metadata[b"jewel_cs"])
        input_metadata.append({"path": str(path), "table_stem": stem, "jewel_cs": metadata})
        for leg in geometry:
            event_key = (leg["run_id"], leg["event_id"])
            if event_key not in event_indices:
                event_indices[event_key] = len(event_indices) + 1
            match = matches[(*event_key, leg["leg_id"])]
            jet = jets[(*event_key, match["jet_id"])] if match["matched"] else None
            rows.append(dict(leg, event_index=event_indices[event_key],
                             matched=match["matched"], analysis_selected=match["analysis_selected"],
                             ambiguous=match["ambiguous"], n_candidates=match["n_candidates"],
                             delta_r=match["delta_r"] if jet else None,
                             jet_id=jet["jet_id"] if jet else None,
                             jet_rank=jet["jet_rank"] if jet else None,
                             jet_pt=jet["pt"] if jet else None,
                             jet_eta=jet["eta"] if jet else None,
                             jet_phi=jet["phi"] if jet else None))
    columns = list(rows[0]) if rows else ["run_id", "event_id", "leg_id", "matched", "analysis_selected"]
    _write_csv(outdir / "matches.csv", rows, columns)
    _write_csv(outdir / "selected_matches.csv", [row for row in rows if row["analysis_selected"]], columns)
    counts = {"events": len(event_indices), "hard_legs": len(rows),
              "matched_legs": sum(row["matched"] for row in rows),
              "selected_matched_legs": sum(row["analysis_selected"] for row in rows),
              "ambiguous_legs": sum(row["ambiguous"] for row in rows),
              "selected_jets": selected_jet_count}
    provenance = {"schema": "jewel_geometry_example_v1", "backend": backend,
                  "parameters": dict(radius=radius, jet_ptmin=jet_ptmin, jet_eta_max=jet_eta_max,
                                     match_delta_r=match_delta_r, subtraction=subtraction),
                  "inputs": input_metadata, "counts": counts}
    (outdir / "analysis_metadata.json").write_text(json.dumps(provenance, indent=2) + "\n")
    return rows


def display_columns(rows):
    """Compact notebook table; full precision and identity remain in matches.csv."""
    columns = ("event_index", "leg_id", "x0_fm", "y0_fm", "L_hot_fm", "L_hot_T_fm",
               "jet_pt", "jet_eta", "delta_r", "matched", "analysis_selected", "ambiguous")
    return [{key: row[key] for key in columns} for row in rows]


def plot_matches(rows, outdir):
    """Show both collision-frame and transverse length, including cut rejections."""
    import matplotlib.pyplot as plt

    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    fig, axes = plt.subplots(1, 2, figsize=(11, 4), layout="constrained")
    states = (("Selected match", lambda r: r["analysis_selected"], "o", "#2276a5", True),
              ("Match rejected by cuts", lambda r: r["matched"] and not r["analysis_selected"],
               "o", "#bd6330", False),
              ("No matched jet", lambda r: not r["matched"], "x", "#444444", True))
    labels = [f"{row['event_index']}/{row['leg_id']}" for row in rows]
    for axis, field, title in zip(axes, ("L_hot_fm", "L_hot_T_fm"),
                                  ("Collision-frame 3D hot length", "Transverse hot length")):
        for label, include, marker, color, filled in states:
            indices = [i for i, row in enumerate(rows) if include(row)]
            if not indices:
                continue
            kwargs = {"color": color} if marker == "x" else {
                "edgecolors": color, "facecolors": color if filled else "none"}
            axis.scatter(indices, [rows[i][field] for i in indices], marker=marker, label=label, **kwargs)
        axis.set(title=title, xlabel="Event / hard leg", ylabel="Length [fm]")
        axis.set_xticks(range(len(labels)), labels, rotation=45)
        axis.grid(alpha=.25)
        if rows:
            axis.legend(fontsize=8)
    fig.suptitle("Straight shower-start rays; matching before analysis cuts")
    path = outdir / "matches.png"
    fig.savefig(path, dpi=160)
    fig.savefig(outdir / "matches.pdf")
    plt.close(fig)
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("inputs", nargs="*", help="HepMC files or glob patterns, each with an adjacent geometry CSV")
    parser.add_argument("--fixture", action="store_true", help="Use the portable recoil fixture instead of the local sample")
    parser.add_argument("--outdir", type=Path, default=Path("outputs/jewel_geometry_example"))
    parser.add_argument("--radius", type=float, default=.4)
    parser.add_argument("--jet-ptmin", type=float, default=20.)
    parser.add_argument("--jet-eta-max", type=float, default=3.1)
    parser.add_argument("--match-delta-r", type=float, default=.3)
    parser.add_argument("--subtraction", choices=("utils", "none"), default="utils",
                        help="Thermal subtraction: utils for DOSUBTRACTION F; none skips analysis-side subtraction")
    parser.add_argument("--no-plot", action="store_true")
    args = parser.parse_args()
    inputs = []
    for pattern in args.inputs:
        found = sorted(glob.glob(str(Path(pattern).expanduser())))
        if not found:
            parser.error(f"No inputs match {pattern!r}")
        inputs.extend(map(Path, found))
    if not inputs:
        inputs = default_inputs(Path(__file__).resolve().parents[1], use_local_sample=not args.fixture)
    rows = analyze_inputs(inputs, args.outdir, radius=args.radius, jet_ptmin=args.jet_ptmin,
                          jet_eta_max=args.jet_eta_max, match_delta_r=args.match_delta_r,
                          subtraction=args.subtraction)
    if not args.no_plot:
        plot_matches(rows, args.outdir)
    print(f"{len(rows)} hard legs; {sum(r['matched'] for r in rows)} matched; "
          f"{sum(r['analysis_selected'] for r in rows)} selected matches")
    print(f"Tables, joined CSVs and backend metadata: {args.outdir.resolve()}")


if __name__ == "__main__":
    main()
