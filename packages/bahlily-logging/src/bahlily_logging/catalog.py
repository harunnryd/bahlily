from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import yaml

_SCAN_EXTENSIONS = (".rs", ".py")
_SCAN_EXCLUDED_DIR_NAMES = {"target", ".venv", "__pycache__", ".git", "node_modules", "tests"}
_CODE_PATTERN = re.compile(r'code\s*[=:]\s*"([A-Z][A-Z0-9_]*)"')


@dataclass(frozen=True)
class CatalogEntry:
    code: str
    domain: str
    severity: str
    description: str


def load_catalog(path: Path) -> list[CatalogEntry]:
    data = yaml.safe_load(path.read_text())
    return [CatalogEntry(**entry) for entry in data]


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


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fail if any error code used in source is missing from the error catalog."
    )
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--scan-root", type=Path, required=True)
    args = parser.parse_args()

    missing = check_consistency(args.catalog, args.scan_root)
    if missing:
        print("Error codes used in source but missing from the catalog:", file=sys.stderr)
        for code in missing:
            print(f"  {code}", file=sys.stderr)
        sys.exit(1)
    print("Error catalog is consistent with source.")
