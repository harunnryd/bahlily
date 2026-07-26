from pathlib import Path

from bahlily_logging.catalog import CatalogEntry, check_consistency, load_catalog, scan_codes_in_use


def test_load_catalog_parses_entries(tmp_path: Path) -> None:
    catalog_path = tmp_path / "error-catalog.yaml"
    catalog_path.write_text(
        "- code: TEST_DOMAIN_FAILED\n"
        "  domain: test-domain\n"
        "  severity: error\n"
        "  description: A test error.\n"
    )

    entries = load_catalog(catalog_path)

    assert entries == [
        CatalogEntry(
            code="TEST_DOMAIN_FAILED",
            domain="test-domain",
            severity="error",
            description="A test error.",
        )
    ]


def test_scan_codes_in_use_finds_rust_and_python_call_sites(tmp_path: Path) -> None:
    (tmp_path / "target").mkdir()
    (tmp_path / "target" / "ignored.rs").write_text('code = "IGNORED_TARGET_CODE"')

    (tmp_path / "shell.rs").write_text(
        'tracing::error!(code = "AUDIO_CAPTURE_STREAM_ERROR", "cpal input stream error");'
    )
    (tmp_path / "service.py").write_text('raise BahlilyError("boom", code="STORAGE_RESERVED")')

    codes = scan_codes_in_use(tmp_path)

    assert codes == {"AUDIO_CAPTURE_STREAM_ERROR", "STORAGE_RESERVED"}


def test_check_consistency_reports_codes_missing_from_catalog(tmp_path: Path) -> None:
    catalog_path = tmp_path / "error-catalog.yaml"
    catalog_path.write_text(
        "- code: KNOWN_CODE\n  domain: test-domain\n  severity: error\n  description: Known.\n"
    )
    scan_root = tmp_path / "src"
    scan_root.mkdir()
    (scan_root / "app.py").write_text('raise BahlilyError("x", code="UNKNOWN_CODE")')

    missing = check_consistency(catalog_path, scan_root)

    assert missing == ["UNKNOWN_CODE"]


def test_check_consistency_allows_unused_placeholder_codes(tmp_path: Path) -> None:
    catalog_path = tmp_path / "error-catalog.yaml"
    catalog_path.write_text(
        "- code: SOME_RESERVED\n"
        "  domain: test-domain\n"
        "  severity: info\n"
        "  description: Reserved, unused.\n"
    )
    scan_root = tmp_path / "src"
    scan_root.mkdir()

    missing = check_consistency(catalog_path, scan_root)

    assert missing == []
