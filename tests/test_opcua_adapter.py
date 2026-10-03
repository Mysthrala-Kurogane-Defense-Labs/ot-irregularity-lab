import asyncio
import contextlib
import socket

import polars as pl
import pytest

pytest.importorskip("asyncua")

from asyncua import Client, ua

from ot_lab.protocols.opcua import replay_opcua


def test_opcua_adapter_maps_canonical_signal_as_read_only_variable(tmp_path):
    frame = pl.DataFrame({
        "timestamp": ["2025-01-01T00:00:00+00:00"],
        "asset_id": ["PUMP-01"], "tag_id": ["flow_l_min"],
        "value": [12.5], "unit": ["L/min"], "signal_class": ["flow"],
        "engineering_min": [0.0], "engineering_max": [3000.0],
    }).with_columns(pl.col("timestamp").str.to_datetime(time_zone="UTC"))
    telemetry = tmp_path / "telemetry.parquet"
    frame.write_parquet(telemetry)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    endpoint = f"opc.tcp://127.0.0.1:{port}/ot-lab/"

    async def verify():
        task = asyncio.create_task(replay_opcua(telemetry, endpoint, realtime=False, stay_open=True))
        try:
            for _ in range(50):
                if task.done():
                    await task
                try:
                    async with Client(endpoint, timeout=0.2) as client:
                        ns = await client.get_namespace_index("urn:ot-irregularity-lab:telemetry:1")
                        root = await client.nodes.objects.get_child([f"{ns}:PUMP-01"])
                        tag = await root.get_child([f"{ns}:flow_l_min"])
                        assert await tag.read_value() == 12.5
                        assert ua.AccessLevel.CurrentWrite not in await tag.get_access_level()
                        with pytest.raises(Exception) as exc_info:
                            await tag.write_value(99.0)
                        assert exc_info.value.code in {ua.StatusCodes.BadNotWritable, ua.StatusCodes.BadUserAccessDenied}
                        properties = await tag.get_children()
                        values = {str(await item.read_browse_name()): await item.read_value() for item in properties}
                        assert "L/min" in values.values()
                        assert 3000.0 in values.values()
                        return
                except (OSError, TimeoutError):
                    await asyncio.sleep(0.05)
            raise AssertionError("OPC UA adapter did not accept a client connection")
        finally:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    asyncio.run(verify())
