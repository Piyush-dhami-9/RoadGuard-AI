FROM python:3.12-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends libglib2.0-0 libgl1 && rm -rf /var/lib/apt/lists/*
# Install CPU-only torch first so ultralytics does not pull the CUDA build,
# which adds several GB of NVIDIA wheels this CPU-only service cannot use.
RUN pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu torch torchvision
COPY backend/requirements.txt ./requirements.txt
ARG INSTALL_MODEL_DEPS=false
RUN if [ "$INSTALL_MODEL_DEPS" = "true" ]; then \
			pip install --no-cache-dir -r requirements.txt; \
		else \
			grep -v '^ultralytics==' requirements.txt > runtime-requirements.txt && \
			pip install --no-cache-dir -r runtime-requirements.txt; \
		fi
COPY backend/app ./app
COPY model ./model
RUN mkdir -p uploads
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
