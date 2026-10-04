# Centrifugal VFD static-head profile v1.1.0

## Scope

Extend the optional centrifugal pump profile to represent both friction-dominated and static-head systems, while preserving old scenario replay.

## Model

The v1.0.0 profile remains unchanged: normalized flow is speed ratio `r`, normalized pressure is `r²`, and normalized hydraulic power is `r³`.

Profile v1.1.0 introduces two explicit scenario parameters:

- `pump_static_head_fraction` (`lambda`): static head divided by rated duty pressure, validated within 0–0.8.
- `pump_shutoff_head_ratio` (`s`): modeled shutoff head divided by rated duty pressure, validated within 1.01–2.0.

The reduced-order quadratic pump curve and system curve intersect at:

```text
flow_ratio = sqrt(max(s * r^2 - lambda, 0) / (s - lambda))
pressure_ratio = lambda + (1 - lambda) * flow_ratio^2   when s * r^2 > lambda
pressure_ratio = min(lambda, s * r^2)                    otherwise
hydraulic_power_ratio = flow_ratio * pressure_ratio
```

At zero static head, v1.1.0 reduces to the affinity-law limit (`flow_ratio = r`, `pressure_ratio = r²`). With static head, flow falls nonlinearly as speed drops and becomes zero below the modeled shutoff threshold. Thermal rise follows normalized hydraulic power. Pump shutoff-curve shape, parameter distributions, constant efficiency, thermal constants and vibration response remain illustrative assumptions, not fitted values or field-population claims.

This change follows the [DOE variable-speed pumping guide](https://www.energy.gov/sites/prod/files/2014/05/f16/variable_speed_pumping.pdf), which describes pump/system curve intersection and cautions that affinity-law approximations can be substantially inaccurate with high static head. No third-party data were copied into source or generated artifacts.

## Versioning and suites

- `AssetSpec` now accepts `centrifugal_vfd@1.1.0`; v1.0-only scenarios retain their historical equations and replay behavior.
- `training-v0.5.yaml` samples `lambda` from 0–0.3 and `s` from 1.2–1.5.
- `challenge-v0.4.yaml` samples `lambda` from 0–0.4 and `s` from 1.15–1.6 using runtime-hidden cases.
- The normal pump example uses a fixed illustrative `lambda=0.2`, `s=1.3` and profile version 1.1.0.

These numeric ranges are synthetic design choices. The optional profile is not a digital twin and does not claim to cover a pump product or plant.

## Validation

- Python 3.12: `uv run --python 3.12 ruff check src tests` passed; full `pytest` passed, 191 tests; `uv lock --check` passed.
- Focused pump, training-v0.5 and challenge-v0.4 checks: 8 passed.
- Seeded suite checks exercised 240 training seeds and verified distinct static-head parameter sets and finite, engineering-bounded LOW/NORMAL/HIGH outputs; challenge sampling encountered and validated v1.1 pump cases.
- CLI generated seed 42 from `normal-pump-centrifugal-vfd.yaml`, producing 3,600 observations; `ot-lab replay` reproduced both artifacts byte-for-byte. Telemetry Parquet SHA-256: `00b8696f7838159028f7c0878bb73a259f1487f9865aed1460da1383d663ad59`; ground-truth SHA-256: `2dc2d90ad6a9de40a8be36d724fb4a9b8288e3a9a447c1b221b9a0f1a9c3be50`.
- End-to-end `dataset create` smoke used `training-v0.5.yaml`, seed `20261004`, 100 runs and four workers. It generated 1,194,381 observations, 100 unique seeds and all 16 configured event families; pump profile counts were generic v1.0.0: 55 and centrifugal VFD v1.1.0: 25. The suite SHA-256 recorded in its manifest is `2725af0f8a495829f43909799aeaf713cd9711b07eddc36f696e59c3cf972336`. The generated smoke dataset is temporary and was not published.
- `git diff --check` passed. The candidate run artifacts are temporary local evidence and are not committed.

## Limits

The profile does not use pump-specific test curves, fluid properties, system identification or measured static head. The source basis supports the structural curve relationships, not the selected `lambda`, `s`, efficiency, temperature or vibration values. Continue collecting compatible openly licensed data before describing this profile as calibrated.
