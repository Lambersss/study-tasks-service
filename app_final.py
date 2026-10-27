"""Простой API для учёта учебных задач."""

from typing import Annotated

from fastapi import FastAPI, HTTPException, Path
from pydantic import BaseModel, ConfigDict, StringConstraints

APP_VERSION = "1.0.0"

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


def create_app() -> FastAPI:
    app = FastAPI(
        title="Study Tasks API",
        description="Учебные задачи: создать, посмотреть и отметить выполнение.",
        version=APP_VERSION,
    )
    # Каждый экземпляр приложения имеет собственный список задач.
    tasks: dict[int, Task] = {}
    next_id = 1

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
        task = Task(id=next_id, title=payload.title)
        tasks[task.id] = task
        next_id += 1
        return task

    @app.get("/tasks", response_model=list[Task], tags=["tasks"])
    async def list_tasks():
        return list(tasks.values())

    @app.get("/tasks/{task_id}", response_model=Task, tags=["tasks"])
    async def get_task(task_id: TaskId):
        return find_task(task_id)

    return app


app = create_app()
