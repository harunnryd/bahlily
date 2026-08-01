#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

# Generate into a staging directory and validate everything there first;
# the existing src/bahlily_storage/pb is only replaced once generation and
# the import-rewrite both succeed, so a failure partway through (protoc
# error, an unexpected rewrite match count) never leaves the working tree
# with a missing or half-generated pb package.
staging_dir="$(mktemp -d)"
trap 'rm -rf "$staging_dir"' EXIT

uv run python -m grpc_tools.protoc \
  -I ../transcription/proto \
  --python_out="$staging_dir" \
  --grpc_python_out="$staging_dir" \
  --pyi_out="$staging_dir" \
  ../transcription/proto/transcription/v1/transcription.proto

find "$staging_dir" -type d -exec touch {}/__init__.py \;

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


staging_dir = pathlib.Path('$staging_dir')

grpc_path = staging_dir / 'transcription/v1/transcription_pb2_grpc.py'
grpc_path.write_text(
    replace_exactly_once(
        grpc_path,
        'from transcription.v1 import',
        'from bahlily_storage.pb.transcription.v1 import',
    )
)

pb2_path = staging_dir / 'transcription/v1/transcription_pb2.py'
pb2_path.write_text(
    replace_exactly_once(
        pb2_path,
        \"'transcription.v1.transcription_pb2'\",
        \"'bahlily_storage.pb.transcription.v1.transcription_pb2'\",
    )
)
"

rm -rf src/bahlily_storage/pb
mkdir -p src/bahlily_storage
cp -R "$staging_dir" src/bahlily_storage/pb

echo "proto codegen complete"
