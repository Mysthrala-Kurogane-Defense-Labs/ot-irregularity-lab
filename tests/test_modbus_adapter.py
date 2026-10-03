import asyncio
import contextlib
import socket
import struct

import polars as pl
import pytest

pymodbus = pytest.importorskip("pymodbus")
from pymodbus.client import AsyncModbusTcpClient

from ot_lab.protocols.modbus import replay_modbus


def test_modbus_adapter_replays_read_only_float32_input_registers(tmp_path):
    frame = pl.DataFrame({
        "timestamp": ["2025-01-01T00:00:00+00:00"],
        "asset_id": ["PUMP-01"], "tag_id": ["flow_l_min"], "value": [12.5],
    }).with_columns(pl.col("timestamp").str.to_datetime(time_zone="UTC"))
    telemetry = tmp_path / "telemetry.parquet"
    frame.write_parquet(telemetry)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]

    async def verify():
        task = asyncio.create_task(replay_modbus(telemetry, port=port, realtime=False, stay_open=True))
        client = AsyncModbusTcpClient("127.0.0.1", port=port, timeout=0.2)
        try:
            for _ in range(50):
                if task.done():
                    await task
                if client.connected:
                    client.close()
                await client.connect()
                if client.connected:
                    response = await client.read_input_registers(0, count=2, device_id=1)
                    if not response.isError():
                        assert struct.unpack(">f", struct.pack(">HH", *response.registers))[0] == 12.5
                        write_response = await client.write_register(0, 0, device_id=1)
                        assert write_response.isError()
                        return
                await asyncio.sleep(0.05)
            raise AssertionError("Modbus adapter did not return input registers")
        finally:
            client.close()
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    asyncio.run(verify())
