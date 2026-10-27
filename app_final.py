"""Простой API для учёта учебных задач."""

from contextlib import asynccontextmanager
import logging
import os
from pathlib import Path as FilePath
from time import perf_counter
from typing import Annotated

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Path, Request, Response
from pydantic import BaseModel, ConfigDict, StrictBool, StringConstraints

APP_VERSION = "1.0.0"
logger = logging.getLogger("study_tasks")

TaskTitle = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)
]
TaskId = Annotated[int, Path(gt=0, description="Положительный номер задачи")]


class TaskCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: TaskTitle


class Task(BaseModel):
    id: int
    title: str
    completed: bool = False


class TaskUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    completed: StrictBool


class TaskStats(BaseModel):
    total: int
    completed: int
    pending: int


def create_app() -> FastAPI:
    load_dotenv(FilePath(__file__).with_name(".env"), override=False)
    app_name = os.getenv("APP_NAME", "Study Tasks API").strip()
    if not app_name:
        raise ValueError("APP_NAME must not be empty")
    try:
        max_tasks = int(os.getenv("MAX_TASKS", "100"))
    except ValueError as exc:
        raise ValueError("MAX_TASKS must be a positive integer") from exc
    if max_tasks < 1:
        raise ValueError("MAX_TASKS must be a positive integer")
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    if log_level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
        raise ValueError("LOG_LEVEL must be DEBUG, INFO, WARNING, ERROR or CRITICAL")
    logger.setLevel(log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(levelname)s %(name)s %(message)s",
        )
        logger.info("Application started version=%s max_tasks=%s", APP_VERSION, max_tasks)
        yield
        logger.info("Application stopped")

    app = FastAPI(
        title=app_name,
        description="Учебные задачи: создать, посмотреть и отметить выполнение.",
        version=APP_VERSION,
        lifespan=lifespan,
    )
    # Каждый экземпляр приложения имеет собственный список задач.
    tasks: dict[int, Task] = {}
    next_id = 1

    @app.middleware("http")
    async def log_requests(request: Request, call_next):
        started = perf_counter()
        response = await call_next(request)
        # Логируем шаблон маршрута, без тела, заголовков и параметров запроса.
        route = request.scope.get("route")
        logger.info(
            "Request method=%s route=%s status=%s duration_ms=%.1f",
            request.method,
            getattr(route, "path", "unmatched"),
            response.status_code,
            (perf_counter() - started) * 1000,
        )
        return response

    def find_task(task_id: int) -> Task:
        if task_id not in tasks:
            raise HTTPException(status_code=404, detail="Задача не найдена")
        return tasks[task_id]

    @app.get("/", tags=["service"])
    async def root():
        return {"name": app.title, "docs": "/docs"}

    @app.get("/health", tags=["service"])
    async def health():
        return {"status": "ok"}

    @app.get("/version", tags=["service"])
    async def version():
        return {"version": APP_VERSION}

    @app.post("/tasks", response_model=Task, status_code=201, tags=["tasks"])
    async def create_task(payload: TaskCreate):
        nonlocal next_id
        if len(tasks) >= max_tasks:
            raise HTTPException(status_code=409, detail="Достигнут лимит задач")
        task = Task(id=next_id, title=payload.title)
        tasks[task.id] = task
        next_id += 1
        logger.info("Task created id=%s", task.id)
        return task

    @app.get("/tasks", response_model=list[Task], tags=["tasks"])
    async def list_tasks(completed: bool | None = None):
        return [
            task for task in tasks.values()
            if completed is None or task.completed == completed
        ]

    @app.get("/tasks/{task_id}", response_model=Task, tags=["tasks"])
    async def get_task(task_id: TaskId):
        return find_task(task_id)

    @app.patch("/tasks/{task_id}", response_model=Task, tags=["tasks"])
    async def update_task(task_id: TaskId, payload: TaskUpdate):
        task = find_task(task_id)
        task.completed = payload.completed
        logger.info("Task updated id=%s completed=%s", task.id, task.completed)
        return task

    @app.delete("/tasks/{task_id}", status_code=204, tags=["tasks"])
    async def delete_task(task_id: TaskId):
        find_task(task_id)
        del tasks[task_id]
        logger.info("Task deleted id=%s", task_id)
        return Response(status_code=204)

    @app.get("/stats", response_model=TaskStats, tags=["tasks"])
    async def task_stats():
        completed = sum(task.completed for task in tasks.values())
        return TaskStats(
            total=len(tasks), completed=completed, pending=len(tasks) - completed
        )

    return app


app = create_app()
