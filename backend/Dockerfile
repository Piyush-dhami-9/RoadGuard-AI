FROM python:3.12-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends libglib2.0-0 libgl1 && rm -rf /var/lib/apt/lists/*
COPY backend/requirements.txt ./requirements.txt
# INSTALL_MODEL_DEPS=true adds the YOLO11 runtime (PyTorch + Ultralytics), needed for INFERENCE_MODE=yolo.
# The default image leaves it out: DEMO mode does not need it and it roughly triples the image size.
ARG INSTALL_MODEL_DEPS=false
# CPU-only PyTorch is installed first so Ultralytics does not pull the CUDA build,
# which adds several GB of NVIDIA wheels a CPU-only container cannot use.
# Ultralytics also requires the non-headless OpenCV package; it is pinned to the same version as the
# headless one in requirements.txt so the image does not pick up whatever release is newest.
RUN if [ "$INSTALL_MODEL_DEPS" = "true" ]; then \
			pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu torch==2.15.0 torchvision==0.29.2 && \
			pip install --no-cache-dir -r requirements.txt opencv-python==4.10.0.84; \
		else \
			grep -v '^ultralytics==' requirements.txt > runtime-requirements.txt && \
			pip install --no-cache-dir -r runtime-requirements.txt; \
		fi
# Keeps Ultralytics' settings file inside the container's writable temp space.
ENV YOLO_CONFIG_DIR=/tmp/ultralytics
COPY backend/app ./app
RUN mkdir -p uploads model/weights
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
