# Architecture

```text
versioned YAML scenario -> seeded process simulation -> optional protocol adapter
                       -> canonical telemetry -> dataset writer
                       -> independent ground-truth writer
model process (telemetry only) -> predictions -> event evaluator (truth access)
```

The first implementation runs process simulation directly; there is no virtual PLC yet. The protocol adapter boundary must translate simulated tags to protocol values without owning process dynamics. A protocol outage can then be distinguished from process behavior.

Modules are separated into `process`, `assets`, `scenarios`, `protocols`, `telemetry`, `datasets`, `benchmark`, and `evaluation`. The CLI and Pydantic scenario models are thin orchestration boundaries. Ground truth is never a telemetry column unless a future scenario explicitly models a PLC-visible operating-regime tag; even then, anomaly labels and event identifiers remain private evaluator inputs.

Replay identity is `(scenario bytes/hash, seed, simulator version, schema version)`. Randomness is scoped to a NumPy generator seeded at run start. The initial reproducibility target is identical logical Parquet rows and event JSON for a fixed environment; byte-identical Parquet across library/runtime versions is not promised.

No detector code or score feedback enters the simulator. Scenario parameters are authored independently and immutable for a run.
