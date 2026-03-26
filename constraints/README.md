# Environment Profiles (Safe and Reproducible)

These files let you reproduce each machine's environment without forcing both machines to the same package stack.

## Profiles

- `constraints/macmini-fast-20260326.txt`
  - Matches the known fast Mac mini stack from `logs/fingerprint_20260326T181721Z.txt`.
- `constraints/mbp-repro-20260326.txt`
  - Matches the MBP stack from `Desktop/MBP_20260326T154507Z.txt`.

## Why this is safe

Using these profiles is **opt-in**. Nothing changes unless you run `pip install` with one of these files.

Your fast Mac mini will stay fast as long as you keep using its own profile.

## Recommended usage

Create one virtual environment per machine profile:

```bash
python3 -m venv .venv-mini-fast
source .venv-mini-fast/bin/activate
pip install --upgrade pip
pip install -r constraints/macmini-fast-20260326.txt
```

```bash
python3 -m venv .venv-mbp-repro
source .venv-mbp-repro/bin/activate
pip install --upgrade pip
pip install -r constraints/mbp-repro-20260326.txt
```

## Keep requirements aligned

`requirements.txt` is the project baseline and now has `peft` pinned.

Use profile files when you need exact machine reproducibility.
