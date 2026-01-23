FROM nvidia/cuda:12.1.0-runtime-ubuntu22.04
ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y \
    python3.10 \
    python3-pip \
    python3.10-venv \
    git \
    wget \
    curl \
    unzip \
    bc \
    ffmpeg \
    libgl1-mesa-glx \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

RUN update-alternatives --install /usr/bin/python python /usr/bin/python3.10 1
RUN update-alternatives --install /usr/bin/pip pip /usr/bin/pip3 1

RUN pip install --no-cache-dir torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121

RUN git clone https://github.com/comfyanonymous/ComfyUI.git /comfyui
WORKDIR /comfyui
RUN pip install --no-cache-dir -r requirements.txt

RUN pip install --no-cache-dir runpod huggingface_hub

RUN mkdir -p models/checkpoints \
    models/text_encoders \
    models/vae \
    models/loras \
    models/latent_upscale_models \
    input \
    output \
    workflows

WORKDIR /comfyui/custom_nodes
RUN git clone https://github.com/Lightricks/ComfyUI-LTXVideo.git && \
    cd ComfyUI-LTXVideo && \
    pip install --no-cache-dir -r requirements.txt || true

RUN git clone https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite.git && \
    cd ComfyUI-VideoHelperSuite && \
    pip install --no-cache-dir -r requirements.txt || true

RUN git clone https://github.com/kijai/ComfyUI-KJNodes.git && \
    cd ComfyUI-KJNodes && \
    pip install --no-cache-dir -r requirements.txt || true

RUN git clone https://github.com/pythongosssss/ComfyUI-Custom-Scripts.git && \
    cd ComfyUI-Custom-Scripts && \
    pip install --no-cache-dir -r requirements.txt || true

RUN pip install --no-cache-dir --force-reinstall torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121

COPY handler.py /handler.py
COPY start.sh /start.sh
COPY workflow_generated_audio.json /workflow_generated_audio.json
COPY workflow_custom_audio.json /workflow_custom_audio.json
RUN chmod +x /start.sh

RUN ln -sf /workflow_generated_audio.json /workflow.json

WORKDIR /
EXPOSE 8188
CMD ["/start.sh"]
