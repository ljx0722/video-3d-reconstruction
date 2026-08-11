FROM nvidia/cuda:12.4.0-runtime-ubuntu22.04

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3.10 python3-pip libgl1-mesa-glx libglib2.0-0 ffmpeg \
    && rm -rf /var/lib/apt/lists/* \
    && update-alternatives --install /usr/bin/python python /usr/bin/python3.10 1

WORKDIR /app
COPY gpu_worker/requirements.txt ./gpu_worker/requirements.txt
COPY lingbot-map-vendor ./lingbot-map-vendor
RUN pip install --no-cache-dir -r gpu_worker/requirements.txt \
    && pip install --no-cache-dir --no-deps ./lingbot-map-vendor
COPY gpu_worker ./gpu_worker

WORKDIR /app/gpu_worker
CMD ["python", "gpu_server.py"]
