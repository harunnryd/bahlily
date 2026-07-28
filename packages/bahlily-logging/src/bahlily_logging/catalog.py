from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import yaml

_SCAN_EXTENSIONS = (".rs", ".py")
# "tests" is excluded so fixture code strings (e.g. a literal placeholder value
# used only to assert on log output) don't pollute the codes-in-use scan and
# force fake catalog entries for test-only values.
_SCAN_EXCLUDED_DIR_NAMES = {"target", ".venv", "__pycache__", ".git", "node_modules", "tests"}
_CODE_PATTERN = re.compile(r'code\s*[=:]\s*[\'"]([A-Z][A-Z0-9_]*)[\'"]')
_CODE_FORMAT_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]*$")


@dataclass(frozen=True)
class CatalogEntry:
    code: str
    domain: str
    severity: str
    description: str


def load_catalog(path: Path) -> list[CatalogEntry]:
    data = yaml.safe_load(path.read_text())
    entries = [CatalogEntry(**entry) for entry in data]

    seen_codes: set[str] = set()
    for entry in entries:
        if not _CODE_FORMAT_PATTERN.match(entry.code):
            raise ValueError(
                f"Catalog code {entry.code!r} does not match the {{DOMAIN}}_{{CONDITION}} "
                "convention (uppercase letters, digits, underscores, starting with a letter)."
            )
        if entry.code in seen_codes:
            raise ValueError(f"Duplicate catalog code: {entry.code!r}")
        seen_codes.add(entry.code)

    return entries


def scan_codes_in_use(root: Path) -> set[str]:
    codes: set[str] = set()
    for path in root.rglob("*"):
        if path.suffix not in _SCAN_EXTENSIONS:
            continue
        if _SCAN_EXCLUDED_DIR_NAMES & set(path.parts):
            continue
        codes.update(_CODE_PATTERN.findall(path.read_text(errors="ignore")))
    return codes


def check_consistency(catalog_path: Path, scan_root: Path) -> list[str]:
    catalog_codes = {entry.code for entry in load_catalog(catalog_path)}
    used_codes = scan_codes_in_use(scan_root)
    return sorted(used_codes - catalog_codes)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Fail if any error code used in source is missing from the error catalog."
    )
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--scan-root", type=Path, required=True)
    args = parser.parse_args(argv)

    if not args.scan_root.is_dir():
        print(
            f"--scan-root {args.scan_root} does not exist or is not a directory.",
            file=sys.stderr,
        )
        sys.exit(1)

    missing = check_consistency(args.catalog, args.scan_root)
    if missing:
        print("Error codes used in source but missing from the catalog:", file=sys.stderr)
        for code in missing:
            print(f"  {code}", file=sys.stderr)
        sys.exit(1)
    print("Error catalog is consistent with source.")
