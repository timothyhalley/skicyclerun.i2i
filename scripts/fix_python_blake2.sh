#!/usr/bin/env bash
# Fix Python blake2 issue by reinstalling with proper OpenSSL support

# Detect current Python version
CURRENT_VERSION=$(python --version 2>&1 | awk '{print $2}')
echo "🔧 Fixing Python ${CURRENT_VERSION} blake2 support..."
echo ""
echo "This will:"
echo "  1. Check if Homebrew OpenSSL is installed"
echo "  2. Uninstall Python ${CURRENT_VERSION}"
echo "  3. Reinstall it with proper OpenSSL configuration"
echo ""

read -p "Continue? (y/n) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Cancelled."
    exit 1
fi

# Check if OpenSSL is installed via Homebrew
if ! brew list openssl@3 &>/dev/null; then
    echo "📦 Installing OpenSSL 3 via Homebrew..."
    brew install openssl@3
fi

# Uninstall current Python version
echo "📦 Uninstalling Python ${CURRENT_VERSION}..."
pyenv uninstall -f ${CURRENT_VERSION}

# Set OpenSSL flags for proper blake2 support
echo "🔐 Configuring OpenSSL paths..."
export LDFLAGS="-L$(brew --prefix openssl@3)/lib"
export CPPFLAGS="-I$(brew --prefix openssl@3)/include"
export PKG_CONFIG_PATH="$(brew --prefix openssl@3)/lib/pkgconfig"
export PYTHON_CONFIGURE_OPTS="--with-openssl=$(brew --prefix openssl@3)"

echo "OpenSSL path: $(brew --prefix openssl@3)"

# Reinstall Python with OpenSSL support
echo "🐍 Reinstalling Python ${CURRENT_VERSION} with OpenSSL support..."
pyenv install ${CURRENT_VERSION}

echo ""
echo "✅ Done! Testing blake2 support..."
echo ""

# Test if blake2 works now
python3 -c "import hashlib; print('blake2b:', hashlib.blake2b); print('blake2s:', hashlib.blake2s); print('✅ blake2 support working!')" 2>&1

if [ $? -eq 0 ]; then
    echo ""
    echo "🎉 Python ${CURRENT_VERSION} reinstalled with blake2 support!"
    echo ""
    echo "📦 Reinstalling project dependencies..."
    pip install -r requirements.txt
else
    echo ""
    echo "❌ blake2 still not working. Additional troubleshooting needed."
    echo "Try: brew reinstall openssl@3"
fi
