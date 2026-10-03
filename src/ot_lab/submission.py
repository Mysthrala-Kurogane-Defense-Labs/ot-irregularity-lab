"""Run an external model process with telemetry-only input."""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path

DEFAULT_MAX_OUTPUT_BYTES = 64 * 1024 * 1024
DEFAULT_MAX_LOG_BYTES = 1024 * 1024


def _validate_limits(timeout_s: int, max_output_bytes: int) -> None:
    if timeout_s <= 0:
        raise ValueError("timeout_s must be positive")
    if max_output_bytes <= 0:
        raise ValueError("max_output_bytes must be positive")


def _run_bounded(
    argv: list[str], *, cwd: Path, env: dict[str, str], timeout_s: int,
    max_output_bytes: int, monitored_output: Path | None,
) -> None:
    """Run while bounding output-file size, wall time, and retained process logs."""
    started = time.monotonic()
    logs: dict[str, bytearray] = {"stdout": bytearray(), "stderr": bytearray()}
    with subprocess.Popen(argv, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE) as process:
        def drain(name: str, stream) -> None:
            while data := stream.read(65536):
                remaining = DEFAULT_MAX_LOG_BYTES - len(logs[name])
                if remaining > 0:
                    logs[name].extend(data[:remaining])

        drainers = [threading.Thread(target=drain, args=(name, stream), daemon=True) for name, stream in (("stdout", process.stdout), ("stderr", process.stderr))]
        for thread in drainers:
            thread.start()
        try:
            while process.poll() is None:
                if time.monotonic() - started > timeout_s:
                    process.kill()
                    raise TimeoutError(f"submission exceeded timeout of {timeout_s} seconds")
                if monitored_output is not None and monitored_output.exists() and monitored_output.stat().st_size > max_output_bytes:
                    process.kill()
                    raise ValueError(f"submission output exceeds {max_output_bytes} bytes")
                time.sleep(0.02)
            return_code = process.wait()
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
            for thread in drainers:
                thread.join(timeout=1)
        if return_code:
            detail = logs["stderr"].decode("utf-8", errors="replace")
            raise RuntimeError(f"submission exited {return_code}: {detail[-2000:]}")


def run_submission(command: str, run_dir: Path, output: Path, timeout_s: int = 300, max_output_bytes: int = DEFAULT_MAX_OUTPUT_BYTES) -> Path:
    """Run a local executable; copy telemetry into a temporary input path and expose no truth path."""
    _validate_limits(timeout_s, max_output_bytes)
    telemetry = run_dir / "telemetry.parquet"
    if not telemetry.is_file():
        raise FileNotFoundError(telemetry)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="ot-lab-infer-") as tmp:
        sandbox = Path(tmp)
        input_path = sandbox / "input.parquet"
        predictions_path = sandbox / "output.jsonl"
        input_path.write_bytes(telemetry.read_bytes())
        argv = [part.replace("{input}", str(input_path)).replace("{output}", str(predictions_path)) for part in shlex.split(command)]
        env = {
            "PATH": os.environ.get("PATH", ""), "TEMP": str(sandbox), "TMP": str(sandbox),
            "OT_LAB_INPUT": str(input_path), "OT_LAB_OUTPUT": str(predictions_path),
        }
        _run_bounded(argv, cwd=sandbox, env=env, timeout_s=timeout_s, max_output_bytes=max_output_bytes, monitored_output=predictions_path)
        if not predictions_path.is_file():
            raise FileNotFoundError("model command did not create {output}")
        if predictions_path.stat().st_size > max_output_bytes:
            raise ValueError(f"submission output exceeds {max_output_bytes} bytes")
        output.write_bytes(predictions_path.read_bytes())
    return output


def run_docker_submission(image: str, run_dir: Path, output: Path, timeout_s: int = 300, max_output_bytes: int = DEFAULT_MAX_OUTPUT_BYTES) -> Path:
    """Execute an image without network, with only telemetry mounted read-only and output writable."""
    _validate_limits(timeout_s, max_output_bytes)
    docker = shutil.which("docker")
    if docker is None:
        raise RuntimeError("Docker CLI is not installed")
    telemetry = (run_dir / "telemetry.parquet").resolve()
    if not telemetry.is_file():
        raise FileNotFoundError(telemetry)
    with tempfile.TemporaryDirectory(prefix="ot-lab-docker-") as tmp:
        sandbox = Path(tmp).resolve()
        input_path = sandbox / "input.parquet"
        mounted_output = sandbox / "output.jsonl"
        cid_path = sandbox / "container.cid"
        input_path.write_bytes(telemetry.read_bytes())
        mounted_output.touch()
        args = [
            docker, "run", "--cidfile", str(cid_path), "--pull=never", "--rm", "--network=none", "--read-only", "--cap-drop=ALL",
            "--security-opt=no-new-privileges:true", "--pids-limit=128", "--memory=2g",
            "--cpus=2", "--user=65534:65534", "--tmpfs", "/tmp:rw,noexec,nosuid,size=64m",
            "--ulimit", f"fsize={max_output_bytes}:{max_output_bytes}",
            "--log-driver=none",
            "--env", "PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
            "--env", "TMPDIR=/tmp",
            "--mount", f"type=bind,src={input_path},dst=/ot-lab/input.parquet,readonly",
            "--mount", f"type=bind,src={mounted_output},dst=/ot-lab/output.jsonl",
            "--env", "OT_LAB_INPUT=/ot-lab/input.parquet", "--env", "OT_LAB_OUTPUT=/ot-lab/output.jsonl",
            image,
        ]
        try:
            _run_bounded(args, cwd=sandbox, env={**os.environ, "OT_LAB_OUTPUT": str(mounted_output)}, timeout_s=timeout_s, max_output_bytes=max_output_bytes, monitored_output=mounted_output)
        finally:
            if cid_path.is_file():
                container_id = cid_path.read_text(encoding="utf-8").strip()
                if container_id:
                    subprocess.run([docker, "rm", "--force", container_id], timeout=30, check=False, capture_output=True)
        output.parent.mkdir(parents=True, exist_ok=True)
        if not mounted_output.is_file():
            raise FileNotFoundError("container did not write the mounted /ot-lab/output.jsonl file")
        if mounted_output.stat().st_size > max_output_bytes:
            raise ValueError(f"submission output exceeds {max_output_bytes} bytes")
        output.write_bytes(mounted_output.read_bytes())
    return output
