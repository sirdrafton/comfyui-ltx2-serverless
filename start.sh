#!/bin/bash
set -e
echo "=========================================="
echo "Starting ComfyUI LTX-2 Video Worker"
echo "=========================================="

HF_TOKEN="${HF_TOKEN:-}"

echo ""
echo "=========================================="
echo "Environment Check"
echo "=========================================="
if [ -n "$HF_TOKEN" ]; then
    echo "✓ HF_TOKEN is set (${#HF_TOKEN} characters)"
else
    echo "⚠ HF_TOKEN is NOT set"
fi

download_hf_file() {
    local repo=$1
    local filename=$2
    local dest=$3
    
    if [ -f "$dest" ]; then
        local size=$(du -h "$dest" | cut -f1)
        echo "✓ Already exists: $(basename $dest) ($size)"
        return 0
    fi
    
    echo "  Downloading: $filename"
    mkdir -p "$(dirname "$dest")"
    
    if [ -n "$HF_TOKEN" ]; then
        if curl -L --fail --progress-bar --max-time 3600 \
            -H "Authorization: Bearer $HF_TOKEN" \
            -o "$dest" \
            "https://huggingface.co/${repo}/resolve/main/${filename}"; then
            local size=$(du -h "$dest" | cut -f1)
            echo "  ✓ Downloaded: $(basename $dest) ($size)"
            return 0
        fi
    fi
    
    if curl -L --fail --progress-bar --max-time 3600 -o "$dest" \
        "https://huggingface.co/${repo}/resolve/main/${filename}"; then
        local size=$(du -h "$dest" | cut -f1)
        echo "  ✓ Downloaded: $(basename $dest) ($size)"
        return 0
    fi
    
    echo "  ✗ FAILED: $filename"
    return 1
}

echo ""
echo "=========================================="
echo "Downloading Models..."
echo "=========================================="

# 1. LTX-2 Checkpoint (27GB)
echo ""
echo "[1/4] LTX-2 Checkpoint (27GB)"
download_hf_file "Lightricks/LTX-2" "ltx-2-19b-dev-fp8.safetensors" "/comfyui/models/checkpoints/ltx-2-19b-dev-fp8.safetensors"

# 2. Gemma Text Encoder - Download shards and merge
echo ""
echo "[2/4] Gemma Text Encoder (24GB - 5 shards)"
GEMMA_DEST="/comfyui/models/text_encoders/gemma_3_12B_it.safetensors"
if [ -f "$GEMMA_DEST" ]; then
    size=$(du -h "$GEMMA_DEST" | cut -f1)
    echo "✓ Already exists: gemma_3_12B_it.safetensors ($size)"
else
    echo "  Downloading 5 shards..."
    mkdir -p /comfyui/models/text_encoders
    
    for i in 1 2 3 4 5; do
        SHARD="model-0000${i}-of-00005.safetensors"
        download_hf_file "google/gemma-3-12b-it" "$SHARD" "/comfyui/models/text_encoders/$SHARD"
    done
    
    download_hf_file "google/gemma-3-12b-it" "model.safetensors.index.json" "/comfyui/models/text_encoders/model.safetensors.index.json"
    
    echo "  Merging shards into single file..."
    python3 << 'PYMERGE'
import json
import os
from safetensors.torch import load_file, save_file

base_path = "/comfyui/models/text_encoders"
output_path = os.path.join(base_path, "gemma_3_12B_it.safetensors")

# Load index to get shard mapping
with open(os.path.join(base_path, "model.safetensors.index.json")) as f:
    index = json.load(f)

# Collect all tensors from shards
all_tensors = {}
shards = set(index["weight_map"].values())
for shard in sorted(shards):
    print(f"  Loading {shard}...")
    shard_path = os.path.join(base_path, shard)
    tensors = load_file(shard_path)
    all_tensors.update(tensors)

print(f"  Saving merged file ({len(all_tensors)} tensors)...")
save_file(all_tensors, output_path)
print("  ✓ Merge complete!")

# Clean up shards
for shard in shards:
    os.remove(os.path.join(base_path, shard))
os.remove(os.path.join(base_path, "model.safetensors.index.json"))
print("  ✓ Cleaned up shards")
PYMERGE
fi

# 3. Spatial Upscaler
echo ""
echo "[3/4] Spatial Upscaler (996MB)"
download_hf_file "Lightricks/LTX-2" "ltx-2-spatial-upscaler-x2-1.0.safetensors" "/comfyui/models/latent_upscale_models/ltx-2-spatial-upscaler-x2-1.0.safetensors"

# 4. Distilled LoRA
echo ""
echo "[4/4] Distilled LoRA (7.6GB)"
download_hf_file "Lightricks/LTX-2" "ltx-2-19b-distilled-lora-384.safetensors" "/comfyui/models/loras/ltx-2-19b-distilled-lora-384.safetensors"

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
