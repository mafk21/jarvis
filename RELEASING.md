# Release Process

Only the project owner or an explicitly authorized maintainer may publish JARVIS releases.

## 1. Define the release

- Choose the version using semantic versioning where practical.
- Review merged changes and identify user-visible behavior, breaking changes, migrations, and known limitations.
- Confirm the target commit contains no unresolved ownership or licensing claims for the material being released.

## 2. Validate

Run the repository's documented validation, including:

```bash
python -m pytest -q
python install_jarvis.py --check
python -m compileall -q main.py ui.py install_jarvis.py core actions memory plugins
```

For HUD changes, also run the checks documented in `CONTRIBUTING.md`. Required GitHub Actions checks must pass on the release commit. Do not bypass or weaken tests to publish.

## 3. Security and privacy review

- Review dependency and code-scanning results rather than relying only on a green workflow status.
- Confirm no credentials, private logs, runtime databases, recordings, user content, browser profiles, or personal paths are included.
- Document new permissions, network destinations, storage, telemetry, and third-party data flows.
- Verify sensitive actions still require the intended confirmation.

## 4. Package and smoke-test

- Build packages only from the selected commit using the tracked release workflow.
- Test first-run setup, launch, upgrade, settings, desktop-shortcut choice, and uninstall/recovery behavior on supported platforms where available.
- Verify artifacts and checksums correspond to the selected commit.
- Never claim signing or notarization unless the artifact was actually signed with the owner's valid platform credentials.

## 5. Publish

- Write release notes with highlights, fixes, security/privacy changes, upgrade steps, known limitations, and artifact checksums.
- Create a signed `v*` tag from the validated commit. The tracked release workflow reruns its matrix, packages clean source archives and checksums, and opens a draft release.
- Review every generated artifact and note before publishing the draft.
- Do not label a build stable when critical known regressions remain.

Automated archives are checksum-protected source packages, not code-signed native installers. Do not describe them as signed. Native Windows signing and macOS signing/notarization require the owner's private certificates in protected secrets; never commit signing keys.

## 6. After release

- Confirm downloads and installation instructions work.
- Monitor private vulnerability reports, issue reports, and failed installation patterns.
- If a severe defect is found, document it promptly and either patch, withdraw, or clearly mark the affected release.
- If an unpublished draft is wrong, remove the draft and tag, fix `main` through normal review, and create a new tag. For a published security defect, publish a fixed release and advisory; never silently replace existing artifacts.

Releases are never automatic merely because a commit reaches `main`.
