#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

rm -rf src/bahlily_transcription/pb
mkdir -p src/bahlily_transcription/pb

uv run python -m grpc_tools.protoc \
  -I proto \
  -I ../../shell/audio-core/proto \
  --python_out=src/bahlily_transcription/pb \
  --grpc_python_out=src/bahlily_transcription/pb \
  --pyi_out=src/bahlily_transcription/pb \
  proto/transcription/v1/transcription.proto \
  ../../shell/audio-core/proto/audio_core/v1/audio.proto

# Create __init__.py in every generated subdirectory
find src/bahlily_transcription/pb -type d -exec touch {}/__init__.py \;

echo "proto codegen complete"
