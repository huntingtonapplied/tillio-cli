<div align="center">
  <img src=".readme/logo.png" alt="Tillio CLI" width="360"><br><br>
</div>

[![License](https://img.shields.io/badge/license-MIT-blue.svg)](#license)
[![Python](https://img.shields.io/badge/python-3.9+-blue.svg)](https://python.org)
[![Version](https://img.shields.io/badge/version-0.2.0-blue.svg)](pyproject.toml)
[![Status](https://img.shields.io/badge/status-active-success.svg)](#)

-----------------

**Tillio CLI** (`tillio`) is the command-line client for [Tillio](../README.md) — contribution-aware economic infrastructure for distributed project teams. It lets contributors and project owners submit and evaluate contributions from a local Git repository without leaving the terminal.

From inside a checked-out repo, the CLI parses local commits, scores and fingerprints code, submits contributions to the Tillio API for AI evaluation, and lists your projects and contribution scores. It talks to a running Tillio [backend](../backend/README.md).

---

## Install

```bash
# Published binary (recommended)
curl -fsSL https://downloads.tillio.ai/cli/install.sh | bash
# installs the `tillio` binary to /usr/local/bin (override with --install-dir)

# Or from a clone of this repo (editable dev install)
pip install -e .
```

This registers the `tillio` entry point (`tillio_cli.main:main`).

---

## Authentication

The CLI needs an API key for your Tillio account and the API base URL:

```bash
tillio login                       # interactive: authenticate & store API key

# or configure via environment
export TILLIO_API_KEY=<your-key>
# The API URL defaults to the production host (https://api.tillio.ai).
# Only set TILLIO_API_URL to point at a local/dev backend:
export TILLIO_API_URL=http://localhost:8000   # dev override only
```

Credentials are stored in the CLI config; `TILLIO_API_KEY` / `TILLIO_API_URL` env vars take precedence. Run `tillio doctor` to verify setup.

---

## Commands

| Command | Description |
|---|---|
| `tillio login` | Authenticate and store an API key |
| `tillio status` | Show project and recent contribution info |
| `tillio submit` | Parse local commits and send them to the Tillio API |
| `tillio eval` | Evaluation command group (evaluate code / contribution / repo) |
| `tillio projects` | List, create, and delete projects |
| `tillio add <repo-url>` | Create a project in Tillio from a repository URL |
| `tillio contributions` | List your contributions with their scores |
| `tillio score` | Score files, modules, or directories in a repository |
| `tillio fingerprint` | Analyze and store repository size/complexity stats |
| `tillio index` | Generate a `TILLIO.md` from the project eval index |
| `tillio completion` | Generate shell completion scripts |
| `tillio doctor` | Check CLI setup and diagnose issues |

Global options: `-o/--output {table,json,yaml}`, `--no-color`, `-v/--verbose`, `--debug`, `--ci`.

### Example

```bash
cd ~/my-project
tillio login
tillio submit                      # send local commits for AI evaluation
tillio contributions -o json       # list your scored contributions as JSON
```

---

## Stack

- **Language:** Python 3.9+
- **CLI framework:** Click 8
- **HTTP:** httpx · **Config:** PyYAML · **Output:** Rich
- **Tests:** pytest (`unit` = no network/git, `integration` = real git repos)

```bash
pytest              # or: pytest -m unit  /  pytest -m integration
```

---

## Documentation & resources

- [Tillio root README](../README.md) — platform overview
- [Backend API](../backend/README.md) — the service this CLI talks to
- Hosted product: [tillio.ai](https://tillio.ai) · downloads: `downloads.tillio.ai`

---

## License

This project is licensed under the MIT License.
