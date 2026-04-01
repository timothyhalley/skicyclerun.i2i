# Environment Profiles

Performance profiles capture exact package versions and machine-specific
tuning parameters for each machine. Use `run_SetupEnv.sh` (wrapper over
`scripts/env_setup.py`) to apply a profile
in one step — no shell preamble or manual env var management required.

## Applying a profile

```bash
# Mac mini (fast baseline)
./run_SetupEnv.sh --profile performance/macmini-fast-20260326.txt

# MacBook Pro (current / under investigation)
./run_SetupEnv.sh --profile performance/mbp-repro-20260326.txt

# Override drive paths if mounted differently:
./run_SetupEnv.sh --profile performance/macmini-fast-20260326.txt \
    --lib-root  /Volumes/MySSD/skicyclerun.i2i \
    --hf-cache  /Volumes/MySSD/huggingface
```

`scripts/env_setup.py` performs all of these steps automatically:

1. Sets pyenv global Python version
2. Regenerates `requirements.txt` from the profile package list
3. Runs `pip install -r requirements.txt`
4. Writes `.env` with runtime paths and MPS/PyTorch flags
5. Updates `config/pipeline_config.json` defaults
6. Validates MPS (Apple GPU) availability with a loud warning if CPU fallback

After running once, every new shell can go straight to:

```bash
./run_Pipeline.sh --stages lora_processing
```

## Profile file format

Profiles are plain pip requirement files with structured `# key: value`
comment lines at the top for machine metadata:

```
# python_version: 3.13.12
# lib_root: /Volumes/MySSD/skicyclerun.i2i
# huggingface_cache: /Volumes/MySSD/huggingface
# device: mps
# precision: bfloat16
# pytorch_enable_mps_fallback: 1
# pytorch_mps_high_watermark_ratio: 0.0
# pytorch_mps_low_watermark_ratio: 0.7
# tokenizers_parallelism: false
# omp_num_threads: 1

torch==2.7.0
diffusers @ git+https://...
...
```

## Profiles

### `macmini-fast-20260326.txt` ⚡ FAST BASELINE

Captures the known-fast Mac mini stack. Key differences vs MBP:

- `torch==2.7.0` — measurably better MPS throughput than 2.8.0 on Apple Silicon
- `diffusers @ git+...` — bleeding-edge commit with Apple Silicon MPS fixes
- No `torchaudio` (not needed for image pipeline)

### `mbp-repro-20260326.txt` ⚠️ UNDER INVESTIGATION

Captures the current MBP state. Suspect causes of slower performance:

- `torch==2.8.0` (MPS regression vs 2.7.0 for FLUX i2i on some Apple Silicon chips)
- Released `diffusers==0.35.2` (may lack MPS optimisations in head)

To test the Mac mini stack on the MBP:

```bash
./run_SetupEnv.sh --profile performance/macmini-fast-20260326.txt
```

## Generating a new profile

Use `scripts/check_env_sync.sh --fingerprint` to capture the current state:

```bash
./scripts/check_env_sync.sh --fingerprint --out performance/$(hostname)-$(date +%Y%m%d).txt
```

Then add the `# key: value` metadata header (see format above).
