#!/bin/bash
set -e
echo "=========================================="
echo "Starting ComfyUI LTX-2 Video Worker"
echo "=========================================="

# HuggingFace token for authenticated downloads
HF_TOKEN="${HF_TOKEN:-}"

echo ""
echo "=========================================="
echo "Environment Check"
echo "=========================================="
if [ -n "$HF_TOKEN" ]; then
    echo "✓ HF_TOKEN is set (${#HF_TOKEN} characters)"
    echo "  Token prefix: ${HF_TOKEN:0:10}..."
else
    echo "✗ HF_TOKEN is NOT set - authenticated downloads will fail!"
fi

# Robust download function with retries and fallbacks
download_hf_file() {
    local repo=$1
    local filename=$2
    local dest=$3
    local max_retries=3
    local retry=0
    
    if [ -f "$dest" ]; then
        local size=$(du -h "$dest" | cut -f1)
        echo "✓ Already exists: $dest ($size)"
        return 0
    fi
    
    echo "Downloading: $filename"
    echo "  From: $repo"
    echo "  To: $dest"
    
    mkdir -p "$(dirname "$dest")"
    
    while [ $retry -lt $max_retries ]; do
        # Method 1: With HF token if available
        if [ -n "$HF_TOKEN" ]; then
            echo "  Attempting download with HF_TOKEN..."
            if curl -L --fail --progress-bar --max-time 1800 \
                -H "Authorization: Bearer $HF_TOKEN" \
                -o "$dest" \
                "https://huggingface.co/${repo}/resolve/main/${filename}"; then
                local size=$(du -h "$dest" | cut -f1)
                echo "✓ Downloaded with token: $filename ($size)"
                return 0
            else
                echo "  Token download failed, trying without..."
            fi
        fi
        
        # Method 2: Without token (for public repos)
        echo "  Attempting download without token..."
        if wget -q --show-progress --timeout=300 -O "$dest" \
            "https://huggingface.co/${repo}/resolve/main/${filename}" 2>/dev/null; then
            local size=$(du -h "$dest" | cut -f1)
            echo "✓ Downloaded: $filename ($size)"
            return 0
        fi
        
        if curl -L --fail --progress-bar --max-time 1800 -o "$dest" \
            "https://huggingface.co/${repo}/resolve/main/${filename}" 2>/dev/null; then
            local size=$(du -h "$dest" | cut -f1)
            echo "✓ Downloaded: $filename ($size)"
            return 0
        fi
        
        retry=$((retry + 1))
        echo "  Retry $retry/$max_retries..."
        sleep 5
    done
    
    echo "✗ FAILED to download: $filename after $max_retries attempts"
    return 1
}

echo ""
echo "=========================================="
echo "Downloading Models..."
echo "=========================================="

# LTX-2 Checkpoint (27.1 GB)
echo ""
echo "[1/4] LTX-2 Checkpoint"
download_hf_file \
    "Lightricks/LTX-2" \
    "ltx-2-19b-dev-fp8.safetensors" \
    "/comfyui/models/checkpoints/ltx-2-19b-dev-fp8.safetensors"

# Gemma Text Encoder (requires HF token)
echo ""
echo "[2/4] Gemma Text Encoder (requires authentication)"
download_hf_file \
    "google/gemma-3-12b-it-qat-q4_0-unquantized" \
    "model.safetensors" \
    "/comfyui/models/text_encoders/gemma_3_12B_it.safetensors"

# Spatial Upscaler (996 MB)
echo ""
echo "[3/4] Spatial Upscaler"
download_hf_file \
    "Lightricks/LTX-2" \
    "ltx-2-spatial-upscaler-x2-1.0.safetensors" \
    "/comfyui/models/latent_upscale_models/ltx-2-spatial-upscaler-x2-1.0.safetensors"

# Distilled LoRA (7.67 GB)
echo ""
echo "[4/4] Distilled LoRA"
download_hf_file \
    "Lightricks/LTX-2" \
    "ltx-2-19b-distilled-lora-384.safetensors" \
    "/comfyui/models/loras/ltx-2-19b-distilled-lora-384.safetensors"

echo ""
echo "=========================================="
echo "Verifying Models..."
echo "=========================================="

verify_model() {
    local path=$1
    local name=$2
    if [ -f "$path" ]; then
        local size=$(du -h "$path" | cut -f1)
        echo "✓ $name ($size)"
        return 0
    else
        echo "✗ MISSING: $name"
        return 1
    fi
}

MISSING=0
verify_model "/comfyui/models/checkpoints/ltx-2-19b-dev-fp8.safetensors" "LTX-2 Checkpoint" || MISSING=1
verify_model "/comfyui/models/text_encoders/gemma_3_12B_it.safetensors" "Gemma Text Encoder" || MISSING=1
verify_model "/comfyui/models/latent_upscale_models/ltx-2-spatial-upscaler-x2-1.0.safetensors" "Spatial Upscaler" || MISSING=1
verify_model "/comfyui/models/loras/ltx-2-19b-distilled-lora-384.safetensors" "Distilled LoRA" || MISSING=1

if [ $MISSING -eq 1 ]; then
    echo ""
    echo "=========================================="
    echo "WARNING: Some models are missing!"
    echo "Generation will likely fail."
    echo "=========================================="
fi

echo ""
echo "=========================================="
echo "Starting ComfyUI server..."
echo "=========================================="

cd /comfyui
python main.py --listen 0.0.0.0 --port 8188 --disable-auto-launch &

echo "Waiting for ComfyUI to initialize..."
sleep 15

max_retries=30
retry_count=0
while [ $retry_count -lt $max_retries ]; do
    if curl -s http://127.0.0.1:8188/system_stats > /dev/null 2>&1; then
        echo "✓ ComfyUI is running!"
        break
    fi
    echo "Waiting for ComfyUI... (attempt $((retry_count+1))/$max_retries)"
    sleep 2
    retry_count=$((retry_count+1))
done

if [ $retry_count -eq $max_retries ]; then
    echo "WARNING: ComfyUI may not have started properly"
fi

echo ""
echo "=========================================="
echo "Starting RunPod handler..."
echo "=========================================="
cd /
python -u /handler.py
