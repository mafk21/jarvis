# JARVIS Governance

JARVIS is currently an owner-led project. This document explains how decisions are made without implying that every proposal will be accepted or that contributors surrender authorship.

## Roles

- **Project owner:** sets product direction, appoints or removes maintainers, approves releases, and makes final decisions when consensus is not possible.
- **Maintainers:** review issues and pull requests, enforce security and quality requirements, and may merge changes within their assigned areas.
- **Contributors:** propose, discuss, test, document, or implement changes. A contribution does not automatically grant maintainer status.

Current authority is derived from repository permissions. GitHub's access controls are the source of truth; this file does not grant access by itself.

## Decision process

1. Small, reversible fixes may be decided in a pull request.
2. Significant architecture, privacy, licensing, dependency, data-flow, or compatibility changes should begin with an issue or design discussion.
3. Maintainers seek practical consensus using user impact, security, cross-platform behavior, maintainability, evidence, and test results.
4. The project owner makes the final decision when consensus cannot be reached.

Decisions that materially change architecture or trust boundaries should be recorded in the pull request or an architecture decision record so the reasoning remains reviewable.

## Merge and release requirements

A change is eligible to merge only when:

- its ownership and license are compatible with the repository;
- required automated checks pass;
- relevant Windows, macOS, and Linux behavior is considered;
- security, privacy, permissions, storage, and external data flows are documented;
- tests cover important behavior and regressions;
- user-facing documentation is updated when needed; and
- a maintainer with appropriate repository permission approves it.

Passing checks does not guarantee acceptance. Maintainers may reject changes that are unsafe, out of scope, duplicative, insufficiently maintainable, or inconsistent with product direction.

Releases follow `RELEASING.md`. Only the project owner or an explicitly authorized maintainer may publish a release.

## Contributor credit and authorship

JARVIS preserves genuine authorship in Git history and contributor records. Replacing or removing code does not justify hiding who originally wrote it. Material third-party code must include accurate provenance and licensing information.

Do not submit code copied or closely rewritten from a source whose license is incompatible with this repository. Changing names, formatting, or structure does not make derived code independent.

## Security and conduct

Security reports follow `SECURITY.md`; never place vulnerabilities or secrets in a public issue. Community behavior follows `CODE_OF_CONDUCT.md`. Maintainers may restrict participation to protect users and contributors.

## Changes to governance

Governance changes use the same review process as other repository changes. The project owner may update this model as the maintainer group grows; changes should be documented publicly in the repository.
