# Bundled Python runtime

ChordPresenter ships its own Python here so users don't have to install one.

The runtimes themselves are **not committed**. Create them before building:

```bash
scripts/build/bundle_python.sh
```

That downloads Python from [python-build-standalone](https://github.com/astral-sh/python-build-standalone),
verifies its checksum, and trims it into `aarch64/` (Apple Silicon) and `x86_64/` (Intel).

At runtime the app uses `python-runtime/<chip>/bin/python3.13`, and falls back to the
system `python3` when the folder is missing (e.g. `pnpm tauri dev` before running the script).

This file stays tracked so the Tauri resource glob always matches something.
