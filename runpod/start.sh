#!/bin/bash
# ─────────────────────────────────────────────────────────────
# RunPod startup script for PersonaPlex 7B 4-bit
# Run this inside your RunPod pod after SSH-ing in.
# Tested on: RTX 3080 12GB / RTX 3090 / A4000
# ─────────────────────────────────────────────────────────────

set -e

echo "==> Installing system dependencies..."
apt-get update -qq && apt-get install -y -qq \
    libsndfile1 ffmpeg git curl build-essential

echo "==> Installing Python packages..."
pip install -q \
    moshi \
    huggingface_hub \
    bitsandbytes \
    accelerate \
    transformers \
    torch \
    torchaudio

echo "==> Downloading PersonaPlex 7B 4-bit from HuggingFace..."
# This uses the moshi PyTorch backend with the BnB-4bit quantised weights
python - <<'PYEOF'
from huggingface_hub import snapshot_download
snapshot_download(
    repo_id="brianmatzelle/personaplex-7b-v1-bnb-4bit",
    local_dir="/workspace/personaplex-model",
    ignore_patterns=["*.msgpack", "flax_model*"],
)
print("Model downloaded to /workspace/personaplex-model")
PYEOF

echo "==> Starting PersonaPlex WebSocket server on port 8998..."
echo "    Audio format: 24kHz PCM float32, 80ms frames"
echo "    Protocol: Moshi WebSocket (binary frames)"
echo ""
echo "    Connect from your bridge at: ws://<RUNPOD_PUBLIC_IP>:8998"
echo ""

# --hf-repo points to the local download OR HuggingFace directly.
# Using local path avoids re-downloading on restart.
python -m moshi.server \
    --hf-repo /workspace/personaplex-model \
    --port 8998 \
    --host 0.0.0.0
    # Remove --ssl flags for plain ws:// (fine for LAN/private testing)
    # Add --ssl-certfile cert.pem --ssl-keyfile key.pem for wss://
