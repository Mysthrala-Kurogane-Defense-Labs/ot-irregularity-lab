# Bosch CNC vibration aggregates

## Objective and scope

Create a reproducible aggregate-only inspection of the openly licensed Bosch CNC Machining Dataset. The primary source is the [Bosch Research repository](https://github.com/boschresearch/CNC_Machining), with its data directory marked CC BY 4.0; dataset record 752 is also listed by [UCI](https://archive.ics.uci.edu/dataset/752/bosch%2Bcnc%2Bmachining%2Bdataset). The associated paper is Tnani, Feil, and Diepold (2022), [DOI 10.1016/j.procir.2022.04.022](https://doi.org/10.1016/j.procir.2022.04.022). No third-party source measurements or code were copied into the project.

## Input and reproducibility

- Repository revision: `d60581d6a3ab6015dcc5488c3d76112bb8e1bcb1`.
- Input: the repository's `data/` directory, downloaded outside the checkout to `%TEMP%\ot-lab-bosch-cnc-full`.
- Files and bytes analyzed: 1,702 HDF5 segments; 952,229,265 bytes.
- Input manifest SHA-256: `355dc601413254f0a4079696a12714b77a08a502ab4e0a1ef7d71508a0aa48e8`. It hashes the sorted relative paths and each file's SHA-256.
- Command: `uv run ot-lab calibration analyze-bosch-cnc --input-dir <CNC_Machining/data> --source-revision d60581d6a3ab6015dcc5488c3d76112bb8e1bcb1 --output calibration/bosch-cnc-summary.json`.
- Aggregate report SHA-256: `4e0133b78dd94ef861b6065cce358a68d4d9367726f559df272a4998799d1c9c`.
- The report contains per-machine, operation, source-label, and timeframe quantiles for segment duration and three-axis/resultant RMS; it contains no source arrays or per-segment measurements.

## Findings and limits

The snapshot has 1,632 `good` and 70 `bad` annotated process segments: M01 has 485/34, M02 617/27, and M03 530/9. The source README describes a tri-axial accelerometer sampled at 2 kHz across three machines, 15 operations, and six timeframe labels. Segment lengths vary by operation. The labels identify manually annotated process condition, not a particular mechanical fault or its onset within the segment; the classes are strongly imbalanced and cannot estimate industrial failure prevalence.

HDF5 arrays do not declare the acceleration unit. RMS values therefore stay in source units and are not convertible from this evidence to the Lab's canonical spindle vibration in mm/s. The source has no controller load, spindle RPM/power, temperatures, or causal intervention. It does not calibrate absolute signal magnitudes, causes, severity gains, or the generic CNC model. It supports machine/operation/timeframe-conditioned scenario diversity only.

During retrieval, a sparse Git checkout stalled while fetching the dataset blobs; it was stopped before importing partial data. Direct HTTPS retrieval succeeded for all 1,702 tree-listed HDF5 files with zero errors. An initial OP07-only sample was stored with flattened filenames, which revealed 10 duplicate names across `good`/`bad`; that sample was excluded from analysis. The full download and analyzer preserve the complete machine/operation/label path hierarchy.

## Validation

- Analyzer input: 1,702/1,702 expected HDF5 files, all three numeric axes present, no non-finite samples, zero parsing errors.
- Report regeneration produced the same SHA-256 as the committed aggregate report.
- Windows Python 3.12 with `uv sync --extra dev --extra calibration --extra opcua --extra modbus --group lint`: 135 tests passed, Ruff passed, `uv lock --check` passed, and `git diff --check` passed.
- WSL/Linux Python 3.12 with the same extras: 134 tests passed, one platform-specific test skipped, Ruff and `uv lock --check` passed.
- Calibration tests: 6 passed on Windows Python 3.12 with the optional `calibration` extra.
- Re-running the CLI against the full downloaded source reproduced the committed report byte-for-byte with the same SHA-256.
