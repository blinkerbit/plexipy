# Linting Guide

This project uses linting tools to ensure code quality for both Python code and Dockerfiles.

## Python Linting (Ruff)

### Installation

```bash
pip install ruff
```

### Usage

**Check for issues:**
```bash
ruff check pyrest/ apps/ main.py
```

**Auto-fix issues:**
```bash
ruff check --fix pyrest/ apps/ main.py
```

**Format code:**
```bash
ruff format pyrest/ apps/ main.py
```

**Check specific file:**
```bash
ruff check apps/pov/handlers.py
```

## Dockerfile Linting (Hadolint)

### Installation Options

**Option 1: Using Docker (Recommended)**
```bash
# No installation needed, uses Docker image
docker pull hadolint/hadolint:latest
```

**Option 2: Using Homebrew (macOS)**
```bash
brew install hadolint
```

**Option 3: Using Scoop (Windows)**
```powershell
scoop install hadolint
```

**Option 4: Direct Download**
- Download from: https://github.com/hadolint/hadolint/releases

### Usage

**Using the provided script (Windows PowerShell):**
```powershell
.\scripts\lint-dockerfile.ps1
```

**Using the provided script (Linux/macOS):**
```bash
chmod +x scripts/lint-dockerfile.sh
./scripts/lint-dockerfile.sh
```

**Using Docker directly:**
```bash
docker run --rm -i hadolint/hadolint < Dockerfile
```

**With configuration file:**
```bash
docker run --rm -i \
  -v "$(pwd)/.hadolint.yaml:/root/.hadolint.yaml" \
  hadolint/hadolint < Dockerfile
```

### Show hadolint scan results (save to file)

To run hadolint on all Dockerfiles and save the report to `hadolint-report.txt`:

**Windows (PowerShell):**
```powershell
.\scripts\hadolint-report.ps1
# Optional: specify output file
.\scripts\hadolint-report.ps1 -OutFile my-report.txt
```

**Linux/macOS (run hadolint per file and redirect):**
```bash
hadolint Dockerfile 2>&1 | tee hadolint-report.txt
hadolint Dockerfile.isolated 2>&1 >> hadolint-report.txt
```

Requires Docker to be running (when using the Docker image) or hadolint installed locally (e.g. `scoop install hadolint` on Windows).

## Lint Everything

Run both Python and Dockerfile linting:

**Windows PowerShell:**
```powershell
.\scripts\lint-all.ps1
```

**Linux/macOS:**
```bash
chmod +x scripts/lint-all.sh
./scripts/lint-all.sh
```

## Configuration

- **Python linting**: Configured in `pyproject.toml`
- **Dockerfile linting**: Configured in `.hadolint.yaml`

## CI/CD Integration

The Dockerfile build process includes automatic Python linting. To skip linting during build:

```bash
docker build --build-arg SKIP_LINT=true -t pyrest .
```

## Common Issues and Fixes

### Python Linting

- **Line too long**: Increase `line-length` in `pyproject.toml` or break the line
- **Unused imports**: Run `ruff check --fix` to auto-remove
- **Unused variables**: Prefix with `_` (e.g., `_unused_var`)

### Dockerfile Linting

- **DL3008/DL3018**: Pin package versions (often ignored for Alpine packages)
- **DL3009/DL3019**: Clean package cache (already handled in our Dockerfile)
- **DL4006**: Use `set -e` in bash scripts (already handled)

## Pre-commit Hooks (Optional)

To run linting automatically before commits, install pre-commit:

```bash
pip install pre-commit
pre-commit install
```

Create `.pre-commit-config.yaml`:
```yaml
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.1.0
    hooks:
      - id: ruff
        args: [--fix]
      - id: ruff-format
```
