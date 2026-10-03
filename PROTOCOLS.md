# Optional protocol adapters

## OPC UA telemetry replay

Install only when needed with `uv sync --extra opcua`. Start a synthetic run as a local OPC UA server:

```bash
uv run --extra opcua ot-lab opcua-replay --telemetry runs/pump-0042/telemetry.parquet --serve
```

The default endpoint is loopback at `opc.tcp://127.0.0.1:4840/ot-lab/`. Use `--fast` to publish rows without waiting for their timestamps; use `--endpoint` only when you intentionally need a different interface. `--serve` keeps the final values readable until interrupted. The address space contains one Object per asset and read-only Variables per tag, with unit, signal class, and engineering bounds as properties. It consumes canonical telemetry only; ground truth is not read by the adapter.

The adapter is for synthetic protocol/replay experiments. Its current endpoint uses OPC UA None security and anonymous access, so keep it on loopback or an isolated test network; do not expose it to an untrusted network or production control systems. It is not a certified PLC implementation.

The adapter follows the OPC UA AddressSpace Object/Variable model in [OPC 10000-3](https://reference.opcfoundation.org/specs/OPC-10000-3/full) and uses [asyncua](https://github.com/FreeOpcUa/opcua-asyncio) as an optional implementation dependency. The core simulator and dataset generator do not import or require it.

## Modbus/TCP telemetry replay

Install PyModbus only when needed with `uv sync --extra modbus`, then run:

```bash
uv run --extra modbus ot-lab modbus-replay --telemetry runs/pump-0042/telemetry.parquet --serve
```

The server listens on `127.0.0.1:5020`, device ID 1. Use `--host`, `--port`, or `--device-id` to select another isolated test endpoint/device. `--fast` skips timestamp delays; `--serve` leaves the final register values available until interrupted. Replay exposes telemetry values through Modbus input registers (function code 04) only. Each tag is IEEE-754 FLOAT32, occupying two consecutive 16-bit registers in network byte order. Addresses start at zero and are assigned by sorting `(asset_id, tag_id)` alphabetically; address `2*n` is the first register of tag index `n`. Reconstruct the map from those canonical Parquet columns. Input registers are marked read-only, and no coils, discrete inputs, or holding registers are published. Ground truth is not loaded.

This optional adapter uses [PyModbus 3.15](https://pymodbus.readthedocs.io/en/stable/source/simulator/datamodel.html) `SimDevice` / `SimData`; the primary process simulation and dataset generator remain independent of protocol services. Modbus/TCP has no transport security in this configuration: bind to loopback or an isolated test network and never expose it to untrusted networks or production control systems. The adapter is intended for synthetic replay and protocol experiments, not PLC certification.
