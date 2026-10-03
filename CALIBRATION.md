# Process model calibration evidence

## Purpose and evidence boundary

This note records sources examined for improving the simplified asset models. Public datasets and product specifications inform signal coverage and possible parameter envelopes; they do not establish field failure priors or validate the simulator's transient dynamics. No source data or code is redistributed by this project.

## Compressor coverage

The public MetroPT-3 dataset describes a real compressed-air production unit on a metro train. It contains pressure, oil temperature, motor current and digital valve/pressure signals, with irregular cadence and gaps. The UCI record identifies the dataset as CC BY 4.0 and provides the DOI [10.24432/C5VW3R](https://doi.org/10.24432/C5VW3R). The observed channel set supports retaining coupled pressure, temperature, electrical and discrete-state channels in a compressor model. Its specific train/APU installation and sensor channels do not directly calibrate this project's generic compressor, and its cadence should not be collapsed to an assumed perfect grid.

The [MetroGuard data card](https://github.com/firathdr/metroguard-ml/blob/main/DATA_CARD.md) reports 1,516,948 rows and notes that the published timestamps are approximately 10 seconds apart with jitter and longer gaps. This is a secondary analysis, not a replacement for inspecting the UCI record and original paper before any data-backed claim.

## Compressor catalog envelope

The manufacturer [Atlas Copco GA 11⁺–30 50 Hz datasheet](https://www.atlascopco.com/content/dam/atlas-copco/compressor-technique/industrial-air/documents/leaflets/compressors/ga-11--30/GA11-30_antwerp_datasheet_EN_2935082640.pdf) lists GA 11 variants with an 11 kW installed motor, pressure variants from 7.5 to 13 bar(e), and flow varying with pressure (for the listed GA 11 rows, 37.2 to 26.7 l/s). These are model-specific catalog points, not universal compressor operating limits. A future asset profile may use these values as a labelled example configuration after unit/range review; current generic ranges remain illustrative.

## Pump evidence

The [Grundfos CR databooklet](https://api.grundfos.com/literature/Grundfosliterature-6511688.pdf) publishes model-specific head-flow-power-efficiency curves for CR pumps under stated test/standard conditions. It supports modelling pump flow, pressure/head, shaft power and efficiency as coupled quantities. Digitizing a curve requires recording the pump variant, speed, impeller, test conditions, source page and digitization error; this has not yet been done.

## What remains uncalibrated

The sources above do not establish this project's thermal time constants, load-transition lag, control-loop settling, vibration baselines, bearing-fault progression, sensor noise distributions or cross-asset failure rates. Keep these as explicit simulator hypotheses and configurable distributions. Do not tune them to improve any detector score. A calibrated profile needs an independently reviewable parameter table with source, unit conversion, operating conditions, uncertainty and license/provenance.

No third-party measurements are included in public dataset releases. The training suite remains synthetic, generated and non-customer data.
