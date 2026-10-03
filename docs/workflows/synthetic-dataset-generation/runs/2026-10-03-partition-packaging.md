# Deterministic dataset partition packaging

## Change

Added `ot-lab dataset package` to validate a completed dataset manifest and source partition hashes, then create one deterministic ZIP per selected public partition. Each ZIP contains its Parquet, an explicitly supplied license notice, and a seed-free release manifest. A release-level manifest lists artifact hashes, byte sizes, row/run counts, suite/schema/simulator versions, and the source dataset manifest SHA-256. No run directories, ground truth, scenarios, per-run metadata, or seed values are copied. Packaging is local; it does not publish a GitHub release.

## Validation

- Five focused package tests cover deterministic contents, invalid partition selection, corrupted source partitions, license inclusion, seed/ground-truth exclusion, and refusal to overwrite output.
- Full `uv run --python 3.12 pytest -q`, Ruff, and `git diff --check` passed locally.
- CLI packaged the generated 1,000-run OT Irregularity Training Dataset v0.3.0 twice using `DATASET_LICENSE.txt`; both output directories had byte-identical manifests and partition ZIPs.
- Artifact sizes and SHA-256:
  - `train.zip`: 63,099,429 bytes; `59edb55be4a3103442267f8b703ed359bd64681108e18c0a4c4e481adfff8a0f`
  - `validation.zip`: 11,392,475 bytes; `744405c1f23796b21bb90e0619ce5d72533032fbcb65e849b59cb9a0a77f6885`
  - `test.zip`: 14,131,123 bytes; `ab09a5712cd9b2987ef9e9228683afce1f6912329b8c48b606528c55c00d50d3`
- Verified each ZIP's CRC with `ZipFile.testzip()`, listed expected members, checked embedded license bytes, validated external ZIP digests, and confirmed release manifests contain no `master_seed` or ground truth.

## Limits

The generated package is not signed and is not uploaded to a public release. Signatures remain gated on availability of an authorized signing key. The source generation manifest retains per-run seeds for local replay and should not be attached when publishing the seed-free partition artifacts.
