# Changelog

All notable changes to the Tillio CLI will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

> **Pre-1.0 policy:** Minor versions (0.x) may include breaking changes.
> Entries earlier than 0.2.0 predate this changelog.

## [0.2.3] - 2026-10-14

### Fixed
- The update check no longer queries PyPI. `tillio-cli` is not published there and the PyPI name may belong to an unrelated project, so the old check could report a stranger's version and suggest installing it. It now reads the latest GitHub release of huntingtonapplied/tillio-cli and suggests `pip install --upgrade git+https://github.com/huntingtonapplied/tillio-cli`, only when that release is newer.

## [0.2.2] - 2026-10-13

### Changed
- README: version badge and default API URL now match the shipped release; removed links to files that are not part of this repository.

## [0.2.0] - 2026-07-18

### Added
- Public release — a thin client for the hosted Tillio API.
- Commands: `login`, `status`, `submit`, `eval`, `projects`, `contributions`,
  `add`, `score_repo`, `fingerprint`, `index`, `doctor`, `completion`.
- `install.sh` for binary download + install.
