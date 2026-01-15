#!/bin/bash

# 设置错误时退出
set -e

echo "================================================"
echo "Reinstalling GetRich (macOS/Linux)"
echo "================================================"

# 1. 初始化 Conda
# 优先使用用户提供的路径 /opt/miniconda3
CONDA_BASE="/opt/miniconda3"

# 尝试 source conda.sh 以启用 conda activate 命令
if [ -f "$CONDA_BASE/etc/profile.d/conda.sh" ]; then
    source "$CONDA_BASE/etc/profile.d/conda.sh"
elif [ -f "$HOME/miniconda3/etc/profile.d/conda.sh" ]; then
    source "$HOME/miniconda3/etc/profile.d/conda.sh"
elif [ -f "$HOME/anaconda3/etc/profile.d/conda.sh" ]; then
    source "$HOME/anaconda3/etc/profile.d/conda.sh"
fi

echo ""
echo "[1/4] Activating 'dev' environment..."
# 检查 conda 是否可用
if command -v conda >/dev/null 2>&1; then
    conda activate dev || { 
        echo "Error: Could not activate conda environment 'dev'."
        echo "Please ensure it exists: conda create -n dev python=3.12"
        exit 1
    }
else
    echo "Warning: 'conda' command not found. Assuming python environment is already set up."
fi

echo ""
echo "[2/4] Uninstalling existing package..."
# 忽略未安装的错误
pip uninstall getrich -y || true

echo ""
echo "[3/4] Installing in editable mode..."
pip install -e .

echo ""
echo "[4/4] Cleaning up build artifacts..."
rm -rf build/ dist/ src/*.egg-info/ *.egg-info/
find . -type d -name "__pycache__" -exec rm -rf {} +

echo ""
echo "================================================"
echo "Installation Complete!"
echo "================================================"
