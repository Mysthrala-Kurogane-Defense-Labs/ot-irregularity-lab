# Optional protocol adapters

## OPC UA telemetry replay

Install only when needed with `uv sync --extra opcua`. Start a synthetic run as a local OPC UA server:

```bash
uv run --extra opcua ot-lab opcua-replay --telemetry runs/pump-0042/telemetry.parquet --serve
```

The default endpoint is loopback at `opc.tcp://127.0.0.1:4840/ot-lab/`. Use `--fast` to publish rows without waiting for their timestamps; use `--endpoint` only when you intentionally need a different interface. `--serve` keeps the final values readable until interrupted. The address space contains one Object per asset and read-only Variables per tag, with unit, signal class, and engineering bounds as properties. It consumes canonical telemetry only; ground truth is not read by the adapter.

The adapter is for synthetic protocol/replay experiments. Its current endpoint uses OPC UA None security and anonymous access, so keep it on loopback or an isolated test network; do not expose it to an untrusted network or production control systems. It is not a certified PLC implementation.

The adapter follows the OPC UA AddressSpace Object/Variable model in [OPC 10000-3](https://reference.opcfoundation.org/specs/OPC-10000-3/full) and uses [asyncua](https://github.com/FreeOpcUa/opcua-asyncio) as an optional implementation dependency. The core simulator and dataset generator do not import or require it.
