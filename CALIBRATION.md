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

The command checks the required timestamp/current/oil-temperature/pressure/digital-valve columns, sorts by timestamp, reports cadence quantiles and signal quantiles grouped by digital operating state, and writes the input SHA-256 and source/license attribution. The `off_or_unloaded` group is intentionally combined because the published binary valve descriptions do not safely distinguish those states. The report contains aggregates only and never copies source rows. A small fixture verifies the calculations. A full-data reanalysis on 2026-10-04 reproduced the committed report byte-for-byte from the locally retained source CSV: 1,516,948 usable rows, 218,300,507 bytes, and SHA-256 `db30ccb4ea402e3c8bf2c99db06e288d4f2a772f6928f9dbe26a920d69793e24`. UCI's page gives both nominal 1 Hz and 0.1 Hz descriptions in different sections; the report uses measured timestamps (positive-gap p05/p50/p95 of 9/10/10 seconds) instead of treating either metadata statement as the observed cadence.

## Scenario severity semantics

- Severity 0 suppresses injected effects; severity 1 applies configured magnitudes or rates. Intermediate values scale continuous magnitudes and sampling probabilities linearly.
- `single_signal_loss` and `asset_communication_loss` use deterministic per-sample masks with probability `loss_pct × severity / 100`. `quality_degradation` marks all tags BAD at a sampled fraction of event timestamps. `sensor_stuck` blends each reading toward its first event value by the severity fraction and marks quality UNCERTAIN when severity is positive.
- These are reproducible benchmark injection semantics, not field-calibrated failure distributions. Suite parameter ranges must not be read as prevalence estimates.

## Compressor catalog envelope

The aggregate run `calibration/metropt-3-summary.json` was generated from the full UCI CSV after its archive SHA-256 matched `aab991a970e58210de853bb8078ce0e63abb4d9412fdc5c79792dae3d8e1721a`. The CSV hash is recorded in the report. All 1,516,948 rows parsed; positive timestamp intervals had p05/p50/p95 of 9/10/10 seconds, with 0.000216 over 120 seconds. Under a deliberately simple digital-state grouping, `DV_eletric > 0.5` produced median motor current 5.835 A and oil temperature 65.9 °C; the combined `COMP > 0.5, DV_eletric <= 0.5` group had median current 0.0425 A and oil temperature 62.05 °C. The official UCI variable description additionally states typical current near 0 A when off, 4 A offloaded, 7 A under load, and 9 A at startup. These operating descriptions are qualitative anchors; the available binary channels do not establish every mode, and the aggregate off-or-unloaded p95 of 3.87 A demonstrates that multiple states remain mixed. Quantiles are observational rather than control setpoints.

The opt-in `process_profile: metropt3_rail_apu` uses these state-conditioned current/pressure and observed temperature envelopes as an illustrative profile. Version `1.1.0` maps `IDLE` to the documented approximately 4 A offloaded current, `OFF` to near-zero current, and one sample at approximately 9 A when entering `WARMUP` or a loaded state after an inactive regime. This mapping preserves the older `1.0.0` profile behavior and does not reconstruct the train PLC. The observed 10-second cadence cannot establish the startup pulse duration; one simulator sample is a documented approximation. The source does not calibrate thermal time constants, vibration, discharge temperature, transition dynamics, or causal load effects. The generic compressor remains unchanged. Defaults are versioned and every physical/noise parameter can be overridden in the resolved scenario; see [PROCESS_MODELS.md](PROCESS_MODELS.md).

The manufacturer [Atlas Copco GA 11⁺–30 50 Hz datasheet](https://www.atlascopco.com/content/dam/atlas-copco/compressor-technique/industrial-air/documents/leaflets/compressors/ga-11--30/GA11-30_antwerp_datasheet_EN_2935082640.pdf) lists GA 11 variants with an 11 kW installed motor, pressure variants from 7.5 to 13 bar(e), and flow varying with pressure (for the listed GA 11 rows, 37.2 to 26.7 l/s). These are model-specific catalog points, not universal compressor operating limits. A future asset profile may use these values as a labelled example configuration after unit/range review; current generic ranges remain illustrative.

## Hydraulic rig evidence for pump leakage and cooling degradation

The official UCI [Condition Monitoring of Hydraulic Systems dataset](https://archive.ics.uci.edu/dataset/447) (DOI `10.24432/C5CW21`, CC BY 4.0; creators Nikolai Helwig, Eliseo Pignanelli, and Andreas Schütze) contains 2,205 repeated 60-second cycles from one experimental hydraulic test rig. It reports six pressure channels and motor power at 100 Hz, two flow channels at 10 Hz, and temperature, vibration, and derived cooling/efficiency channels at 1 Hz. Four component conditions are varied with graded labels, and a separate stability flag marks cycles that may not have reached steady state.

Download the official ZIP outside the checkout and run:

```bash
uv run ot-lab calibration analyze-hydraulic \
  --input /path/to/condition+monitoring+of+hydraulic+systems.zip \
  --output calibration/zema-hydraulic-summary.json
```

The committed aggregate report records archive SHA-256 `24128aad2ee45eea7e6b63ebbd9992cdf25d0483a2cebefbfc13bc69079af1f2`, label counts, and cycle-mean quantiles. To reduce confounding, its per-component summaries hold other component labels at nominal values and require the stable flag to be zero. This leaves only 10 cycles per level for most isolated groups, so values are descriptive and not universal limits or population priors.

In that isolated subset, internal leakage levels 0/1/2 have median `FS1` flow 6.712/6.525/6.432 l/min and median `EPS1` motor power 2533.08/2550.15/2575.25 W. The four recorded cooling-condition values 100/20/3 have median `TS1` temperature 36.28/45.56/54.76 °C and median derived `CE` cooling efficiency 47.59/28.00/20.60%. These observations support coupled, graded examples for flow/power and cooling/temperature. They do not establish causal parameters for this Lab's generic pump: the rig's `EPS1` is power rather than current, it does not measure RPM, its pressure sensors have distinct physical positions, and its cycle-wise labels do not timestamp within-cycle fault onset. `VS1` does not rise with the internal leakage label in this isolated sample, so the evidence does not justify a generic leakage-to-vibration gain. No raw UCI measurements are included in the repository or public datasets.

## Pump evidence

The [Grundfos CR databooklet](https://api.grundfos.com/literature/Grundfosliterature-6511688.pdf) publishes model-specific head-flow-power-efficiency curves for CR pumps under stated test/standard conditions. It supports modelling pump flow, pressure/head, shaft power and efficiency as coupled quantities. Digitizing a curve requires recording the pump variant, speed, impeller, test conditions, source page and digitization error; this has not yet been done.

## Optional variable-speed centrifugal pump

Grundfos' [pump-curve overview](https://www.grundfos.com/ca/learn/research-and-insights/pump-curves) explains that a Q-H curve relates flow to head and should be considered with the system characteristic; its [speed-control overview](https://www.grundfos.com/au/learn/research-and-insights/speed-controlled-operation) shows that speed changes produce different pump curves. The optional `centrifugal_vfd` profile uses conventional approximate affinity relations (flow proportional to speed, head to speed squared, power to speed cubed) as a fixed-duty simplification. Efficiency, system curve, thermal response and vibration remain configurable or explicit assumptions. Defaults are illustrative simulator settings, not vendor catalog ratings. No proprietary curve was digitized or redistributed. This profile improves model structure but does not constitute pump-specific calibration.
The ZeMA hydraulic rig results above provide an additional independently sourced, fault-labelled example of internal leakage and cooling degradation. They do not fill the missing RPM and current measurements for `PUMP-01`; the generic process model remains illustrative until a directly compatible pump curve or telemetry source is analyzed.

## What remains uncalibrated

The sources above do not establish this project's thermal time constants, load-transition lag, control-loop settling, vibration baselines, bearing-fault progression, sensor noise distributions or cross-asset failure rates. Keep these as explicit simulator hypotheses and configurable distributions. Do not tune them to improve any detector score. A calibrated profile needs an independently reviewable parameter table with source, unit conversion, operating conditions, uncertainty and license/provenance.

No third-party measurements are included in public dataset releases. The training suite remains synthetic, generated and non-customer data.

## Brownfield CNC vibration reference

The Bosch Research [CNC Machining Dataset](https://github.com/boschresearch/CNC_Machining) includes tri-axial acceleration segments collected at 2 kHz from three brownfield milling machines, across 15 shuffled tool operations and six six-month timeframe labels. Its data directory is CC BY 4.0; the paper is Tnani, Feil, and Diepold (2022), [DOI 10.1016/j.procir.2022.04.022](https://doi.org/10.1016/j.procir.2022.04.022). The repository's README describes manually annotated `good` and `bad` process folders; labels do not identify a mechanical fault or within-segment onset. The HDF5 arrays do not declare an acceleration unit.

Reproduce the aggregate report from a local checkout of the data directory with:

```bash
uv sync --extra calibration
uv run ot-lab calibration analyze-bosch-cnc \
  --input-dir /path/to/CNC_Machining/data \
  --source-revision d60581d6a3ab6015dcc5488c3d76112bb8e1bcb1 \
  --output calibration/bosch-cnc-summary.json
```

The pinned repository snapshot contains 1,702 HDF5 segment files (1,632 `good`, 70 `bad`) across three machines. The analyzer records the aggregate SHA-256 manifest of source paths and file hashes, then emits per-machine, per-operation, per-label and per-timeframe sample counts, segment durations, and axis/resultant RMS quantiles. No source arrays or segment-level RMS values are written. Because the unit is absent and these are acceleration rather than velocity measurements, the resulting values cannot calibrate `spindle_vibration_mm_s`; no conversion, physical limit, fault prior or cause-specific gain is inferred. Label imbalance and differences among operations also mean that source class ratios are not failure prevalence.

This source is useful for preserving machine-, operation- and timeframe-conditioned variability in future vibration scenario design. It does not identify spindle load, RPM, power, temperature, controller regimes or causal links; the generic CNC process equations remain illustrative. The analyzer and committed aggregates are documented in the [2026-10-04 Bosch CNC analysis record](docs/workflows/synthetic-dataset-generation/runs/2026-10-04-bosch-cnc-analysis.md).
