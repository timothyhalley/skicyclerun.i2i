#!/bin/bash
# One-time installation script for skicyclerun.i2i project
# Run this ONCE to install Python, dependencies, and verify PyTorch
# For daily work, use: source ./env_setup.sh <images_root>

set -e

echo "🚀 Installing skicyclerun.i2i dependencies..."

# 1. Ensure Python 3.13.12 is installed via pyenv
echo "📋 Checking Python version..."
if ! pyenv versions | grep -q "3.13.12"; then
    echo "Installing Python 3.13.12..."
    pyenv install 3.13.12
fi

# 2. Set Python version for this project
echo "🐍 Setting Python 3.13.12 for this project..."
pyenv local 3.13.12

# 3. Verify Python version
echo "Verifying Python version:"
python --version

# 4. Upgrade pip
echo "📦 Upgrading pip..."
python -m pip install --upgrade pip

# 5. Install packages from requirements.txt
echo "📚 Installing Python packages..."
pip install -r requirements.txt

# 6. Set MPS memory environment variable
echo "🧠 Setting MPS memory configuration..."
export PYTORCH_MPS_HIGH_WATERMARK_RATIO=0.0
#echo 'export PYTORCH_MPS_HIGH_WATERMARK_RATIO=0.0' >> ~/.zshrc

# 7. Verify installation
echo "✅ Verifying installation..."
python -c "import torch, diffusers, transformers, peft; print(f'PyTorch: {torch.__version__}'); print(f'MPS available: {torch.backends.mps.is_available()}')"

echo "🎉 Installation complete!"
echo ""
echo "📝 IMPORTANT: For every terminal session, run:"
echo "   source ./env_setup.sh /Volumes/MySSD/skicyclerun.i2i /Volumes/MySSD/huggingface"
echo "   (adjust paths as needed)"
echo ""
echo "   Setup key to hugging face"
echo "   hf auth login"
echo "      Then select 'Login with a token' and paste your Hugging Face token."
echo ""
echo "   This will set up your environment variables and ensure you have access to the Hugging Face models."
echo "   Check Hugging Face access with: hf auth whoami"
echo ""
echo "Then you can run the pipeline:"
echo "   run_Pipeline.sh --stages geocode_sweep --yes"