def main() -> None:
    import uvicorn

    uvicorn.run("bahlily_orchestration.app:app", host="127.0.0.1", port=8001)
