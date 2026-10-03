"""Optional OPC UA server adapter for replaying canonical telemetry."""

from __future__ import annotations

import asyncio
from pathlib import Path

import polars as pl


async def replay_opcua(
    telemetry_path: Path, endpoint: str = "opc.tcp://127.0.0.1:4840/ot-lab/",
    realtime: bool = True, stay_open: bool = False,
) -> None:
    """Expose one read-only OPC UA Variable per tag and replay rows from Parquet.

    Install the optional dependency with ``uv sync --extra opcua``. This is a
    protocol/replay adapter, not a PLC safety or conformance certification.
    """
    try:
        from asyncua import Server
    except ImportError as exc:
        raise RuntimeError("OPC UA adapter requires the optional extra: uv sync --extra opcua") from exc

    frame = pl.read_parquet(telemetry_path).sort("timestamp", "asset_id", "tag_id")
    if frame.is_empty():
        raise ValueError("cannot replay an empty telemetry file")
    server = Server()
    await server.init()
    server.set_endpoint(endpoint)
    server.set_server_name("OT Irregularity Lab synthetic telemetry")
    namespace = await server.register_namespace("urn:ot-irregularity-lab:telemetry:1")
    assets: dict[str, object] = {}
    variables: dict[tuple[str, str], object] = {}
    value_frame = frame.drop("timestamp")
    for row in value_frame.iter_rows(named=True):
        asset_id, tag_id = row["asset_id"], row["tag_id"]
        key = (asset_id, tag_id)
        if asset_id not in assets:
            assets[asset_id] = await server.nodes.objects.add_object(namespace, asset_id)
        if key not in variables:
            variable = await assets[asset_id].add_variable(namespace, tag_id, float(row["value"]))
            await variable.set_writable(False)
            await variable.add_property(namespace, "Unit", row["unit"])
            await variable.add_property(namespace, "SignalClass", row["signal_class"])
            await variable.add_property(namespace, "EngineeringMin", float(row["engineering_min"]))
            await variable.add_property(namespace, "EngineeringMax", float(row["engineering_max"]))
            variables[key] = variable
    timestamp_ms = frame.get_column("timestamp").dt.epoch("ms").to_list()
    async with server:
        previous = timestamp_ms[0]
        for row, timestamp in zip(value_frame.iter_rows(named=True), timestamp_ms, strict=True):
            if realtime:
                delay = max(0.0, min(60.0, (timestamp - previous) / 1000))
                if delay:
                    await asyncio.sleep(delay)
            await variables[(row["asset_id"], row["tag_id"])].write_value(float(row["value"]))
            previous = timestamp
        if stay_open:
            await asyncio.Event().wait()
