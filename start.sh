#!/bin/bash
set -e
echo "=========================================="
echo "Starting ComfyUI LTX-2 Video Worker"
echo "=========================================="

download_file() {
    local url=$1
    local dest=$2
    
    if [ -f "$dest" ]; then
        local size=$(du -h "$dest" | cut -f1)
        echo "✓ Already exists: $(basename $dest) ($size)"
        return 0
    fi
    
    echo "  Downloading: $(basename $dest)"
    mkdir -p "$(dirname "$dest")"
    
    if curl -L --fail --progress-bar --max-time 3600 -o "$dest" "$url"; then
        local size=$(du -h "$dest" | cut -f1)
        echo "  ✓ Downloaded: $(basename $dest) ($size)"
        return 0
    fi
    
    echo "  ✗ FAILED: $(basename $dest)"
    return 1
}

echo ""
echo "=========================================="
echo "Downloading Models..."
echo "=========================================="

# 1. LTX-2 Checkpoint (25GB)
echo ""
echo "[1/4] LTX-2 Checkpoint"
download_file \
    "https://huggingface.co/Lightricks/LTX-2/resolve/main/ltx-2-19b-dev-fp8.safetensors" \
    "/comfyui/models/checkpoints/ltx-2-19b-dev-fp8.safetensors"

# 2. Gemma Text Encoder (23GB) - From Comfy-Org (pre-merged, no auth needed)
echo ""
echo "[2/4] Gemma Text Encoder"
download_file \
    "https://huggingface.co/Comfy-Org/ltx-2/resolve/main/split_files/text_encoders/gemma_3_12B_it.safetensors" \
    "/comfyui/models/text_encoders/gemma_3_12B_it.safetensors"

# 3. Spatial Upscaler (950MB)
echo ""
echo "[3/4] Spatial Upscaler"
download_file \
    "https://huggingface.co/Lightricks/LTX-2/resolve/main/ltx-2-spatial-upscaler-x2-1.0.safetensors" \
    "/comfyui/models/latent_upscale_models/ltx-2-spatial-upscaler-x2-1.0.safetensors"

# 4. Distilled LoRA (7.15GB)
echo ""
echo "[4/4] Distilled LoRA"
download_file \
    "https://huggingface.co/Lightricks/LTX-2/resolve/main/ltx-2-19b-distilled-lora-384.safetensors" \
    "/comfyui/models/loras/ltx-2-19b-distilled-lora-384.safetensors"

echo ""
echo "=========================================="
echo "Verifying Models..."
echo "=========================================="

for f in \
    "/comfyui/models/checkpoints/ltx-2-19b-dev-fp8.safetensors" \
    "/comfyui/models/text_encoders/gemma_3_12B_it.safetensors" \
    "/comfyui/models/latent_upscale_models/ltx-2-spatial-upscaler-x2-1.0.safetensors" \
    "/comfyui/models/loras/ltx-2-19b-distilled-lora-384.safetensors"
do
    if [ -f "$f" ]; then
        size=$(du -h "$f" | cut -f1)
        echo "✓ $(basename $f) ($size)"
    else
        echo "✗ MISSING: $(basename $f)"
    fi
done

echo ""
echo "=========================================="
echo "Starting ComfyUI..."
echo "=========================================="

cd /comfyui
python main.py --listen 0.0.0.0 --port 8188 --disable-auto-launch &

echo "Waiting for ComfyUI..."
sleep 15

for i in $(seq 1 30); do
    if curl -s http://127.0.0.1:8188/system_stats > /dev/null 2>&1; then
        echo "✓ ComfyUI is running!"
        break
    fi
    echo "  Waiting... ($i/30)"
    sleep 2
done

echo ""
echo "=========================================="
echo "Starting Handler..."
echo "=========================================="
cd /
python -u /handler.py
