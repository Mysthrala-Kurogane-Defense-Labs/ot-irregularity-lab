# Linux process-pool deadlock after native thread-pool initialization

## Observation

Recent GitHub Actions jobs completed setup and lint but remained in the `pytest` step. A Linux reproduction on the current checkout reached the parallel batch tests with two child processes idle in `futex` waits while pytest waited for their results. The Windows test suite had not reproduced it.

## Resolution

NumPy and Polars can initialize native worker threads before the test's process pool is created. On Linux, the default `fork` start method can copy locks from those thread pools without copying their owning threads. Both resumable and ordinary batch generation now select the `spawn` context explicitly. A severity-frequency test also constructs its immutable Pydantic event once per severity level rather than thousands of times; the stochastic sample count remains 2,000 per level.

## Validation

- Linux WSL targeted resume/parallel tests passed: 3 tests.
- Linux WSL full suite passed: 128 tests, including the OPC UA extra.
- The same pre-fix Linux full suite stalled in the process-pool section; this reproduction is local WSL evidence, not a completed GitHub Actions run.
- GitHub Actions status after pushing the fix is recorded separately; a green remote run is still required before treating the CI issue as closed.
