#!/usr/bin/env bash
# Local RTX 3080 profile. Requires the already built K2-compatible llama.cpp.
set -euo pipefail
cd "$(dirname "$0")/.."
model="${1:?Usage: bash examples/start_k2.sh /path/to/K2-Horizon-7B-Q4_K_M.gguf}"
export LD_LIBRARY_PATH="$PWD/.cache/cuda-k2/lib64${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
exec .cache/llama-k2/build-cuda/bin/llama-server \
  --model "$model" --device CUDA0 --gpu-layers 999 --override-tensor '.*=CUDA0' \
  --split-mode none --fit off --ctx-size 8192 --parallel 1 \
  --batch-size 512 --ubatch-size 128 --flash-attn on \
  --host 127.0.0.1 --port 18089 --no-webui --reasoning-budget 1024
