#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

rm -rf src/bahlily_storage/pb
mkdir -p src/bahlily_storage/pb

uv run python -m grpc_tools.protoc \
  -I ../transcription/proto \
  --python_out=src/bahlily_storage/pb \
  --grpc_python_out=src/bahlily_storage/pb \
  --pyi_out=src/bahlily_storage/pb \
  ../transcription/proto/transcription/v1/transcription.proto

find src/bahlily_storage/pb -type d -exec touch {}/__init__.py \;

python3 -c "
import pathlib
import sys


def replace_exactly_once(path: pathlib.Path, old: str, new: str) -> str:
    text = path.read_text()
    count = text.count(old)
    if count != 1:
        sys.exit(
            f'expected exactly one occurrence of {old!r} in {path}, found {count} '
            '-- protoc output shape may have changed; update gen_proto.sh'
        )
    return text.replace(old, new)


grpc_path = pathlib.Path('src/bahlily_storage/pb/transcription/v1/transcription_pb2_grpc.py')
grpc_path.write_text(
    replace_exactly_once(
        grpc_path,
        'from transcription.v1 import',
        'from bahlily_storage.pb.transcription.v1 import',
    )
)

pb2_path = pathlib.Path('src/bahlily_storage/pb/transcription/v1/transcription_pb2.py')
pb2_path.write_text(
    replace_exactly_once(
        pb2_path,
        \"'transcription.v1.transcription_pb2'\",
        \"'bahlily_storage.pb.transcription.v1.transcription_pb2'\",
    )
)
"

echo "proto codegen complete"
