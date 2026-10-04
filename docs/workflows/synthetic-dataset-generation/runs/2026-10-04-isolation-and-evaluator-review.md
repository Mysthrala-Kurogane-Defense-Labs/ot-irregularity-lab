# Docker isolation and host evaluator review

## Objective

Verify the local Docker submission boundary against the model-input requirements, review all `src/ot_lab` modules for source-backed security issues, and fix any confirmed issue that could make evaluation unavailable.

## Scope and revision

- Target: repository commit `df6f0ad` (`fix/event-episode-metrics`), with a separate local fix in the working tree.
- Scope: all 12 Python modules in `src/ot_lab`; supporting test: `tests/test_simulation.py`.
- Threat boundary: a user-selected model image can control its output, but inference must not read ground truth, other datasets, or host network and must not access the Internet.
- Report: Codex Security scan `12e77925-451a-42dd-b1c3-ebcf93ac7d45`, target revision `df6f0ad`, one low-severity host-side CPU finding. An independent baseline reviewer checked the same immutable source and found no additional vulnerability or source-backed container escape.

## Evidence and decisions

| Operation | Observed result | Decision |
| --- | --- | --- |
| Static review of `src/ot_lab` | Container receives a read-only telemetry file and a single writable prediction file. Ground truth and sibling run files are not mounted. Image pulls are disabled; network, capabilities, root filesystem, user, PID, CPU and memory are constrained. | No source-backed container escape found. The host OS, Docker daemon, VM and kernel remain trusted boundaries. |
| Local Docker adversarial smoke | Container saw only input/output mounts, ran as UID 65534 with zero effective capabilities, had a read-only root filesystem and input, and could not write other mount paths, see the ground truth/sibling dataset/host environment sentinel, or reach 1.1.1.1. Cgroup limits reported 128 processes, 2 GiB memory, and 2 CPUs. | Confirmed those controls in this Docker Desktop environment; this is not a daemon, host, or kernel penetration test. |
| Docker output overflow smoke | With a 1,024-byte configured ceiling, the test image received `EFBIG`; the host output mount remained 1,024 bytes and the predictions were not published. | The configured output-file ceiling holds in the tested local environment. |
| Timestamp PR-AUC source path at `df6f0ad` | `_timestamp_scores()` scanned every prediction interval and every event interval for each expected sample after output parsing. The runner's file-size ceiling did not prevent multiplicative host-side work. | Reported as CWE-400, low severity, because it affects local CLI evaluation and requires an operator to run the input. |
| Independent performance probe | 5,000 prediction intervals × 2,400 expected samples took 0.958 seconds before the change and 0.011 seconds with the ordered heap sweep in WSL. A maximum-output extrapolation was not measured directly. | Replace the nested scan with an O((P+S) log P) temporal sweep and preserve half-open interval semantics. |
| WSL full suite after prediction and event interval sweeps | Python 3.13.11; `uv run --extra dev --group lint pytest`: 139 passed, 3 skipped. `ruff check src tests`: passed. | Local Linux validation of the working-tree change passed. |
| Structured local review | First pass found the event-label scan still had per-sample linear work. That finding was verified and fixed with a second active-interval heap; the final review returned `autoreview clean: no accepted/actionable findings reported`. | The final patch processes both prediction scores and event labels using ordered active intervals, preserving half-open endpoint behavior. |
| Windows full suite attempt | `uv run pytest` could not repair the existing `.venv` because Windows denied removal of the `lib64` directory symlink. An isolated `.venv-ci` lacked the dev dependencies. No existing environment was deleted. | Windows validation of this working-tree patch remains pending; use a clean CI runner or repair the venv deliberately. |

## Validation and handoff

- Acceptance: source review, local Docker smoke, output-cap smoke, prediction and event interval sweeps, and regression tests completed.
- Residual security boundary: no test attempted Docker daemon compromise, host/VM escape, or kernel escape. `run-model` executes a local process and is not a security sandbox.
- Publication: the interval-sweep change and this record are local working-tree changes. PR #4 still points to `df6f0ad`; its existing green CI does not validate these changes. Commit and push the patch, then require fresh CI before closing the reported finding.
- Reusable lesson: bound host-side work after container execution as well as CPU, memory, time and output size inside the container. Model output and hidden event arrays remain untrusted inputs to host scoring.
- Next action: commit and push the fix to PR #4, run CI, and update the security finding status only after the pushed revision is validated.
