# External model benchmark on OT Irregularity Dataset v0.4.0

## Purpose and scope

Exercise the model-agnostic submission and scoring path with three independently implemented methods. This is an exploratory evaluation of generated data, not evidence of industrial detection quality, simulator fidelity, or operational false-alarm rates. The results did not change the simulator or its fault parameters.

This record preserves the original event/window-mixed precision calculation for historical reproducibility. It predates metric version 2.0.0; use the [v2 rescore](2026-10-04-external-model-evaluation-metrics-v2.md) and its [machine-readable results](2026-10-04-external-model-evaluation-v0.4.0-metrics-v2.json) for coherent event/episode precision and F1.

## Data and inference boundary

- Dataset: public [OT Irregularity Dataset v0.4.0](https://github.com/Mysthrala-Kurogane-Defense-Labs/ot-irregularity-lab/releases/tag/dataset-v0.4.0), `test` partition, lexical first 40 runs. These contained 10 event-free runs, 30 runs with events, 44 events and 15 event types.
- Training: the lexically first eight event-free runs per asset class from the `train` partition. Calibration: the lexically first two event-free runs per asset class from `validation`. The evaluator used their separate ground truth only to select event-free examples; no test labels were used for fitting, calibration, or threshold selection.
- The test set contains 10 short normal runs in this subset, so the false-alarm rates below have limited exposure and should not be generalized.
- The inference images were built in two stages. The training stage had selected train/validation examples and labels; the final stage copied only model artifacts into the runtime image. Inspection inside the final image found no `/training` directory and no `ground_truth.json` files. The Lab's Docker runner mounted one read-only test telemetry file and one prediction output file, disabled networking, and did not mount the test run directory or ground truth.
- Models emitted one score per asset/cadence window. Values were median-imputed, standardized by asset class, then scored. Model scores were mapped to empirical percentiles from normal validation examples. The fixed score threshold was 0.995; event overlap threshold was 10%. No test-set tuning was done.

## Models

| Method | Library and fixed configuration |
| --- | --- |
| Isolation Forest | scikit-learn 1.9.1; 150 trees, `max_samples=256`, `random_state=42` |
| Local Outlier Factor | scikit-learn 1.9.1; novelty mode, 20 neighbors |
| ECOD | PyOD 3.6.6; contamination 0.1 |

Runtime used Python 3.12, NumPy 2.5.3, PyArrow 25.0.1. All three predictions ran through `run-container`; all 120 run/model submissions completed without errors.

## Results

| Method | Event recall | Event precision* | Event F1* | Mean event coverage | Mean expected-sample PR-AUC | False alert windows / asset-hour | Normal-only false alert windows / asset-hour |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Isolation Forest | 6.8% (3/44) | 0.5% | 1.0% | 3.8% | 0.233 | 64.54 | 60.62 |
| Local Outlier Factor | 34.1% (15/44) | 5.2% | 9.0% | 23.6% | 0.367 | 40.97 | 79.62 |
| ECOD | 2.3% (1/44) | 0.2% | 0.4% | 1.1% | 0.184 | 47.05 | 45.69 |

\* Event precision and F1 follow the Lab's documented event/window aggregation semantics; they combine detected events and unmatched alert windows within the 30 event-bearing runs. Normal-run false alerts are reported separately. PR-AUC is macro-averaged across the 40 runs. False-alert rates use the summed false alert windows over total asset-hour exposure; the normal-only column uses only the ten event-free runs.

At this threshold all three configurations had high false-alert rates and low event recall. LOF ranked highest on mean expected-sample PR-AUC and event recall in this small sample, but its false-alert rate was also high. This only shows that the evaluator distinguishes these outputs; it does not establish a useful model ranking. Different preprocessing, training distributions, model configurations, and larger held-out samples could change the comparison.

## Reproduction and references

The training/calibration run selection rule, preprocessing, score threshold, overlap threshold, test selection rule, library versions, and aggregate metrics above define this exploratory run. The runtime images were built locally from Python 3.12 with exact dependency versions listed above; test inference used prebuilt local images and Docker's `--pull=never` runner path.

- [scikit-learn IsolationForest API](https://scikit-learn.org/stable/modules/generated/sklearn.ensemble.IsolationForest.html)
- [scikit-learn LocalOutlierFactor API](https://scikit-learn.org/stable/modules/generated/sklearn.neighbors.LocalOutlierFactor.html)
- [PyOD ECOD documentation](https://pyod.readthedocs.io/en/latest/pyod.models.tabular.html)
- [Dataset v0.4.0 release](https://github.com/Mysthrala-Kurogane-Defense-Labs/ot-irregularity-lab/releases/tag/dataset-v0.4.0)
