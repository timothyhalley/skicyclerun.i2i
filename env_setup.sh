#!/usr/bin/env bash
# ============================================================================
# SkiCycleRun Environment Setup
# ============================================================================
# Environment bootstrapper for SkiCycleRun development sessions.
# Sets up required environment variables for image processing pipeline.
#
# USAGE:
#   source ./env_setup.sh <images_root> [huggingface_cache]
#
# ARGUMENTS:
#   images_root        - Path to root directory for pipeline data
#                        (albums, preprocessed, lora_processed, etc.)
#   huggingface_cache  - Optional: Path to HuggingFace model cache
#                        (defaults to <parent_of_images_root>/models)
#
# EXAMPLE:
#   source ./env_setup.sh /Volumes/MySSD/skicyclerun.i2i /Volumes/MySSD/huggingface
#
# EXPORTS:
#   SKICYCLERUN_LIB_ROOT    - Pipeline data root directory
#   HUGGINGFACE_CACHE_LIB   - HuggingFace model cache location
#   HF_HOME                 - HuggingFace home directory
#   HUGGINGFACE_CACHE       - HuggingFace cache directory
#   HF_DATASETS_CACHE       - HuggingFace datasets cache
#
# ============================================================================

_env_setup_label="[env_setup]"
_env_setup_hint="source ./env_setup.sh <images_root> [huggingface_cache]"



_env_setup_is_sourced=0
if [ -n "${BASH_VERSION:-}" ]; then
  if [[ "${BASH_SOURCE[0]}" != "${0}" ]]; then
    _env_setup_is_sourced=1
  fi
elif [ -n "${ZSH_VERSION:-}" ]; then
  case ${ZSH_EVAL_CONTEXT:-} in
    *:file) _env_setup_is_sourced=1 ;;
  esac
fi

if [ "${_env_setup_is_sourced}" -ne 1 ]; then
  echo "${_env_setup_label} Please source this script."
  echo "${_env_setup_label} Hint: ${_env_setup_hint}"
  exit 1
fi

if [ $# -lt 1 ] || [ $# -gt 2 ]; then
  echo "${_env_setup_label} Usage: ${_env_setup_hint}"
  echo "${_env_setup_label} Hint: ${_env_setup_hint}"
  return 1
fi

images_root=$1
hf_cache_root=${2:-}

if [ -z "${hf_cache_root}" ]; then
  parent_dir=$(dirname -- "${images_root}")
  hf_cache_root="${parent_dir}/models"
fi

if [ -e "${images_root}" ] && [ ! -d "${images_root}" ]; then
  echo "${_env_setup_label} Path exists but is not a directory: ${images_root}"
  echo "${_env_setup_label} Hint: ${_env_setup_hint}"
  return 1
fi

if [ ! -d "${hf_cache_root}" ] && [ -e "${hf_cache_root}" ]; then
  echo "${_env_setup_label} Path exists but is not a directory: ${hf_cache_root}"
  echo "${_env_setup_label} Hint: ${_env_setup_hint}"
  return 1
fi

if [ ! -d "${images_root}" ]; then
  echo "${_env_setup_label} Creating directory: ${images_root}"
  if ! mkdir -p "${images_root}"; then
    echo "${_env_setup_label} Failed to create directory: ${images_root}"
    echo "${_env_setup_label} Hint: ${_env_setup_hint}"
    return 1
  fi
else
  echo "${_env_setup_label} Using existing directory: ${images_root}"
fi

if [ ! -d "${hf_cache_root}" ]; then
  echo "${_env_setup_label} Creating directory: ${hf_cache_root}"
  if ! mkdir -p "${hf_cache_root}"; then
    echo "${_env_setup_label} Failed to create directory: ${hf_cache_root}"
    echo "${_env_setup_label} Hint: ${_env_setup_hint}"
    return 1
  fi
else
  echo "${_env_setup_label} Using existing directory: ${hf_cache_root}"
fi

if ! resolved_images=$(cd "${images_root}" 2>/dev/null && pwd); then
  echo "${_env_setup_label} Unable to resolve absolute path for: ${images_root}"
  echo "${_env_setup_label} Hint: ${_env_setup_hint}"
  return 1
fi

if ! resolved_cache=$(cd "${hf_cache_root}" 2>/dev/null && pwd); then
  echo "${_env_setup_label} Unable to resolve absolute path for: ${hf_cache_root}"
  echo "${_env_setup_label} Hint: ${_env_setup_hint}"
  return 1
fi

datasets_cache_dir="${resolved_cache}/datasets"
mkdir -p "${datasets_cache_dir}"

# Clear deprecated Transformers cache variable to avoid library warnings
unset TRANSFORMERS_CACHE

export SKICYCLERUN_LIB_ROOT="${resolved_images}"
export HUGGINGFACE_CACHE_LIB="${resolved_cache}"
export SKICYCLERUN_MODEL_LIB="${resolved_cache}"
export HUGGINGFACE_CACHE="${resolved_cache}"
export HF_HOME="${resolved_cache}"
export HF_DATASETS_CACHE="${datasets_cache_dir}"
echo "${_env_setup_label} SKICYCLERUN_LIB_ROOT set to: ${SKICYCLERUN_LIB_ROOT}"
echo "${_env_setup_label} HUGGINGFACE_CACHE_LIB set to: ${HUGGINGFACE_CACHE_LIB}"
echo "${_env_setup_label} (Compat) SKICYCLERUN_MODEL_LIB mirrored to: ${SKICYCLERUN_MODEL_LIB}"
echo "${_env_setup_label} Hugging Face envs exported: HF_HOME, HUGGINGFACE_CACHE, HF_DATASETS_CACHE"
echo "${_env_setup_label} Verify with: printenv SKICYCLERUN_LIB_ROOT && printenv HF_HOME"
echo "${_env_setup_label} Next steps: python pipeline.py --config config/pipeline_config.json --check-config"
return 0
