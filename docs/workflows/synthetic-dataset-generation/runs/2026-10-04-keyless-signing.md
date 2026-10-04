# Keyless signing workflow preparation

## Changes

- Added a manually dispatched workflow to sign new `vX.Y.Z` software tags or
  `dataset-vX.Y.Z` tags with Gitsign's GitHub Actions OIDC provider. It only
  runs from `main`, requires a full commit SHA reachable from `origin/main`,
  checks the core/OPC UA/Modbus CI jobs, refuses to replace an existing tag,
  verifies the Sigstore workflow identity, and pushes only after verification.
- Added a release-published workflow that signs the existing release assets
  (including dataset manifests) and verifies their signatures before it
  completes. The action and actions/setup-go and actions/checkout references
  are pinned to immutable commit SHAs.
- Added operator and consumer instructions in `RELEASE_SIGNING.md`.

## Validation and limits

- `actionlint` passed for both workflows.
- Extracted the tag signing shell block passed `bash -n`.
- Existing release candidate package verification passed independently; the
  workflows do not modify historical releases or publish the local v0.6.0-rc3
  candidate.
- The Sigstore action declares `id-token: write` and `contents: write` only on
  the release-signing job. The tag workflow scopes those permissions to its job
  and adds `checks: read` for the required CI gate.
- Actual OIDC signing and Rekor verification cannot run from this local
  checkout. The first live signing run must use GitHub Actions and be checked
  independently after an authorized new release. Earlier release tags and
  assets remain unsigned.

## Sources

- [Sigstore GitHub Actions signing guide](https://docs.sigstore.dev/quickstart/quickstart-ci/)
- [Sigstore Gitsign](https://github.com/sigstore/gitsign)
- [Go release history](https://go.dev/doc/devel/release)
