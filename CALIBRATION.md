# Process model calibration evidence

## Purpose and evidence boundary

This note records sources examined for improving the simplified asset models. Public datasets and product specifications inform signal coverage and possible parameter envelopes; they do not establish field failure priors or validate the simulator's transient dynamics. No source data or code is redistributed by this project.

## Compressor coverage

The public MetroPT-3 dataset describes a real compressed-air production unit on a metro train. It contains pressure, oil temperature, motor current and digital valve/pressure signals, with irregular cadence and gaps. The UCI record identifies the dataset as CC BY 4.0 and provides the DOI [10.24432/C5VW3R](https://doi.org/10.24432/C5VW3R). The observed channel set supports retaining coupled pressure, temperature, electrical and discrete-state channels in a compressor model. Its specific train/APU installation and sensor channels do not directly calibrate this project's generic compressor, and its cadence should not be collapsed to an assumed perfect grid.

The [MetroGuard data card](https://github.com/firathdr/metroguard-ml/blob/main/DATA_CARD.md) reports 1,516,948 rows and notes that the published timestamps are approximately 10 seconds apart with jitter and longer gaps. This is a secondary analysis, not a replacement for inspecting the UCI record and original paper before any data-backed claim.

### Reproducible local analysis

Download the official `MetroPT3(AirCompressor).csv` from the [UCI dataset page](https://archive.ics.uci.edu/dataset/791/metropt%2B3%2B) (DOI `10.24432/C5VW3R`, CC BY 4.0), then run:

```bash
uv run ot-lab calibration analyze-metropt \
  --input /path/to/MetroPT3\(AirCompressor\).csv \
  --output calibration/metropt-3-summary.json
```

The command checks the required timestamp/current/oil-temperature/pressure/digital-valve columns, sorts by timestamp, reports cadence quantiles and signal quantiles grouped by digital operating state, and writes the input SHA-256 and source/license attribution. The `off_or_unloaded` group is intentionally combined because the published binary valve descriptions do not safely distinguish those states. The report contains aggregates only and never copies source rows. A small fixture verifies the calculations; a full-data report must be reviewed before using values in a simulator profile. UCI and other project sources describe the dataset as 1,516,948 rows; the official archive transfer was not yet complete at the time this procedure was added, so no full-file measurements are claimed here.

## Scenario severity semantics

- Severity 0 suppresses injected effects; severity 1 applies configured magnitudes or rates. Intermediate values scale continuous magnitudes and sampling probabilities linearly.
- `single_signal_loss` and `asset_communication_loss` use deterministic per-sample masks with probability `loss_pct × severity / 100`. `quality_degradation` marks all tags BAD at a sampled fraction of event timestamps. `sensor_stuck` blends each reading toward its first event value by the severity fraction and marks quality UNCERTAIN when severity is positive.
- These are reproducible benchmark injection semantics, not field-calibrated failure distributions. Suite parameter ranges must not be read as prevalence estimates.

## Compressor catalog envelope

The aggregate run `calibration/metropt-3-summary.json` was generated from the full UCI CSV after its archive SHA-256 matched `aab991a970e58210de853bb8078ce0e63abb4d9412fdc5c79792dae3d8e1721a`. The CSV hash is recorded in the report. All 1,516,948 rows parsed; positive timestamp intervals had p05/p50/p95 of 9/10/10 seconds, with 0.000216 over 120 seconds. Under a deliberately simple digital-state grouping, `DV_eletric > 0.5` produced median motor current 5.835 A and oil temperature 65.9 °C; the combined `COMP > 0.5, DV_eletric <= 0.5` group had median current 0.0425 A and oil temperature 62.05 °C. The available binary channels do not establish the physical meaning of every combination, and quantiles are observational rather than control setpoints.

The opt-in `process_profile: metropt3_rail_apu` uses these state-conditioned current/pressure and observed temperature envelopes as an illustrative profile. It does not represent a digital twin: the source does not calibrate thermal time constants, vibration, discharge temperature, transitions, or causal load effects. The generic compressor remains unchanged. Profile parameters are currently code defaults and need to become explicit, versioned profile configuration in a follow-up.

The manufacturer [Atlas Copco GA 11⁺–30 50 Hz datasheet](https://www.atlascopco.com/content/dam/atlas-copco/compressor-technique/industrial-air/documents/leaflets/compressors/ga-11--30/GA11-30_antwerp_datasheet_EN_2935082640.pdf) lists GA 11 variants with an 11 kW installed motor, pressure variants from 7.5 to 13 bar(e), and flow varying with pressure (for the listed GA 11 rows, 37.2 to 26.7 l/s). These are model-specific catalog points, not universal compressor operating limits. A future asset profile may use these values as a labelled example configuration after unit/range review; current generic ranges remain illustrative.

## Pump evidence

The [Grundfos CR databooklet](https://api.grundfos.com/literature/Grundfosliterature-6511688.pdf) publishes model-specific head-flow-power-efficiency curves for CR pumps under stated test/standard conditions. It supports modelling pump flow, pressure/head, shaft power and efficiency as coupled quantities. Digitizing a curve requires recording the pump variant, speed, impeller, test conditions, source page and digitization error; this has not yet been done.

## What remains uncalibrated

The sources above do not establish this project's thermal time constants, load-transition lag, control-loop settling, vibration baselines, bearing-fault progression, sensor noise distributions or cross-asset failure rates. Keep these as explicit simulator hypotheses and configurable distributions. Do not tune them to improve any detector score. A calibrated profile needs an independently reviewable parameter table with source, unit conversion, operating conditions, uncertainty and license/provenance.

No third-party measurements are included in public dataset releases. The training suite remains synthetic, generated and non-customer data.
