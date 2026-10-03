# Optional Modbus/TCP telemetry replay

## Scope

Implement an independent, optional Modbus/TCP replay adapter for canonical telemetry. Keep process simulation and dataset generation usable without PyModbus or a running protocol service.

## Implementation

- Added the `modbus` dependency extra (`pymodbus>=3.15,<4`) and `ot-lab modbus-replay` command.
- Uses PyModbus `SimDevice` / `SimData` and only serves values via read-only IEEE-754 FLOAT32 input registers (function code 04). Each signal occupies two zero-based registers in network byte order, with stable alphabetical `(asset_id, tag_id)` assignment.
- Defaults to `127.0.0.1:5020`, device ID 1. Ground truth is not loaded. No PLC control logic is emulated.
- Added optional CI matrix coverage and a local client/server integration test.
- Documented the register map and security boundary in `PROTOCOLS.md`.

## Validation

- Windows Python 3.12: `uv run ruff check src tests` passed; `uv run pytest` passed (130 tests); `uv lock --check` and `git diff --check` passed.
- Linux WSL Python 3.12 with `dev`, `opcua`, and `modbus` extras: full `pytest -q` passed (130 tests).
- Integration test connected with a PyModbus client, decoded the value `12.5` from two input registers, and confirmed that a holding-register write returns an error. The service bound to loopback.
- GitHub Actions run [37157484312](https://github.com/Mysthrala-Kurogane-Defense-Labs/ot-irregularity-lab/actions/runs/37157484312) passed all three jobs (core, OPC UA, Modbus) in 38 seconds. The first run emitted two cache-key collision warnings between the optional jobs; the workflow now uses a matrix-specific cache suffix to avoid them.

## Evidence limits

This tests the adapter against PyModbus 3.15.0 client/server behavior. It does not validate vendor PLC interoperability, control behavior, transport security, or safety. Modbus/TCP has no transport security here; use loopback or an isolated test network.

## References

- [PyModbus 3.15.0 data model documentation](https://pymodbus.readthedocs.io/en/stable/source/simulator/datamodel.html)
- [PyModbus 3.x server documentation](https://pymodbus.readthedocs.io/en/stable/source/server.html)
