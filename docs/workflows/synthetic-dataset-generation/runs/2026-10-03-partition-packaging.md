# Deterministic dataset partition packaging

## Change

Added `ot-lab dataset package` to validate a completed dataset manifest and source partition hashes, then create one deterministic ZIP per selected public partition. The publisher must provide a license identifier and notice file; the identifier must match the suite when declared. Each ZIP contains its Parquet, the license notice, and a seed-free release manifest. A release-level manifest lists artifact hashes, byte sizes, row/run counts, class/event/asset-class distributions, suite/schema/simulator versions, and the source dataset manifest SHA-256. No run directories, ground truth, scenarios, per-run metadata, or seed values are copied. Packaging is local; it does not publish a GitHub release.

## Validation

- Seven focused package tests cover deterministic contents, invalid partition selection, corrupted source partitions, license inclusion and consistency, seed/ground-truth exclusion, and refusal to overwrite output.
- Full `uv run --python 3.12 pytest -q`, Ruff, and `git diff --check` passed locally.
- CLI packaged a generated 1,000-run normal-operation dataset (700/150/150 train/validation/test, 10,832,949 observations, suite `ot-irregularity-normal-operation`) as a local release demo `0.1.0`, explicitly selecting CC BY 4.0 because the normal-operation suite does not declare a license. The package was repeated byte for byte. It is not the public mixed training dataset v0.3.0.
- Artifact sizes and SHA-256:
  - `train.zip`: 63,099,482 bytes; `303a8f749b1d9911058977946a32188b3620ce7b71685abdd1e59c94b9065bb2`
  - `validation.zip`: 11,392,528 bytes; `d2eaa065625fc47bf0fc185fc8a6d2b89fa6fbb19c9d22aa2742eb129c30f79f`
  - `test.zip`: 14,131,175 bytes; `af04e7c1d11072a7775ce6702f34cc4feb48ef2cce02760c4ada2eea1fca3aab`
- Verified each ZIP's CRC with `ZipFile.testzip()`, listed expected members, checked embedded license bytes, validated external ZIP digests, and confirmed release manifests contain no `master_seed` or ground truth.

## Limits

The generated package is not signed and is not uploaded to a public release. Signatures remain gated on availability of an authorized signing key. The source generation manifest retains per-run seeds for local replay and should not be attached when publishing the seed-free partition artifacts.
