# SkiCycleRun Pipeline UI

Native macOS graphical interface for the SkiCycleRun photo processing pipeline.

## Features

- ✅ **Stage Selection**: Check/uncheck pipeline stages to run
- ✅ **Command Flags**: Toggle all available command-line flags
- ✅ **Live Preview**: See the exact command that will be executed
- ✅ **Real-time Output**: View pipeline output as it runs
- ✅ **Native macOS**: Built with PyObjC for true native experience
- ✅ **Non-invasive**: Uses existing `pipeline.py` - no code changes needed

## Installation

### 1. Install PyObjC Dependencies

```bash
pip3 install -r requirements-ui.txt
```

### 2. Verify Installation

```bash
python3 -c "import Cocoa; print('✅ PyObjC installed successfully')"
```

## Usage

### Launch UI

```bash
python3 main.py
```

### Launch with Custom Config

```bash
python3 main.py --config path/to/config.json
```

## UI Layout

```
┌─────────────────────────────────────────────────────────┐
│ 🏔️ SkiCycleRun Photo Processing Pipeline              │
├─────────────────────────────────────────────────────────┤
│                                                          │
│ Pipeline Stages:                                         │
│  ☑ export            — Export from Apple Photos         │
│  ☑ cleanup           — Archive old outputs              │
│  ☑ metadata_extraction — Extract EXIF, GPS, POIs        │
│  ☑ llm_image_analysis — 6-stage Ollama analysis         │
│  ☐ preprocessing     — Scale and optimize               │
│  ☐ lora_processing   — Apply LoRA styles                │
│  ☐ post_lora_watermarking — Apply watermarks            │
│  ☐ s3_deployment     — Deploy to S3                     │
│                                                          │
│ Command Flags:                                           │
│  ☐ --cache-only-geocode     — Use cache only            │
│  ☐ --force-llm-reanalysis   — Force re-analysis         │
│  ☐ --force-watermark        — Force re-watermark        │
│  ☑ --verbose                — Verbose output            │
│  ☑ --debug-prompt           — Log LLM prompts           │
│  ☐ --yes                    — Skip confirmations        │
│                                                          │
│ Command Preview:                                         │
│  python3 pipeline.py --stages export cleanup metadata_  │
│  extraction llm_image_analysis --verbose --debug-prompt │
│                                                          │
│  [ ▶️ Run Pipeline ]  [ ⏹️ Stop ]                       │
│                                                          │
│ Output Console:                                          │
│  ┌────────────────────────────────────────────────────┐ │
│  │ 🚀 Starting pipeline...                            │ │
│  │ 💻 Command: python3 pipeline.py --stages ...       │ │
│  │ ════════════════════════════════════════════════   │ │
│  │                                                    │ │
│  │ [Pipeline output streams here in real-time]       │ │
│  │                                                    │ │
│  └────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────┘
```

## Architecture

### Modular Structure

```
ui/
├── __init__.py              # Package initialization
├── app.py                   # Main application coordinator
├── models/
│   ├── __init__.py
│   └── pipeline_config.py   # Config parsing & command building
├── controllers/
│   ├── __init__.py
│   └── pipeline_controller.py  # Subprocess execution
└── views/
    ├── __init__.py
    └── main_window.py       # UI layout & controls
```

### Component Responsibilities

**Models** (`ui/models/`)

- Parse `pipeline_config.json`
- Define available stages and flags
- Build command-line arguments

**Controllers** (`ui/controllers/`)

- Execute `pipeline.py` as subprocess
- Stream output in real-time
- Handle process lifecycle (start/stop)

**Views** (`ui/views/`)

- Native macOS window using PyObjC
- Stage checkboxes
- Flag toggles
- Command preview field
- Output console
- Run/Stop buttons

**App** (`ui/app.py`)

- Coordinate between Model, View, Controller
- Wire callbacks
- Initialize PyObjC application

## How It Works

### 1. Configuration Loading

```python
config = PipelineConfig("config/pipeline_config.json")
# Parses JSON, extracts enabled stages and available flags
```

### 2. UI Rendering

```python
window = MainWindow(config)
# Creates native macOS window with checkboxes for stages/flags
# Uses PyObjC Cocoa bindings
```

### 3. Command Building

```python
stages = ["export", "metadata_extraction"]
flags = {"verbose": True, "debug_prompt": True}
cmd = config.build_command(stages, flags)
# Result: ["python3", "pipeline.py", "--stages", "export",
#          "metadata_extraction", "--verbose", "--debug-prompt"]
```

### 4. Subprocess Execution

```python
controller = PipelineController()
controller.set_output_callback(lambda line: window.append_output(line))
controller.run_pipeline(cmd)
# Streams output line-by-line to UI console
```

## Integration with pipeline.py

The UI **does not modify** your existing `pipeline.py`. It simply:

1. Reads `config/pipeline_config.json` to know available stages/flags
2. Builds command-line arguments based on UI selections
3. Executes `pipeline.py` as a subprocess with those arguments
4. Streams stdout/stderr to the UI console

Your pipeline logic remains untouched - the UI is a pure wrapper.

## Customization

### Adding New Stages

Edit `ui/models/pipeline_config.py`:

```python
AVAILABLE_STAGES = [
    "export",
    "cleanup",
    # ... add your new stage here
    "my_custom_stage"
]

STAGE_DESCRIPTIONS = {
    # ... add description
    "my_custom_stage": "My custom processing step"
}
```

### Adding New Flags

Edit `ui/models/pipeline_config.py`:

```python
AVAILABLE_FLAGS = {
    # ... add your new flag
    "my_custom_flag": {
        "type": "bool",
        "description": "Enable my custom feature",
        "default": False
    }
}
```

The UI will automatically render new stages/flags in the window.

## Troubleshooting

### PyObjC Import Error

```bash
# Install PyObjC
pip3 install pyobjc-core pyobjc-framework-Cocoa

# Verify
python3 -c "from Cocoa import NSApplication; print('OK')"
```

### Window Not Showing

- Ensure you're running on macOS (PyObjC is macOS-only)
- Check that Terminal has accessibility permissions
- Try running with `sudo` if permission issues

### Pipeline Not Running

- Verify `pipeline.py` is in the current directory
- Check that `config/pipeline_config.json` exists
- Review output console for error messages

## Development

### Running from Source

```bash
cd /path/to/skicyclerun.i2i
python3 main.py
```

### Testing Without UI

You can still run `pipeline.py` directly from terminal:

```bash
python3 pipeline.py --stages metadata_extraction llm_image_analysis
```

The UI and CLI can be used interchangeably.

## Future Enhancements

Potential improvements:

- [ ] Save/load preset configurations
- [ ] Progress bar for each stage
- [ ] Pause/resume capability
- [ ] Export logs to file
- [ ] Dark mode support
- [ ] Stage-specific settings panels
- [ ] Batch processing queue
- [ ] Integration with Apple Photos picker

## License

Same as parent project.
