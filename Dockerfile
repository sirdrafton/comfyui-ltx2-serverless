# ComfyUI LTX-2 Video Serverless Endpoint
FROM nvidia/cuda:12.1.0-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1

# Install system dependencies
RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    python3-venv \
    git \
    wget \
    curl \
    ffmpeg \
    libgl1-mesa-glx \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    && rm -rf /var/lib/apt/lists/*

RUN ln -sf /usr/bin/python3 /usr/bin/python

WORKDIR /
RUN git clone https://github.com/comfyanonymous/ComfyUI.git /comfyui

WORKDIR /comfyui
RUN pip install --no-cache-dir torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121
RUN pip install --no-cache-dir -r requirements.txt

RUN pip install --no-cache-dir \
    runpod \
    requests \
    websocket-client \
    Pillow \
    numpy \
    opencv-python-headless \
    sentencepiece \
    transformers \
    accelerate \
    safetensors

# Install ComfyUI Manager
RUN git clone https://github.com/ltdrdata/ComfyUI-Manager.git /comfyui/custom_nodes/ComfyUI-Manager

# Install VideoHelperSuite
RUN git clone https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite.git /comfyui/custom_nodes/ComfyUI-VideoHelperSuite
RUN pip install --no-cache-dir -r /comfyui/custom_nodes/ComfyUI-VideoHelperSuite/requirements.txt || true

# Install LTX-Video nodes
RUN git clone https://github.com/Lightricks/ComfyUI-LTXVideo.git /comfyui/custom_nodes/ComfyUI-LTXVideo
RUN pip install --no-cache-dir -r /comfyui/custom_nodes/ComfyUI-LTXVideo/requirements.txt || true

# Create model directories
RUN mkdir -p /comfyui/models/checkpoints \
    /comfyui/models/text_encoders \
    /comfyui/models/vae \
    /comfyui/models/loras \
    /comfyui/models/latent_upscale_models \
    /comfyui/input \
    /comfyui/output

COPY handler.py /handler.py
COPY start.sh /start.sh
COPY workflow.json /workflow.json

RUN chmod +x /start.sh

EXPOSE 8188

CMD ["/start.sh"]
