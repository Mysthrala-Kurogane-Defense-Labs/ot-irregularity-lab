# Release signatures

New software and dataset releases can use keyless Sigstore signing without a
persistent private key. The repository keeps the OIDC permission scoped to the
signing jobs. The workflow uses [Gitsign](https://github.com/sigstore/gitsign)
for Git tags and the pinned
[Sigstore GitHub Action](https://github.com/sigstore/gh-action-sigstore-python)
for release assets.

Before enabling these workflows on the default branch, configure the GitHub
Environment `release-signing` with the approved release reviewer(s), prevent
self-approval/bypass where the repository settings allow it, and restrict its
deployment refs to `main`, `v*`, and `dataset-v*`. Both signing jobs reference
this environment. An environment with no required reviewers does not add an
approval gate; until reviewers are configured, treat signing as available to
the repository's write-authorized workflow dispatchers.

## Signed Git tags

From the default `main` branch, dispatch **Sign release tag** with a new tag
(`vX.Y.Z` or `dataset-vX.Y.Z`) and a full commit SHA reachable from
`origin/main` whose core, OPC UA, and Modbus CI checks have all succeeded. The
job waits for approval from the configured `release-signing` environment. The
workflow refuses existing tags, verifies the generated Sigstore signature
against its GitHub Actions identity, and only then pushes the tag. It does not
create a GitHub Release or replace historical tags.

Verify a tag with the same signer identity and issuer:

```bash
gitsign verify-tag \
  --certificate-oidc-issuer=https://token.actions.githubusercontent.com \
  --certificate-github-workflow-ref=https://github.com/Mysthrala-Kurogane-Defense-Labs/ot-irregularity-lab/.github/workflows/sign-release-tag.yml@refs/heads/main \
  vX.Y.Z
```

For dataset releases, use the `dataset-vX.Y.Z` tag as the final argument.

## Release assets and dataset manifests

When a GitHub Release is published, **Sign release assets** waits for the
`release-signing` environment approval, then uses the GitHub Actions OIDC
identity to sign its existing assets and attach Sigstore bundles to the
release. This covers dataset release manifests, checksums, telemetry archives,
and separate label archives. The job verifies its signatures before finishing.
A release is considered fully signed only after this workflow completes
successfully and the `.sigstore.json` bundles are present.

Verify a release asset using the identity for the publishing tag:

```bash
sigstore verify identity \
  --bundle release_manifest.json.sigstore.json \
  --certificate-identity 'https://github.com/Mysthrala-Kurogane-Defense-Labs/ot-irregularity-lab/.github/workflows/sign-release-assets.yml@refs/tags/dataset-vX.Y.Z' \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com \
  release_manifest.json
```

Replace the asset and tag names for the file being checked. Historical releases
remain unsigned and are not rewritten by these workflows. The repository's
dataset verifier continues to validate checksums, archive contents, CRCs, and
telemetry/ground-truth separation independently of signature verification.
