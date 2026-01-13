#!/bin/bash
set -e

echo "=============================================="
echo "  LTX-2 VIDEO SERVERLESS STARTUP"
echo "=============================================="
echo "Start time: $(date)"

# List available models
echo ""
echo "=== Available Models ==="
echo "Checkpoints:"
ls -lh /comfyui/models/checkpoints/ 2>/dev/null || echo "  (empty)"
echo "Text Encoders:"
ls -lh /comfyui/models/text_encoders/ 2>/dev/null || echo "  (empty)"
echo "LoRAs:"
ls -lh /comfyui/models/loras/ 2>/dev/null || echo "  (empty)"
echo "Upscalers:"
ls -lh /comfyui/models/latent_upscale_models/ 2>/dev/null || echo "  (empty)"

echo ""
echo "=== Starting ComfyUI ==="
cd /comfyui
python main.py --listen 0.0.0.0 --port 8188 --disable-auto-launch &
COMFYUI_PID=$!

echo "ComfyUI starting with PID: $COMFYUI_PID"

# Wait for ComfyUI to be ready
echo "Waiting for ComfyUI to initialize..."
MAX_WAIT=120
WAITED=0

while [ $WAITED -lt $MAX_WAIT ]; do
    if curl -s http://127.0.0.1:8188/system_stats > /dev/null 2>&1; then
        echo "✓ ComfyUI is ready!"
        break
    fi
    sleep 2
    WAITED=$((WAITED + 2))
    if [ $((WAITED % 10)) -eq 0 ]; then
        echo "  Still waiting... (${WAITED}s)"
    fi
done

if [ $WAITED -ge $MAX_WAIT ]; then
    echo "✗ ComfyUI failed to start within ${MAX_WAIT}s"
    exit 1
fi

echo ""
echo "=== Starting RunPod Handler ==="
python /handler.py
