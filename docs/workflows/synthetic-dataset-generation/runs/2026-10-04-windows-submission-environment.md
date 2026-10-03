# Preserve required Windows system environment for local model commands

## Finding

An external scikit-learn model failed under `ot-lab run-model` on Windows when importing libraries that initialize Winsock. The runner intentionally starts trusted local model commands with a small environment, but had removed `SystemRoot`: the library import raised Windows error 10106, and a direct `getaddrinfo` reproduction returned error 11003 without `SystemRoot`.

## Change

Preserve only the standard Windows runtime variables `SystemRoot`, `WINDIR`, `COMSPEC`, and `PATHEXT` when present. Temporary paths and the `OT_LAB_INPUT` / `OT_LAB_OUTPUT` variables remain scoped to the temporary inference directory. This does not make `run-model` a filesystem or network sandbox; it remains documented for trusted local commands.

## Validation

- Added a Windows-only test that runs a separate Python process, resolves `localhost` through Winsock, and writes the required prediction file.
- Windows Python 3.12 full suite: 131 passed; Ruff, lock check, and diff check passed.
- Linux WSL Python 3.12 with dev, OPC UA, Modbus and lint extras: Ruff and full pytest passed; the Windows-only test is skipped on Linux.
- The three external-model containers then ran against the v0.4.0 test subset through `run-container`, with no runner errors.
