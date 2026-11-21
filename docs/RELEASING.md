# Publishing hepyy-utils

Releases are built and uploaded by `.github/workflows/publish.yml` when a
`v*` tag is pushed. PyPI trusted publishing is scoped to owner `matplo`,
repository `hepyy-utils`, workflow `publish.yml`, environment `pypi`.
No long-lived PyPI token is stored in the repository.

1. Update the version in `pyproject.toml` and `src/hepyy_utils/__init__.py`.
2. Run the complete suite in a hepyy/cppyy environment, including native jet
   tests. CI also runs the tests without a native runtime and exercises a
   wheel-installed HDF5 CLI conversion; native tests skip in that environment.
3. Merge the release PR after its build, tests and distribution checks pass.
4. Tag the merged commit with `v<version>` and push that tag. The workflow
   refuses mismatches between tag, package metadata and runtime version.
5. Wait for publishing to succeed, inspect the PyPI version and artifact
   hashes, then install the released package in a fresh environment and run
   the CLI smoke checks. Create the corresponding GitHub release notes.

The `h5`, `parquet` and `jets` extras install h5py, pyarrow and hepyy,
respectively. The native libraries/cppyy runtime remain managed by the
user's hepyy environment. Publication must not introduce standalone FastJet.
