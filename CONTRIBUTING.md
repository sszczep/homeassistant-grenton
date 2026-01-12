# Contributing to Grenton Home Assistant Integration

Thank you for considering a contribution to this project! We welcome improvements to code, documentation, translations, tests, and user experience.

## How to Contribute

### 1. Fork the Repository

Click **Fork** on GitHub and clone your fork:

```bash
git clone https://github.com/sszczep/homeassistant-grenton.git
cd homeassistant-grenton
```

### 2. Create a Feature Branch

Use clear, descriptive names:

```bash
git checkout -b feature/my-improvement
```

Examples:
- fix/config-flow-validation
- feature/roller-shutter-v3-tilt
- docs/update-readme-widgets
- refactor/entity-config-schema

### 3. Make Your Changes

Keep each change focused and tested. Update docs and translations when behavior or UI changes.

#### General Guidelines
- Keep changes **atomic** and avoid mixing unrelated edits
- Write clear commit messages (see format below)
- Update README and translations (`translations/en.json`, `translations/pl.json`) when relevant
- Ensure all entities and options have proper translation keys
- Test thoroughly in a local HA instance

#### Python/Integration Guidelines
- Follow existing project structure under `custom_components/homeassistant_grenton`
- Prefer small, maintainable modules (entities, devices, mappers, DTOs)
- Validate config data and handle errors gracefully (options flows, selectors)
- Use Home Assistant device classes and units consistently
- Keep public APIs stable; avoid breaking changes without migration

#### Documentation Guidelines
- Use clear, concise language
- Keep formatting consistent with README sections
- Explain new widgets, entities, options, or behaviors

### 4. Development Setup

Recommended environment:
- Python 3.12+
- Home Assistant 2025.12.4+

Create a virtual environment and install dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 5. Testing & Quality

Run tests and checks before opening a PR:

```bash
# Unit tests
pytest

# Static type checking
mypy custom_components/homeassistant_grenton

# Linting
ruff check custom_components/homeassistant_grenton
```

### Commit Message Format

Use clear, structured commit messages:

```
<type>: <short description>

[optional longer description]
```

Types:
- fix: bug fix
- feat: new feature
- docs: documentation or translations
- refactor: code restructuring
- test: tests or CI-related updates
- chore: maintenance tasks

Examples:
- fix: handle None units in slider options flow
- feat: add roller shutter V3 lamel control
- docs: update README supported widgets table

### Pull Request Checklist

Before submitting:
- Code compiles and tests pass
- Linting and type checks pass
- README updated if user-facing behavior changed
- Translations updated where applicable
- Linked issue (if any) referenced in PR description

### Reporting Issues

When filing an issue, please include:
- Home Assistant version
- Integration version/commit
- Steps to reproduce
- Expected vs. actual behavior
- Logs or screenshots if helpful

Open an issue here:
- Issues: https://github.com/sszczep/homeassistant-grenton/issues
- Discussions: https://github.com/sszczep/homeassistant-grenton/discussions

### License

By contributing, you agree your contributions are licensed under **GPL-3.0** (same as this project).

### Code of Conduct

Be respectful and collaborative. Follow GitHub Community Guidelines. Discrimination, harassment, or toxicity is not tolerated.

### Sponsor

If this project helps you, please consider sponsoring ongoing development:
- GitHub Sponsors: https://github.com/sponsors/sszczep

Thank you for your support and contributions!
