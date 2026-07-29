from bahlily_orchestration.app import app


def test_app_is_a_fastapi_instance() -> None:
    assert app.title == "bahlily-orchestration"
