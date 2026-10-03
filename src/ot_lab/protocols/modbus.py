"""Optional Modbus/TCP input-register replay for canonical telemetry."""

from __future__ import annotations

import asyncio
import math
import struct
from pathlib import Path

import polars as pl


async def replay_modbus(
    telemetry_path: Path,
    host: str = "127.0.0.1",
    port: int = 5020,
    device_id: int = 1,
    realtime: bool = True,
    stay_open: bool = False,
) -> None:
    """Replay telemetry as read-only FLOAT32 input registers, two per tag.

    Tag addresses are stable alphabetical indexes within the sorted asset/tag
    list. Input register addresses are zero-based; consult ``modbus-map.json``
    generated beside no data automatically: the mapping is deterministic and
    can be reconstructed from the Parquet asset_id/tag_id columns.
    """
    try:
        from pymodbus.server import ModbusTcpServer
        from pymodbus.simulator import DataType, SimData, SimDevice
    except ImportError as exc:
        raise RuntimeError("Modbus adapter requires: uv sync --extra modbus") from exc
    frame = pl.read_parquet(telemetry_path).sort("timestamp", "asset_id", "tag_id")
    if frame.is_empty():
        raise ValueError("cannot replay an empty telemetry file")
    if not 0 <= port <= 65535:
        raise ValueError("port must be between 0 and 65535")
    if not 0 <= device_id <= 255:
        raise ValueError("device_id must be between 0 and 255")
    keys = sorted(set(zip(frame["asset_id"].to_list(), frame["tag_id"].to_list())))
    address_by_key = {key: index * 2 for index, key in enumerate(keys)}
    if len(keys) * 2 > 65536:
        raise ValueError("telemetry contains too many tags for Modbus input registers")
    values_by_key = {}
    for asset_id, tag_id, value in frame.select("asset_id", "tag_id", "value").iter_rows():
        values_by_key.setdefault((asset_id, tag_id), float(value))
    blocks = [
        SimData(address=address_by_key[key], values=values_by_key[key], datatype=DataType.FLOAT32, readonly=True)
        for key in keys
    ]

    async def update_read_values(function_code, start_address, address, count, current_registers, set_values):
        if set_values is not None or function_code != 4:
            return
        end_address = address + count
        for key, tag_address in address_by_key.items():
            if address <= tag_address and tag_address + 2 <= end_address:
                offset = tag_address - start_address
                words = struct.unpack(">HH", struct.pack(">f", values_by_key[key]))
                current_registers[offset:offset + 2] = words
        return

    invalid_bits = [SimData(address=0, datatype=DataType.BITS, values=False)]
    invalid_registers = [SimData(address=0, datatype=DataType.INVALID)]
    device = SimDevice(
        device_id,
        (invalid_bits, invalid_bits.copy(), invalid_registers, blocks),
        action=update_read_values,
    )
    server = ModbusTcpServer(device, address=(host, port))
    timestamps = frame["timestamp"].dt.epoch("ms").to_list()
    rows = frame.select("asset_id", "tag_id", "value").iter_rows(named=True)
    await server.serve_forever(background=True)
    try:
        previous = timestamps[0]
        for row, timestamp in zip(rows, timestamps, strict=True):
            if realtime:
                delay = max(0.0, min(60.0, (timestamp - previous) / 1000))
                if delay:
                    await asyncio.sleep(delay)
            value = float(row["value"])
            if math.isfinite(value):
                key = (row["asset_id"], row["tag_id"])
                values_by_key[key] = value
            previous = timestamp
        if stay_open:
            await asyncio.Event().wait()
    finally:
        await server.shutdown()
