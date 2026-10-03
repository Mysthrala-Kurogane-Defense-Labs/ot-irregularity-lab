"""Run an external model process with telemetry-only input."""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import tempfile
from pathlib import Path


def run_submission(command: str, run_dir: Path, output: Path, timeout_s: int = 300) -> Path:
    """Run a local executable; copy telemetry into a temporary input path and expose no truth path."""
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
        process = subprocess.run(argv, cwd=sandbox, env=env, timeout=timeout_s, check=False, capture_output=True, text=True)
        if process.returncode:
            raise RuntimeError(f"model command exited {process.returncode}: {process.stderr[-2000:]}")
        if not predictions_path.is_file():
            raise FileNotFoundError("model command did not create {output}")
        output.write_bytes(predictions_path.read_bytes())
    return output


def run_docker_submission(image: str, run_dir: Path, output: Path, timeout_s: int = 300) -> Path:
    """Execute an image without network, with only telemetry mounted read-only and output writable."""
    docker = shutil.which("docker")
    if docker is None:
        raise RuntimeError("Docker CLI is not installed")
    telemetry = (run_dir / "telemetry.parquet").resolve()
    if not telemetry.is_file():
        raise FileNotFoundError(telemetry)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="ot-lab-docker-") as tmp:
        sandbox = Path(tmp).resolve()
        input_path = sandbox / "input.parquet"
        output_dir = sandbox / "out"
        output_dir.mkdir()
        output_path = output_dir / "output.jsonl"
        input_path.write_bytes(telemetry.read_bytes())
        output_mount = f"type=bind,src={output_dir},dst=/ot-lab/out"
        args = [
            docker, "run", "--rm", "--network=none", "--read-only", "--cap-drop=ALL",
            "--security-opt=no-new-privileges:true", "--pids-limit=128", "--memory=2g",
            "--cpus=2", "--user=65534:65534", "--tmpfs", "/tmp:rw,noexec,nosuid,size=64m",
            "--mount", f"type=bind,src={input_path},dst=/ot-lab/input.parquet,readonly",
            "--mount", output_mount,
            "--env", "OT_LAB_INPUT=/ot-lab/input.parquet", "--env", "OT_LAB_OUTPUT=/ot-lab/out/output.jsonl",
            image,
        ]
        result = subprocess.run(args, timeout=timeout_s, check=False, capture_output=True, text=True)
        if result.returncode:
            raise RuntimeError(f"container exited {result.returncode}: {result.stderr[-2000:]}")
        if not output_path.is_file():
            raise FileNotFoundError("container did not create /ot-lab/out/output.jsonl")
        output.write_bytes(output_path.read_bytes())
    return output
