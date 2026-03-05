#!/usr/bin/env bash
# Use Python 3.12 instead of 3.13.2 to avoid blake2 issues

echo "🔄 Switching to Python 3.12 (stable alternative)..."
echo ""

# Check if Python 3.12 is installed
if ! pyenv versions | grep -q "3.12"; then
    echo "📦 Installing Python 3.12..."
    pyenv install 3.12
fi

# Set Python 3.12 for this project
echo "🐍 Setting Python 3.12 for this project..."
pyenv local 3.12

# Reinstall dependencies
echo "📦 Reinstalling dependencies..."
pip install -r requirements.txt

echo ""
echo "✅ Done! Now using Python 3.12"
echo "Current Python version:"
python --version
echo ""
echo "Test hashlib:"
python -c "import hashlib; print('blake2b:', hashlib.blake2b); print('✅ blake2 working!')"
