# LoRA Transformer Refactoring Documentation

**Date**: December 6, 2025  
**Change**: Renamed `main.py` → `core/lora_transformer.py`  
**Rationale**: Improve code organization and clarify module purpose

## Overview

The LoRA image transformation CLI was previously located at the root level as `main.py`, which didn't clearly indicate its purpose or relationship to other core modules. This refactoring moves it into the `core/` directory with a descriptive name that reflects its function: transforming images using LoRA (Low-Rank Adaptation) style filters.

## What Changed

### File Movement
- **Old**: `main.py` (root level)
- **New**: `core/lora_transformer.py` (core module)

### Files Updated

#### 1. Core Pipeline Integration
- **File**: `pipeline.py` (line 771)
- **Change**: Updated subprocess call in `run_lora_processing_stage()`
  ```python
  # Before
  cmd = [sys.executable, 'main.py', '--lora', lora_name, '--batch', ...]
  
  # After
  cmd = [sys.executable, 'core/lora_transformer.py', '--lora', lora_name, '--batch', ...]
  ```

#### 2. CLI Help Text
- **File**: `core/lora_transformer.py`
- **Lines Updated**: 93-99, 217-218, 512
- **Change**: Updated all example commands in help text and error messages
  ```bash
  # Before
  python main.py --list-loras
  
  # After
  python core/lora_transformer.py --list-loras
  ```

#### 3. Debug Scripts
- **File**: `debug/batch_lora_test.sh` (line 124)
- **Change**: Updated LoRA processing command
  ```bash
  # Before
  CMD="python main.py --lora \"$LORA\""
  
  # After
  CMD="python core/lora_transformer.py --lora \"$LORA\""
  ```

#### 4. Utility Scripts
- **File**: `utils/night_batch_run.sh` (line 91)
- **Change**: Updated batch processing command
  ```bash
  # Before
  CMD="python main.py --lora \"$LORA\" --file \"$INPUT\" --batch"
  
  # After
  CMD="python core/lora_transformer.py --lora \"$LORA\" --file \"$INPUT\" --batch"
  ```

#### 5. Documentation Files (Manual Update Required)
The following documentation files contain references to `main.py` that should be updated:

- **README.md** (lines 110, 249, 255, 279)
- **WORKFLOW.md** (lines 161, 167, 173, 179, 185, 195)
- **FIXES.md** (line 131)

Example updates needed:
```markdown
<!-- Before -->
python main.py --check-config
python main.py --list-loras
python main.py --batch --lora Anime

<!-- After -->
python core/lora_transformer.py --check-config
python core/lora_transformer.py --list-loras
python core/lora_transformer.py --batch --lora Anime
```

## Usage Examples

### List Available LoRA Styles
```bash
python core/lora_transformer.py --list-loras
```

### Process Single Image
```bash
python core/lora_transformer.py --lora Anime --file photo.jpg
```

### Batch Process Album
```bash
python core/lora_transformer.py --lora Impressionism --batch \
  --input-folder ./data/preprocessed/VacationPhotos \
  --output-folder ./data/lora_processed
```

### Called by Pipeline
```bash
# Pipeline automatically calls lora_transformer.py during stage 6
python pipeline.py --stages lora_processing
```

## Validation Tests

### Phase 1: Smoke Tests (5 minutes)
```bash
# Test 1: List available LoRAs
python core/lora_transformer.py --list-loras

# Test 2: Config validation
python core/lora_transformer.py --check-config

# Test 3: Single image test (use small test image)
python core/lora_transformer.py --lora Anime --file [test-image.jpg]
```

### Phase 2: Integration Tests (10 minutes)
```bash
# Test 4: Small batch (3-5 images)
python core/lora_transformer.py --lora Anime --batch \
  --input-folder ./data/preprocessed/TestAlbum \
  --output-folder ./data/lora_processed

# Test 5: Pipeline integration
python pipeline.py --stages lora_processing
```

### Phase 3: Full Pipeline Test (time varies)
```bash
# Test 6: Complete pipeline with all LoRAs
python pipeline.py --stages lora_processing

# Verify output structure matches expected
ls -la ./data/lora_processed/[album-name]/[lora-style]/
```

## Architecture Benefits

### Before Refactoring
```
skicyclerun.i2i/
├── main.py                    # ❌ Unclear purpose, root clutter
├── pipeline.py                # Pipeline orchestrator
└── core/
    ├── image_processor.py
    ├── lora_manager.py
    └── pipeline_loader.py
```

### After Refactoring
```
skicyclerun.i2i/
├── pipeline.py                # Pipeline orchestrator
└── core/
    ├── image_processor.py
    ├── lora_manager.py
    ├── lora_transformer.py    # ✅ Clear purpose, organized location
    └── pipeline_loader.py
```

### Improvements
1. **Clarity**: Name explicitly describes function (LoRA transformation)
2. **Organization**: Groups related core functionality together
3. **Discoverability**: Easier to find among core modules
4. **Consistency**: All image processing logic in `core/` directory
5. **Maintainability**: Clear separation between pipeline orchestration and transformation logic

## Dependencies

### No Import Changes Required
The refactoring only affects:
- **Subprocess calls** (pipeline.py, shell scripts)
- **CLI invocation** (user commands, documentation)
- **Help text** (internal examples)

All Python imports (`from core.lora_manager import ...`) remain unchanged because `lora_transformer.py` was never imported as a module—it's only executed via subprocess or direct CLI invocation.

## Rollback Plan

If issues arise:

### Option 1: Git Revert
```bash
git revert HEAD
```

### Option 2: Manual Rollback
```bash
# Move file back
git mv core/lora_transformer.py main.py

# Revert pipeline.py
# Change line 771 back to 'main.py'

# Revert scripts
# Update debug/batch_lora_test.sh and utils/night_batch_run.sh
```

## Migration Notes

### For Users
- **Update bookmarks/aliases**: Change any saved commands from `main.py` to `core/lora_transformer.py`
- **Update custom scripts**: Replace `python main.py` with `python core/lora_transformer.py`
- **Shell aliases**: Update any shell aliases that reference `main.py`

### For Developers
- **No code changes needed**: Python imports remain unchanged
- **Subprocess calls**: Use `'core/lora_transformer.py'` instead of `'main.py'`
- **Documentation**: Update README, WORKFLOW, and other docs to reflect new path

## Success Criteria

✅ **Critical Tests Pass**:
- [ ] `--list-loras` displays available styles
- [ ] Single image processing works
- [ ] Batch processing creates correct output structure
- [ ] Pipeline stage 6 (lora_processing) executes successfully
- [ ] All configured LoRAs process without errors

✅ **Integration Verified**:
- [ ] utils/cli.py functions accessible (load_config, list_loras)
- [ ] core/ module imports work correctly
- [ ] Config file resolution correct
- [ ] Output files land in expected directories

✅ **Documentation Current**:
- [ ] Help text shows correct paths
- [ ] README examples accurate
- [ ] WORKFLOW instructions updated
- [ ] Debug scripts functional

## Related Files

### Core Modules
- `core/lora_transformer.py` - Main LoRA transformation CLI (moved from root)
- `core/lora_manager.py` - LoRA loading and application logic
- `core/pipeline_loader.py` - FLUX pipeline initialization
- `core/inference_runner.py` - Model inference execution

### Configuration
- `config/pipeline_config.json` - Pipeline configuration
- `config/lora_registry.json` - LoRA style registry

### Supporting Utilities
- `utils/cli.py` - CLI configuration loading (used by lora_transformer.py)
- `utils/spinner.py` - Progress indicators
- `utils/validator.py` - Configuration validation

## Timeline

- **2025-12-06 15:38**: File moved from `main.py` to `core/lora_transformer.py`
- **2025-12-06 15:38**: Updated pipeline.py subprocess call
- **2025-12-06 15:38**: Updated help text and examples in lora_transformer.py
- **2025-12-06 15:38**: Updated debug and utility scripts
- **Pending**: Manual documentation updates (README.md, WORKFLOW.md, FIXES.md)

## Questions & Answers

**Q: Why not use `python -m core.lora_transformer`?**  
A: Direct path invocation (`python core/lora_transformer.py`) is simpler and requires no `__main__.py` wrapper. Works identically to previous behavior.

**Q: Will this break existing workflows?**  
A: Users running `python main.py` commands will need to update to `python core/lora_transformer.py`. The pipeline automatically uses the new path.

**Q: Do I need to reinstall or reconfigure?**  
A: No. All dependencies and configurations remain unchanged. Just update command paths in custom scripts.

**Q: What if I have `main.py` in my PATH or aliases?**  
A: Update shell aliases or PATH entries to reference `core/lora_transformer.py` instead.

## Contact

For issues or questions about this refactoring:
- Review test results in validation phase
- Check git history: `git log --follow core/lora_transformer.py`
- Compare before/after: `git diff HEAD~1 pipeline.py`
