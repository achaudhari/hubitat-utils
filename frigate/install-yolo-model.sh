#!/bin/bash
#
# YOLOv9 Model Builder for Frigate
# Builds YOLOv9 ONNX model using Docker (from Frigate docs)
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_DIR="${SCRIPT_DIR}/config"
MODEL_CACHE_DIR="${CONFIG_DIR}/model_cache"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

# Default values
MODEL_SIZE="${1:-s}"  # t, s, m, c, or e
IMG_SIZE="${2:-640}"   # 320 or 640

mkdir -p "${MODEL_CACHE_DIR}"

echo -e "${GREEN}YOLOv9 Model Builder for Frigate${NC}"
echo "================================="
echo ""
echo "Building YOLOv9-${MODEL_SIZE} at ${IMG_SIZE}x${IMG_SIZE} resolution"
echo ""
echo "Available sizes:"
echo "  t = tiny (fastest, least accurate)"
echo "  s = small (good balance)"
echo "  m = medium (better accuracy)"
echo "  c = compact (high accuracy)"
echo "  e = extended (best accuracy, slowest)"
echo ""
echo -e "${YELLOW}This will use Docker to build the model...${NC}"
echo ""

# Check if docker is available
if ! command -v docker &> /dev/null; then
    echo -e "${RED}Error: Docker is required but not found${NC}"
    echo "Please install Docker first: https://docs.docker.com/get-docker/"
    exit 1
fi

# Build the model using the official Frigate documentation method
echo "Building model (this may take a few minutes)..."
echo ""

cd "${MODEL_CACHE_DIR}"

docker build . --build-arg MODEL_SIZE="${MODEL_SIZE}" --build-arg IMG_SIZE="${IMG_SIZE}" --output . -f- <<'EOF'
FROM python:3.11 AS build
RUN apt-get update && apt-get install --no-install-recommends -y libgl1 && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:0.8.0 /uv /bin/
WORKDIR /yolov9
ADD https://github.com/WongKinYiu/yolov9.git .
RUN uv pip install --system -r requirements.txt
RUN uv pip install --system onnx==1.18.0 onnxruntime onnx-simplifier>=0.4.1 onnxscript
ARG MODEL_SIZE
ARG IMG_SIZE
ADD https://github.com/WongKinYiu/yolov9/releases/download/v0.1/yolov9-${MODEL_SIZE}-converted.pt yolov9-${MODEL_SIZE}.pt
RUN sed -i "s/ckpt = torch.load(attempt_download(w), map_location='cpu')/ckpt = torch.load(attempt_download(w), map_location='cpu', weights_only=False)/g" models/experimental.py
RUN python3 export.py --weights ./yolov9-${MODEL_SIZE}.pt --imgsz ${IMG_SIZE} --simplify --include onnx
FROM scratch
ARG MODEL_SIZE
ARG IMG_SIZE
COPY --from=build /yolov9/yolov9-${MODEL_SIZE}.onnx /yolov9-${MODEL_SIZE}-${IMG_SIZE}.onnx
EOF

echo ""
echo "================================="
echo -e "${GREEN}Build Complete!${NC}"
echo "================================="
echo ""
echo "Model saved to: ${MODEL_CACHE_DIR}/yolov9-${MODEL_SIZE}-${IMG_SIZE}.onnx"
echo ""

if [ -f "${MODEL_CACHE_DIR}/yolov9-${MODEL_SIZE}-${IMG_SIZE}.onnx" ]; then
    ls -lh "${MODEL_CACHE_DIR}/yolov9-${MODEL_SIZE}-${IMG_SIZE}.onnx"
    echo ""
    echo "✓ Model ready to use!"
else
    echo -e "${RED}✗ Model file not found. Check errors above.${NC}"
    exit 1
fi
echo ""
echo "Next Steps:"
echo "----------"
echo "1. Update your frigate.yml.base with:"
echo ""
echo "detectors:"
echo "  ov:"
echo "    type: onnx"
echo "    device: AUTO"
echo ""
echo "model:"
echo "  model_type: yolo-generic"
echo "  width: ${IMG_SIZE}"
echo "  height: ${IMG_SIZE}"
echo "  input_tensor: nchw"
echo "  input_dtype: float"
echo "  path: /config/model_cache/yolov9-${MODEL_SIZE}-${IMG_SIZE}.onnx"
echo "  labelmap_path: /labelmap/coco-80.txt"
echo ""
echo "2. Make sure your docker-compose.yml mounts the config directory:"
echo "   volumes:"
echo "     - ./config:/config"
echo ""
echo "3. Restart Frigate"
echo ""
