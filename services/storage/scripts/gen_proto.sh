#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

# Generate into a staging directory and validate everything there first;
# the existing src/bahlily_storage/pb is only replaced once generation and
# the import-rewrite both succeed, so a failure partway through (protoc
# error, an unexpected rewrite match count) never leaves the working tree
# with a missing or half-generated pb package. The final swap itself also
# renames the old package aside rather than deleting it up front, so a
# failure during the copy/rename can still be rolled back.
staging_dir="$(mktemp -d)"
new_pb="src/bahlily_storage/pb.new.$$"
old_pb_backup="src/bahlily_storage/pb.old.$$"
cleanup() {
  rm -rf "$staging_dir" "$new_pb"
  if [ -d "$old_pb_backup" ] && [ ! -d src/bahlily_storage/pb ]; then
    mv "$old_pb_backup" src/bahlily_storage/pb
  fi
  rm -rf "$old_pb_backup"
}
trap cleanup EXIT

uv run python -m grpc_tools.protoc \
  -I ../transcription/proto \
  --python_out="$staging_dir" \
  --grpc_python_out="$staging_dir" \
  --pyi_out="$staging_dir" \
  ../transcription/proto/transcription/v1/transcription.proto

find "$staging_dir" -type d -exec touch {}/__init__.py \;

STAGING_DIR="$staging_dir" python3 -c "
import os
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


staging_dir = pathlib.Path(os.environ['STAGING_DIR'])

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

mkdir -p src/bahlily_storage
rm -rf "$new_pb"
cp -R "$staging_dir" "$new_pb"

rm -rf "$old_pb_backup"
if [ -d src/bahlily_storage/pb ]; then
  mv src/bahlily_storage/pb "$old_pb_backup"
fi
mv "$new_pb" src/bahlily_storage/pb
rm -rf "$old_pb_backup"

echo "proto codegen complete"
