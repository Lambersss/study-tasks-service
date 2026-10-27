"""Простой API для учёта учебных задач."""

from fastapi import FastAPI

APP_VERSION = "1.0.0"


def create_app() -> FastAPI:
    app = FastAPI(
        title="Study Tasks API",
        description="Учебные задачи: создать, посмотреть и отметить выполнение.",
        version=APP_VERSION,
    )

    @app.get("/", tags=["service"])
    async def root():
        return {"name": app.title, "docs": "/docs"}

    @app.get("/health", tags=["service"])
    async def health():
        return {"status": "ok"}

    @app.get("/version", tags=["service"])
    async def version():
        return {"version": APP_VERSION}

    return app


app = create_app()
