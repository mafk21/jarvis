# Contributing to JARVIS

Thank you for helping improve JARVIS. Contributions should be focused, cross-platform, secure, and testable.

## Before you begin

- Search existing issues and pull requests.
- Use an issue for substantial behavior or architecture changes before implementation.
- Never include credentials, personal data, runtime databases, recordings, browser profiles, generated user content, or private logs.
- Keep the Male and Female editions functionally equivalent unless an issue explicitly concerns presentation.

## Development setup

Requires Python 3.11 or newer and Node.js 22 for HUD development.

```bash
git clone https://github.com/mafk21/jarvis.git
cd jarvis
python -m venv .venv
# Windows: .venv\Scripts\python -m pip install -r requirements.txt
# macOS/Linux:
.venv/bin/python -m pip install -r requirements.txt pytest pytest-asyncio
```

HUD setup:

```bash
cd apex_ui
npm ci
npx tsc --noEmit
npm run build
```

## Validation

Run the smallest relevant test set while developing, then before submission run:

```bash
python -m pytest -q
python install_jarvis.py --check
python -m compileall -q main.py ui.py install_jarvis.py core actions memory plugins
```

For HUD changes also run `npm audit --audit-level=low`, `npx tsc --noEmit`, and `npm run build` in `apex_ui/`.

## Pull requests

1. Branch from the latest `main`.
2. Keep unrelated changes out of the PR.
3. Explain behavior, security/privacy implications, platforms tested, and exact test results.
4. Update documentation and generated HUD output when applicable.
5. Wait for all required CI checks and review.

By intentionally submitting a contribution, you agree that your contribution is licensed under the repository's [JARVIS Personal-Use License](LICENSE) and may be used, modified, and included in JARVIS. A contribution does not grant permission to publish, redistribute, sublicense, sell, or separately exploit JARVIS or derivatives.
