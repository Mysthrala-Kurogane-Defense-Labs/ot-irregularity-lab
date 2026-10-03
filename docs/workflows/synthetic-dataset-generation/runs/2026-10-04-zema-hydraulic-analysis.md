# UCI ZeMA hydraulic aggregate analysis

## Objective and scope

Add a reproducible, aggregate-only analysis for the openly licensed UCI Condition Monitoring of Hydraulic Systems dataset and assess whether its observations can inform pump and cooling scenario design. The source archive was downloaded from the official [UCI dataset record](https://archive.ics.uci.edu/dataset/447), DOI `10.24432/C5CW21`, CC BY 4.0. No source measurements were copied into this repository.

## Reproducibility

- Input: official UCI ZIP, stored outside the repository at `%TEMP%\ot-lab-uci-hydraulic-447.zip`.
- Input SHA-256: `24128aad2ee45eea7e6b63ebbd9992cdf25d0483a2cebefbfc13bc69079af1f2`.
- Command: `uv run --python 3.12 ot-lab calibration analyze-hydraulic --input <archive.zip> --output calibration/zema-hydraulic-summary.json`.
- Aggregate report SHA-256: `EC90BEC7C722D78825C1F831576837EC612AEFE48C25BBD1E4B789D96550D165`.
- Analyzer behavior: computes per-cycle summaries and isolated component-condition quantiles; emits provenance and label counts without raw rows.

## Observations and limits

The archive describes 2,205 repeated 60-second cycles on one hydraulic rig. In isolated stable cycles, internal leakage levels 0/1/2 have median FS1 flow 6.712/6.525/6.432 l/min and EPS1 motor power 2533.08/2550.15/2575.25 W. Cooler values 100/20/3 have median TS1 temperatures 36.28/45.56/54.76 °C and CE efficiencies 47.59/28.00/20.60%. Most isolated groups contain only 10 cycles per level. These are descriptive observations, not causal estimates, failure prevalence, or universal limits. The source measures motor power rather than current, has no RPM channel, and labels conditions by cycle rather than fault onset time; it therefore does not calibrate generic PUMP-01 or establish a leakage-to-vibration relationship.

## Validation

- `ruff check src/ot_lab/calibration.py src/ot_lab/cli.py tests/test_calibration.py`: passed.
- `pytest tests/test_calibration.py -q`: 4 passed on Windows Python 3.12.
- The analyzer was run on the full official archive and produced the committed aggregate report.
- Full-suite Windows and WSL verification is pending at record creation.
