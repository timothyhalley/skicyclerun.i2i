#!/usr/bin/env python3
"""
LoRA Registry Validator
Validates all LoRA entries in lora_registry.json against HuggingFace Hub
"""

import json
import os
import sys
from datetime import datetime
from huggingface_hub import list_repo_files, HfApi
from huggingface_hub.utils import RepositoryNotFoundError, GatedRepoError

from utils.config_utils import resolve_config_placeholders
import torch
from diffusers import FluxKontextPipeline

# Color codes for terminal output
GREEN = '\033[92m'
RED = '\033[91m'
YELLOW = '\033[93m'
BLUE = '\033[94m'
RESET = '\033[0m'

class LoRAValidator:
    def __init__(self, registry_path="config/lora_registry.json", log_dir="logs"):
        self.registry_path = registry_path
        self.log_dir = log_dir
        self.results = []
        self.log_file = None
        
    def setup_logging(self):
        """Create timestamped log file"""
        os.makedirs(self.log_dir, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.log_file = os.path.join(self.log_dir, f"lora_validation_{timestamp}.log")
        with open(self.log_file, 'w') as f:
            f.write(f"LoRA Registry Validation - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write("=" * 80 + "\n\n")
        
    def log(self, message, console=True, file=True):
        """Log to console and/or file"""
        if console:
            print(message)
        if file and self.log_file:
            # Strip ANSI color codes for log file
            clean_msg = message
            for code in [GREEN, RED, YELLOW, BLUE, RESET]:
                clean_msg = clean_msg.replace(code, '')
            with open(self.log_file, 'a') as f:
                f.write(clean_msg + "\n")
    
    def load_registry(self):
        """Load LoRA registry from JSON file"""
        try:
            with open(self.registry_path, 'r') as f:
                raw = json.load(f)
                wrapped = {"registry": raw}
                resolved = resolve_config_placeholders(wrapped)
                registry = resolved.get("registry", raw)
                return registry
        except FileNotFoundError:
            self.log(f"{RED}❌ Registry file not found: {self.registry_path}{RESET}")
            sys.exit(1)
        except json.JSONDecodeError as e:
            self.log(f"{RED}❌ Invalid JSON in registry: {e}{RESET}")
            sys.exit(1)
    
    def validate_repo_exists(self, repo_id):
        """Check if HuggingFace repository exists"""
        try:
            api = HfApi()
            api.repo_info(repo_id=repo_id, repo_type="model")
            return True, "Repository accessible"
        except RepositoryNotFoundError:
            return False, "Repository not found"
        except GatedRepoError:
            return True, "Repository gated (requires authentication)"
        except Exception as e:
            return False, f"Error: {str(e)}"
    
    def validate_weight_file(self, repo_id, filename):
        """Check if weight file exists in repository"""
        try:
            files = list_repo_files(repo_id)
            if filename in files:
                return True, "Weight file found"
            else:
                # Check if there's a similar file (version change)
                similar = [f for f in files if f.endswith('.safetensors') and 
                          any(word in f.lower() for word in filename.lower().split('_'))]
                if similar:
                    return False, f"File not found. Similar files: {', '.join(similar[:3])}"
                return False, "Weight file not found"
        except Exception as e:
            return False, f"Error listing files: {str(e)}"
    
    def dry_run_load(self, lora_entry, pipeline=None):
        """Test loading LoRA weights without full inference"""
        if pipeline is None:
            return None, "Skipped (no pipeline provided for dry-run)"
        
        try:
            raw_path = lora_entry.get("resolved_path") or lora_entry.get("path")
            resolved_path = os.path.expanduser(raw_path) if isinstance(raw_path, str) else raw_path
            resolved_path = os.path.abspath(resolved_path) if isinstance(resolved_path, str) else resolved_path

            if isinstance(resolved_path, str) and os.path.exists(resolved_path) and os.path.isfile(resolved_path):
                pipeline.load_lora_weights(
                    resolved_path,
                    adapter_name="validation_test"
                )
            else:
                pipeline.load_lora_weights(
                    lora_entry["path"],
                    weight_name=lora_entry["weights"],
                    adapter_name="validation_test"
                )
            # Unload to free memory
            pipeline.unload_lora_weights()
            return True, "Successfully loaded and unloaded"
        except Exception as e:
            return False, f"Load failed: {str(e)}"
    
    def validate_entry(self, name, entry, dry_run=False, pipeline=None):
        """Validate a single LoRA entry"""
        self.log(f"\n{BLUE}{'='*80}{RESET}")
        resolved_path = os.path.expanduser(entry['path']) if isinstance(entry['path'], str) else entry['path']
        resolved_path = os.path.abspath(resolved_path) if isinstance(resolved_path, str) else resolved_path

        self.log(f"\n{BLUE}{'='*80}{RESET}")
        self.log(f"{BLUE}Validating: {name}{RESET}")
        self.log(f"  Path: {entry['path']}")
        if resolved_path and entry['path'] != resolved_path:
            self.log(f"  Resolved path: {resolved_path}")
        self.log(f"  Weights: {entry['weights']}")
        result = {
            'name': name,
            'original_path': entry['path'],
            'path': resolved_path,
            'repo_status': None,
            'file_status': None,
            'load_status': None,
            'overall': 'PASS'
        }

        repo_ok = False
        weight_path_local = None
        is_local_path = isinstance(resolved_path, str) and os.path.exists(resolved_path)

        if is_local_path:
            if os.path.isfile(resolved_path):
                result['repo_status'] = "Local file path"
                self.log(f"\n  📍 Detected local LoRA file")
                self.log(f"  {GREEN}✅ Local file exists{RESET}")
                result['file_status'] = "Local file present"
                weight_path_local = resolved_path
            else:
                weight_path = os.path.join(resolved_path, entry['weights'])
                self.log(f"\n  📁 Detected local LoRA directory")
                if os.path.isfile(weight_path):
                    result['repo_status'] = "Local directory path"
                    result['file_status'] = "Weight file present"
                    self.log(f"  {GREEN}✅ Found weight file at {weight_path}{RESET}")
                    weight_path_local = weight_path
                else:
                    result['repo_status'] = "Local directory path"
                    result['file_status'] = "Missing weight file"
                    self.log(f"  {RED}❌ Weight file not found at {weight_path}{RESET}")
                    result['overall'] = 'FAIL'
        else:
            self.log(f"\n  🔍 Checking repository...")
            repo_ok, repo_msg = self.validate_repo_exists(entry['path'])
            result['repo_status'] = repo_msg
            if repo_ok:
                self.log(f"  {GREEN}✅ {repo_msg}{RESET}")
            else:
                self.log(f"  {RED}❌ {repo_msg}{RESET}")
                result['overall'] = 'FAIL'

            if repo_ok and "gated" not in repo_msg.lower():
                self.log(f"  🔍 Checking weight file...")
                file_ok, file_msg = self.validate_weight_file(entry['path'], entry['weights'])
                result['file_status'] = file_msg
                if file_ok:
                    self.log(f"  {GREEN}✅ {file_msg}{RESET}")
                else:
                    self.log(f"  {RED}❌ {file_msg}{RESET}")
                    result['overall'] = 'FAIL'
            else:
                result['file_status'] = "Skipped (repo not accessible)"
                self.log(f"  {YELLOW}⚠️  Weight file check skipped{RESET}")

        dry_run_allowed = False
        if dry_run and pipeline:
            if weight_path_local:
                dry_run_allowed = True
            elif not is_local_path and repo_ok and result['file_status'] != "Skipped (repo not accessible)" and result['overall'] != 'FAIL':
                dry_run_allowed = True

        if dry_run_allowed:
            self.log(f"  🔍 Testing LoRA load...")
            load_ok, load_msg = self.dry_run_load({**entry, "resolved_path": weight_path_local or resolved_path}, pipeline)
            result['load_status'] = load_msg
            if load_ok:
                self.log(f"  {GREEN}✅ {load_msg}{RESET}")
            elif load_ok is None:
                self.log(f"  {YELLOW}⚠️  {load_msg}{RESET}")
            else:
                self.log(f"  {RED}❌ {load_msg}{RESET}")
                result['overall'] = 'FAIL'
        else:
            result['load_status'] = "Skipped"

        status_color = GREEN if result['overall'] == 'PASS' else RED
        self.log(f"  {status_color}Status: {result['overall']}{RESET}")
        self.log(f"  {status_color}{'='*80}{RESET}")
        
        self.results.append(result)
        return result
    
    def print_summary(self):
        """Print validation summary"""
        total = len(self.results)
        passed = sum(1 for r in self.results if r['overall'] == 'PASS')
        failed = total - passed
        
        self.log(f"\n\n{BLUE}{'='*80}{RESET}")
        self.log(f"{BLUE}VALIDATION SUMMARY{RESET}")
        self.log(f"{BLUE}{'='*80}{RESET}")
        self.log(f"Total LoRAs: {total}")
        self.log(f"{GREEN}Passed: {passed}{RESET}")
        self.log(f"{RED}Failed: {failed}{RESET}")
        
        if failed > 0:
            self.log(f"\n{RED}Failed LoRAs:{RESET}")
            for r in self.results:
                if r['overall'] == 'FAIL':
                    self.log(f"  • {r['name']}")
                    if r['repo_status'] and 'not found' in r['repo_status'].lower():
                        self.log(f"    - Repository issue: {r['repo_status']}")
                    if r['file_status'] and 'not found' in r['file_status'].lower():
                        self.log(f"    - File issue: {r['file_status']}")
        
        self.log(f"\n📋 Full report saved to: {self.log_file}")
        self.log(f"{BLUE}{'='*80}{RESET}\n")
    
    def run(self, dry_run=False, specific_loras=None):
        """Run validation on all or specific LoRAs"""
        self.setup_logging()
        registry = self.load_registry()
        
        self.log(f"{BLUE}{'='*80}{RESET}")
        self.log(f"{BLUE}LoRA Registry Validator{RESET}")
        self.log(f"{BLUE}{'='*80}{RESET}")
        self.log(f"Registry: {self.registry_path}")
        self.log(f"Total entries: {len(registry)}")
        self.log(f"Dry-run mode: {'enabled' if dry_run else 'disabled'}")
        
        # Load pipeline if dry-run is requested
        pipeline = None
        if dry_run:
            self.log(f"\n{YELLOW}⚠️  Dry-run mode: This will load the base pipeline (may take time){RESET}")
            try:
                self.log("Loading FLUX.1-Kontext-dev pipeline...")
                pipeline = FluxKontextPipeline.from_pretrained(
                    "black-forest-labs/FLUX.1-Kontext-dev",
                    dtype=torch.bfloat16
                )
                self.log(f"{GREEN}✅ Pipeline loaded{RESET}")
            except Exception as e:
                self.log(f"{RED}❌ Failed to load pipeline: {e}{RESET}")
                self.log(f"{YELLOW}⚠️  Continuing without dry-run loading tests{RESET}")
                dry_run = False
        
        # Validate each LoRA
        loras_to_check = specific_loras if specific_loras else registry.keys()
        for name in loras_to_check:
            if name not in registry:
                self.log(f"{RED}❌ LoRA '{name}' not found in registry{RESET}")
                continue
            self.validate_entry(name, registry[name], dry_run=dry_run, pipeline=pipeline)
        
        # Print summary
        self.print_summary()
        
        # Return exit code
        return 0 if all(r['overall'] == 'PASS' for r in self.results) else 1


def main():
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Validate LoRA registry entries against HuggingFace Hub",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Quick validation (check repos and files only)
  python validate_loras.py
  
  # Full validation with dry-run loading (slower)
  python validate_loras.py --dry-run
  
  # Validate specific LoRAs only
  python validate_loras.py --loras Ghibli Jojo Pixel
  
  # Full validation of specific LoRAs
  python validate_loras.py --dry-run --loras PencilDrawing
        """
    )
    
    parser.add_argument(
        '--registry',
        default='config/lora_registry.json',
        help='Path to LoRA registry JSON file (default: config/lora_registry.json)'
    )
    
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Test loading each LoRA (requires loading base pipeline, slower)'
    )
    
    parser.add_argument(
        '--loras',
        nargs='+',
        help='Validate specific LoRAs only (space-separated names)'
    )
    
    parser.add_argument(
        '--log-dir',
        default='logs',
        help='Directory for validation logs (default: logs)'
    )
    
    args = parser.parse_args()
    
    validator = LoRAValidator(
        registry_path=args.registry,
        log_dir=args.log_dir
    )
    
    exit_code = validator.run(
        dry_run=args.dry_run,
        specific_loras=args.loras
    )
    
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
