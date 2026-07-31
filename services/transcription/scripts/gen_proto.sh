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

# Fix protoc-generated import paths to use installed package paths
python3 -c "
import pathlib, re
fixes = {
    'src/bahlily_transcription/pb/transcription/v1/transcription_pb2_grpc.py':
        ('from transcription.v1 import', 'from bahlily_transcription.pb.transcription.v1 import'),
    'src/bahlily_transcription/pb/audio_core/v1/audio_pb2_grpc.py':
        ('from audio_core.v1 import', 'from bahlily_transcription.pb.audio_core.v1 import'),
}
for path, (old, new) in fixes.items():
    p = pathlib.Path(path)
    p.write_text(p.read_text().replace(old, new))
"

echo "proto codegen complete"
