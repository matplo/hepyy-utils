# Artifact Cache

`hepyy_utils.cache` provides small, generator-neutral helpers for local
analysis caches. It is meant to avoid repeating expensive event generation,
jet finding, or table construction when only later analysis or plotting steps
change.

The module deliberately does not define a physics payload schema. Callers own
the meaning of each cached object, which configuration fields invalidate it,
and whether pickle is acceptable for that workflow.

## What It Provides

- `jsonable(value)`: converts common structured values, dataclasses, paths,
  numpy scalars, and numpy arrays into JSON-compatible objects.
- `config_digest(config, length=12)`: returns a deterministic short hash of a
  JSON-safe configuration mapping.
- `safe_token(value)`: converts a label into a filename-friendly token.
- `path_label(path, base_dir=None)`: returns a compact relative label when
  possible.
- `ArtifactCache`: combines hashed filenames, pickle payload I/O, and JSON
  sidecar metadata.

## Basic Usage

```python
from hepyy_utils.cache import ArtifactCache

CACHE_SCHEMA_VERSION = 1

cache = ArtifactCache("outputs/cache", schema_version=CACHE_SCHEMA_VERSION, base_dir=".")
config = {
    "cache_schema_version": CACHE_SCHEMA_VERSION,
    "generator": "pythia8",
    "n_events": 10000,
    "jet_R": 0.4,
    "selection": "maxkt",
}

path = cache.path("splitting_records", "pythia_demo", config)

payload = {
    "cache_schema_version": CACHE_SCHEMA_VERSION,
    "config": config,
    "records": records,
}

cache.write_pickle(path, payload, sidecar_exclude={"records"})
loaded = cache.read_pickle(path)
```

The payload is written to a file like:

```text
outputs/cache/splitting_records__pythia_demo__8f3a1c77e0a2.pkl
```

A sibling JSON sidecar is written with the same stem:

```text
outputs/cache/splitting_records__pythia_demo__8f3a1c77e0a2.json
```

The sidecar is intended for inspection and provenance. Exclude bulky or
non-JSON payload fields with `sidecar_exclude`.

## Load Or Compute

For compact workflows, use `load_or_compute_pickle`:

```python
def compute_payload():
    records = run_expensive_step()
    return {
        "cache_schema_version": CACHE_SCHEMA_VERSION,
        "config": config,
        "records": records,
    }

payload, cache_hit = cache.load_or_compute_pickle(
    path,
    compute_payload,
    sidecar_exclude={"records"},
)
```

`cache_hit` is `True` when an existing pickle was reused and `False` when the
payload was recomputed and written.

## Invalidation

The cache filename hash is computed only from the `config` mapping passed to
`cache.path(...)`. Include every input that can change the payload:

- generator name and process settings;
- random seed and number of events;
- input filenames or glob patterns;
- jet radius, pT cuts, eta cuts, and particle cuts;
- grooming or splitting-selection parameters;
- histogram binning or table-construction parameters;
- code-level schema version.

`ArtifactCache.schema_version` is written to sidecars by default, but it does
not automatically change the filename. If a schema change should force a new
cache file, include `cache_schema_version` in the config used for `cache.path`.

Plotting-only options should usually be kept out of the expensive-step config.
That allows plot styling changes to reuse generation or analysis caches.

## Pickle Caveat

Pickle is convenient for local notebook and analysis caches, but it is not a
portable interchange format. A pickle that contains project-specific Python
objects can only be read when compatible class definitions are importable at
the same module paths. Changes to class layout, package names, Python version,
or dependency versions can make old cache files unreadable or semantically
stale.

Mitigations:

- Treat pickle caches as disposable local accelerators, not archival data.
- Store full config and schema metadata in the payload and sidecar.
- Increment `CACHE_SCHEMA_VERSION` when payload object layouts change, and
  include it in the hash config.
- Prefer simple dictionaries, lists, arrays, or tables over custom class
  instances when feasible.
- For durable interchange, write stable formats such as parquet, Arrow, HDF5,
  ROOT through uproot, or JSON metadata plus numeric arrays. `ArtifactCache`
  can still be used for deterministic naming and sidecars around those files.

## Directory Policy

Keep cache directories outside tracked source files, for example under
`outputs/<workflow>/cache/`, and add those outputs to `.gitignore`. Commit the
code and configuration needed to regenerate caches, not the cache payloads
themselves.
