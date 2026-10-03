# Contributing

Contributions must preserve independence from MKDL products and infrastructure, avoid detector-specific tuning, and use synthetic inputs. Changes to telemetry or scenario behavior require versioning discussion and deterministic tests. Process relationships should be expressed as coupled dynamics rather than independent random walks.

Run `uv run pytest` before submitting. Do not add real customer or facility data. Include numeric parameter ranges and explain affected signals for new scenario types. Software is Apache-2.0; dataset terms are declared per release.
