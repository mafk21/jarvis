<p align="center">
  <img src="docs/assets/jarvis-wordmark.png" alt="JARVIS OS — Operating Companion" width="900">
</p>

<p align="center">
  <strong>A local-first AI system that can see, speak, remember, and act.</strong>
</p>

<p align="center">
  <a href="https://jarvis-khaki-eight.vercel.app/">Website</a> ·
  <a href="https://jarvis-khaki-eight.vercel.app/docs/">Documentation</a> ·
  <a href="docs/PRIVACY.md">Privacy</a> ·
  <a href="https://github.com/mafk21/OS/issues">Issues</a>
</p>

---

## What is JARVIS?

JARVIS turns your computer into an AI-operated workspace. Speak or type a goal and it can understand your screen, use applications, work with files, research, write and run code, coordinate specialist agents, and complete long-running tasks with visible progress.

It is source-available for personal, non-commercial use and runs on **Windows, macOS, and Linux**.

## Highlights

- **Voice, text, and vision** — full-duplex conversation, interruption, typed input, and screen understanding.
- **Computer control** — applications, browser, terminal, files, keyboard, mouse, clipboard, media, and system controls.
- **Durable memory** — local timelines, preferences, documents, commitments, learning records, and searchable history.
- **Long-running work** — specialist workers, checkpoints, cancellation, recovery, progress, and verified outputs.
- **Connected services** — optional integrations for mail, calendars, drives, messaging, development tools, productivity platforms, REST, webhooks, and MCP.
- **Owner control** — confirmation gates, encrypted credentials, scoped tools, audit history, and explicit privacy controls.
- **Two equal editions** — Guardian and Confidante offer different presentation styles with the same capabilities, safeguards, and reliability.

For the complete feature guide and architecture, visit the **[documentation website](https://jarvis-khaki-eight.vercel.app/docs/)**.

## Requirements

Before installing JARVIS, make sure you have:

- **Windows 10/11, macOS, or Linux** on a 64-bit computer.
- **Python 3.11 or 3.12 (64-bit).** Python 3.12 is recommended. Python 3.13+ is not currently supported because some native packages may not provide compatible wheels yet.
- **Git** for cloning and updating the repository.
- **An internet connection** for the initial Python dependencies and Playwright browser download.
- **At least 2 GB of free disk space.** Keep 5 GB free for a more comfortable installation; local Ollama models require additional space.
- **A microphone and speakers/headphones** for voice features. Text input can be used without them.
- **At least one supported AI provider** configured during onboarding: Anthropic Claude for text reasoning, Gemini or OpenAI for realtime voice and multimodal sessions, or a supported local model.

You do **not** need Microsoft Visual C++ Build Tools when using the supported Python 3.12 installation.

## Install

### Windows (PowerShell)

Use Python 3.12 explicitly so Windows does not accidentally launch a newer, unsupported Python installation:

```powershell
git clone https://github.com/mafk21/jarvis.git
cd jarvis
py -3.12 setup.py
py -3.12 main.py
```

If `py -3.12` is unavailable, install Python 3.12 first:

```powershell
winget install -e --id Python.Python.3.12
```

Close and reopen PowerShell after installation, then run the Windows commands above.

### macOS or Linux

```bash
git clone https://github.com/mafk21/jarvis.git
cd jarvis
python3.12 setup.py
python3.12 main.py
```

The setup command installs the required Python packages and Playwright browsers. Configure Gemini, OpenAI, or supported local AI components during onboarding. Credentials and model files are not included in the repository.

After setup, you can also use the native launcher included for your system:

| Platform | Launcher |
| --- | --- |
| Windows | `Start_JARVIS.bat` |
| macOS | `./Start_JARVIS.command` |
| Linux | `./Start_JARVIS.sh` |

## Local-first, clearly

The interface, orchestration, memory, tools, automations, credential vault, and action history run locally. Cloud models and connected services receive data only when you configure and use them. A completely local setup requires local model, speech-to-text, and text-to-speech components.

Read **[Privacy and Data Flow](docs/PRIVACY.md)** before connecting accounts or enabling remote features.

## Development

```bash
python -m pytest -q
python install_jarvis.py --check
```

HUD development and build instructions are available in the **[documentation](https://jarvis-khaki-eight.vercel.app/docs/)**.

## Contributing and support

Issues and focused pull requests are welcome. Read [CONTRIBUTING.md](CONTRIBUTING.md) before making changes and use [SUPPORT.md](SUPPORT.md) for help and bug-report guidance.

1. Keep Windows, macOS, and Linux behavior aligned.
2. Do not commit credentials, runtime databases, memories, recordings, or generated user data.
3. Run the relevant tests and report real results.
4. Update documentation when behavior changes.

Security vulnerabilities must not be posted publicly. Follow the private reporting process in [SECURITY.md](SECURITY.md).

## Release status

JARVIS is currently public beta software. Use the latest release, review permissions before approving sensitive actions, and expect rapid changes while installation and packaging mature.

## License

JARVIS is source-available under the [JARVIS Personal-Use License](LICENSE).

You may download, run, study, and modify JARVIS on devices you own or control for personal, non-commercial use. Publishing, redistribution, sublicensing, commercial use, and using JARVIS or its contents to develop or distribute another project are not permitted without separate written permission.

This is not an OSI-approved open-source license. See [LICENSE](LICENSE) for the complete terms.
