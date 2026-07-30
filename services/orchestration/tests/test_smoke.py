from unittest.mock import patch

from bahlily_orchestration import main
from bahlily_orchestration.app import app


def test_app_is_a_fastapi_instance() -> None:
    assert app.title == "bahlily-orchestration"


def test_main_starts_uvicorn_with_expected_args() -> None:
    with patch("uvicorn.run") as mock_run:
        main()
    mock_run.assert_called_once_with("bahlily_orchestration.app:app", host="127.0.0.1", port=8001)
