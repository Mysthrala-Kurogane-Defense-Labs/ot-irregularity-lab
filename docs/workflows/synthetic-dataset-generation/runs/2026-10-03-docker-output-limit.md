# Docker submission output-limit hardening

## Change

The previous 20 ms file-size poll watched a writable host bind mount. A fast or highly parallel submission could write beyond the configured ceiling between polls. The Docker runner now also applies `RLIMIT_FSIZE` through Docker's `--ulimit fsize=LIMIT:LIMIT`, inherited by the container's model process tree. The mounted output file is therefore bounded by the kernel before data can exceed the ceiling. `--log-driver=none` disables persistent Docker container logs; the runner still drains and bounds the Docker CLI's attached stdout/stderr. The existing poll remains as defense in depth. The output file remains the only writable host bind mount; input is read-only.

An attempted output-tmpfs design was rejected by an end-to-end experiment: Docker discards tmpfs contents when the container stops, before an external `docker cp` can retrieve them. No tmpfs design is used by the shipped runner.

## Validation

- Local tests: `uv run --python 3.12 pytest tests/test_simulation.py -q`; Ruff and `git diff --check` passed.
- Docker Engine through Docker Desktop 29.8.1: a local submission image repeatedly wrote 32 KiB blocks with a configured 1,024-byte maximum. It failed with `OSError: [Errno 27] File too large`; the host bind-mount file was exactly 1,024 bytes.
- A local audit image exercised the actual `run_docker_submission` path and recorded UID 65534, zero effective capabilities, read-only input, read-only root, write denial outside the output mount, no network connection, pids limit 128, memory limit 2 GiB and CPU quota 2 CPUs. It saw only `input.parquet` and `output.jsonl` in `/ot-lab`.
- The runner removed test containers after completion/failure. No model image was pulled from a registry; the smoke images were already local.

## Evidence and limits

Docker documents `--ulimit` support for RLIMIT values and the `none` logging driver in the [`docker run` reference](https://docs.docker.com/reference/cli/docker/container/run/). The host Docker daemon, kernel, runtime and arbitrary image contents remain trusted; this is not a hostile-kernel or host-compromise boundary, and it is not a security certification. A submission image can include its own files. Challenge randomization reduces run memorization but does not prevent a submission author from bundling external data or code in the image.
