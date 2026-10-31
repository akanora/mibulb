# Publishing Mi Bulb

## Releasing a version

1. Set `__version__` in `mibulb/__init__.py`, for example `0.10.0`.
2. Commit and push to `main`. CI runs the tests, lint and an installer build.
3. Tag and push. The Release workflow builds `MiBulb-Setup.exe` and `MiBulb-Portable.exe` from the tag, writes `SHA256SUMS.txt`, signs build-provenance attestations and publishes the release:
   ```powershell
   git tag v0.10.0
   git push origin v0.10.0
   ```

Installed copies update themselves on their next start.

## winget (Windows Package Manager)

Getting listed means people can install with `winget install akanora.MiBulb`. Listing works through a pull request to Microsoft's public [winget-pkgs](https://github.com/microsoft/winget-pkgs) repository, opened from your GitHub account.

1. After a release is published, generate the manifests from it:
   ```powershell
   python tools/winget_manifest.py 0.10.0
   ```
   This writes `packaging/winget/0.10.0/*.yaml`, filled in with the release's download link and SHA-256.
2. Check them (needs winget, which is built into Windows 11):
   ```powershell
   winget validate packaging/winget/0.10.0
   winget install --manifest packaging/winget/0.10.0
   ```
3. Submit with [wingetcreate](https://github.com/microsoft/winget-create). It forks winget-pkgs for you and opens the pull request:
   ```powershell
   winget install wingetcreate
   wingetcreate submit --token <a GitHub token with public_repo> packaging/winget/0.10.0
   ```
4. Microsoft's bots and moderators review the pull request, which usually takes a few days. For later versions, `wingetcreate update akanora.MiBulb --version 0.11.0 --urls <setup url> --submit` is enough.

## Code signing (removes the SmartScreen warning)

The exe is built and attested by GitHub, but it isn't signed with a code-signing certificate, so Windows SmartScreen warns on first run. Open-source projects can get free signing from the **SignPath Foundation**:

1. Apply at <https://signpath.org/apply>. They check that the project is open source and builds on CI, which this repo already does.
2. Once accepted, SignPath gives you an organization id, a project slug and a signing policy. Add them, plus an API token, as repository secrets: `SIGNPATH_API_TOKEN`, `SIGNPATH_ORGANIZATION_ID`.
3. In `.github/workflows/release.yml`, after "Build portable exe and installer", upload `dist/` as an artifact and add their action:
   ```yaml
   - uses: signpath/github-action-submit-signing-request@v1
     with:
       api-token: ${{ secrets.SIGNPATH_API_TOKEN }}
       organization-id: ${{ secrets.SIGNPATH_ORGANIZATION_ID }}
       project-slug: mibulb
       signing-policy-slug: release-signing
       github-artifact-id: ${{ steps.upload.outputs.artifact-id }}
       wait-for-completion: true
       output-artifact-directory: dist
   ```
   SignPath's onboarding gives the exact values. Keep the checksum and attestation steps after signing, so they cover the signed files.

A paid certificate from a certificate authority works too. Even signed, a new publisher builds SmartScreen reputation over the first few hundred downloads.
