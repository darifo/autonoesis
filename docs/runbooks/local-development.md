# Local development

## Bootstrap

```bash
conda env create --file environment.yml
conda activate autonoesis
UV_PROJECT_ENVIRONMENT="$CONDA_PREFIX" uv sync --inexact --all-packages --dev
```

For an existing environment, update it with `conda env update --file environment.yml --prune`
before synchronizing the workspace. Setting `UV_PROJECT_ENVIRONMENT` to `CONDA_PREFIX` installs
the locked workspace into the active Conda environment instead of creating a repository-local
`.venv`; `--inexact` preserves packages managed by Conda.

If Task is installed:

```bash
conda activate autonoesis
task bootstrap
```

## Verify

```bash
task check
```

Individual checks:

```bash
task lint
task typecheck
task test
```

## Run API

```bash
task api
```

Then open `http://127.0.0.1:8000/health/live`.

## Worker bootstrap check

```bash
task worker
```

The initial worker command validates configuration only. Temporal connection and workflow registration are added with the first durable-execution vertical slice.

## Local configuration

Copy `.env.example` to `.env`. Do not commit `.env`, credentials, production payloads, or raw traces.
