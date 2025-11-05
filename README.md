# 📘 Kontext Transform: Modular Image-to-Image with LoRA Adapters

Kontext Transform is a modular Python tool for transforming images into humorous, meaningful, or stylistically rich outputs using LoRA-enhanced pipelines. Built for creative technologists, it supports batch processing, adapter switching, dry-run previews, and quality control hooks. Primary motivator is this toolset located here:

<https://huggingface.co/Kontext-Style/models>

---

## 🧱 Project Structure

```text
kontext_transform/
├── config/
│ └── default_config.json # Main config file for single or batch runs
├── core/
│ ├── pipeline_loader.py # Loads and configures the FluxKontext pipeline
│ ├── lora_manager.py # Applies LoRA adapters
│ ├── lora_registry.py # Discovers available LoRA folders
│ ├── image_processor.py # Loads, resizes, and preprocesses images
│ ├── inference_runner.py # Runs the image-to-image transformation
│ └── quality_hooks.py # Optional tone correction and face masking
├── utils/
│ ├── cli.py # CLI helpers and config loader
│ ├── validator.py # Config validation
│ └── spinner.py # Visual feedback during inference
├── main.py # Entry point with CLI and batch support
└── README.md # You're reading it!
```

---

## 🚀 Installation

```bash
git clone https://github.com/yourname/kontext-transform.git
cd kontext-transform
pip install -r requirements.txt
```

Requires Python 3.10+, PyTorch, diffusers, PIL, numpy. Optional: mediapipe for face detection.

⚙️ Configuration

Edit config/default_config.json:

```json
{
  "input_folder": "./input",
  "output_folder": "./output",
  "input_image": "AndreaMaeAxe.png",
  "output_format": "webp",
  "style_name": "Ghibli",
  "prompt": "Make this image humorous and meaningful in the Ghibli style.",
  "negative_prompt": "extra limbs, distorted anatomy, blurry, duplicate arms, broken fingers",
  "max_dim": 1024,
  "num_inference_steps": 24,
  "guidance_scale": 7.5,
  "device": "mps",
  "precision": "float32",
  "lora": {
    "path": "Kontext-Style/Ghibli_lora",
    "weights": "Ghibli_lora_weights.safetensors",
    "adapter_name": "Ghibli"
  },
  "preprocess": {
    "enabled": true,
    "cleanup": true,
    "face_detection": true,
    "tone_correction": true,
    "face_masking": false
  }
}
```

## 🧪 CLI Usageage

```bash
python main.py --config config/default_config.json
```

## 🔧 Flags

```text
--config <path>         Path to config JSON file (default: config/default_config.json)
--dry-run               Skip inference, log planned actions only
--debug                 Enable verbose debug logging (reserved for future use)
--lora <name>           Override LoRA adapter by name (e.g., Ghibli, PixelDream)
--list-loras            List available LoRA adapters and exit
--batch                 Process all images in the input folder instead of a single file
```

## 📦 LoRA Management

LoRA adapters are stored in Kontext-Style/:

```text
Kontext-Style/
├── Ghibli/
│   └── Ghibli_weights.safetensors
├── PixelDream/
│   └── PixelDream_weights.safetensors
```

To list available adapters:

```bash
python main.py --list-loras
```

To override adapter:

```bash
python main.py --lora PixelDream
```

## 🔍 LoRA Registry Validation

The `validate_loras.py` tool checks all LoRA entries in your registry to ensure they're still valid and accessible on HuggingFace Hub. This helps catch issues like:

- Removed or renamed repositories
- Changed weight file names (version updates)
- Loading errors before they affect your workflow

**Quick Validation** (checks repos and files only):

```bash
python validate_loras.py
```

**Full Validation** (includes dry-run loading test):

```bash
python validate_loras.py --dry-run
```

**Validate Specific LoRAs**:

```bash
python validate_loras.py --loras Ghibli Jojo PencilDrawing
```

**Options**:

- `--registry <path>` - Path to registry file (default: config/lora_registry.json)
- `--dry-run` - Test loading each LoRA (slower, requires loading base pipeline)
- `--loras <names>` - Validate specific LoRAs only (space-separated)
- `--log-dir <path>` - Log directory (default: logs)

Results are saved to timestamped log files in `logs/lora_validation_YYYYMMDD_HHMMSS.log`

**Example Output**:

```text
================================================================================
Validating: Ghibli
  Path: Kontext-Style/Ghibli_lora
  Weights: Ghibli_lora_weights.safetensors

  🔍 Checking repository...
  ✅ Repository accessible

  🔍 Checking weight file...
  ✅ Weight file found

  ================================================================================
  Status: PASS
  ================================================================================
```

---

## 🧼 Quality Hooks

Enable in config under "preprocess":

- **cleanup**: Median filter + contrast boost
- **face_detection**: Warn if no face detected
- **tone_correction**: Slight color enhancement
- **face_masking**: Placeholder for future masking logic

## 🧠 Extending

- Add new LoRA folders to Kontext-Style/
- Add new hooks in quality_hooks.py
- Add CLI flags in main.py → parse_args()
- Add batch preview or dry-run inspection modes

## 🧑‍💻 Author

Built by Tim H, a creative technologist focused on modular generative workflows, reproducibility, and meaningful image transformation.
