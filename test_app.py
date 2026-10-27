"""Проверки API, ошибок, настроек и безопасных диагностических логов."""

import logging

from fastapi.testclient import TestClient
import pytest


@pytest.fixture(autouse=True)
def default_environment(monkeypatch):
    """Локальный .env и настройки компьютера не меняют результаты тестов."""
    monkeypatch.setenv("APP_NAME", "Study Tasks API")
    monkeypatch.setenv("MAX_TASKS", "100")
    monkeypatch.setenv("LOG_LEVEL", "INFO")


@pytest.fixture
def app_factory():
    # Импорт после установки переменных: модуль также создаёт приложение.
    from app_final import create_app

    return create_app


@pytest.fixture
def client(app_factory):
    with TestClient(app_factory()) as test_client:
        yield test_client


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_version(client):
    response = client.get("/version")
    assert response.status_code == 200
    assert response.json() == {"version": "1.0.0"}


def test_docs_and_root(client):
    assert client.get("/").json() == {"name": "Study Tasks API", "docs": "/docs"}
    response = client.get("/docs")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "/tasks" in client.get("/openapi.json").json()["paths"]


def test_create_list_and_get_task(client):
    assert client.get("/tasks").json() == []
    response = client.post("/tasks", json={"title": "Повторить Git"})
    expected = {"id": 1, "title": "Повторить Git", "completed": False}
    assert response.status_code == 201
    assert response.json() == expected
    assert client.get("/tasks").json() == [expected]
    assert client.get("/tasks/1").json() == expected


def test_title_is_trimmed(client):
    response = client.post("/tasks", json={"title": "  Изучить FastAPI \n"})
    assert response.status_code == 201
    assert response.json()["title"] == "Изучить FastAPI"


@pytest.mark.parametrize("title", ["", " \n\t", "a" * 121, None, 123])
def test_invalid_title_is_rejected(client, title):
    assert client.post("/tasks", json={"title": title}).status_code == 422
    assert client.get("/tasks").json() == []


@pytest.mark.parametrize("payload", [{}, {"title": "Задача", "secret": "value"}])
def test_missing_title_or_extra_field_is_rejected(client, payload):
    assert client.post("/tasks", json=payload).status_code == 422


@pytest.mark.parametrize("method", ["get", "patch", "delete"])
def test_unknown_task_returns_404(client, method):
    kwargs = {"json": {"completed": True}} if method == "patch" else {}
    response = client.request(method, "/tasks/999", **kwargs)
    assert response.status_code == 404
    assert response.json() == {"detail": "Задача не найдена"}


@pytest.mark.parametrize("task_id", ["0", "-1", "not-a-number"])
def test_invalid_task_id_returns_422(client, task_id):
    assert client.get(f"/tasks/{task_id}").status_code == 422


@pytest.mark.parametrize("completed", ["true", "false", 0, 1, None])
def test_completed_requires_json_boolean(client, completed):
    client.post("/tasks", json={"title": "Задача"})
    response = client.patch("/tasks/1", json={"completed": completed})
    assert response.status_code == 422
    assert client.get("/tasks/1").json()["completed"] is False


def test_filter_by_completion_and_empty_result(client):
    client.post("/tasks", json={"title": "Первая"})
    client.post("/tasks", json={"title": "Вторая"})
    assert client.get("/tasks?completed=true").json() == []
    assert client.patch("/tasks/1", json={"completed": True}).status_code == 200
    assert [task["id"] for task in client.get("/tasks?completed=true").json()] == [1]
    assert [task["id"] for task in client.get("/tasks?completed=false").json()] == [2]
    assert len(client.get("/tasks").json()) == 2
    assert client.get("/tasks?completed=maybe").status_code == 422


def test_update_delete_and_ids_are_not_reused(client):
    first = client.post("/tasks", json={"title": "Первая"}).json()
    second = client.post("/tasks", json={"title": "Вторая"}).json()
    response = client.patch(f"/tasks/{second['id']}", json={"completed": True})
    assert response.json() == {**second, "completed": True}
    response = client.patch(f"/tasks/{second['id']}", json={"completed": False})
    assert response.json()["completed"] is False
    deleted = client.delete(f"/tasks/{second['id']}")
    assert deleted.status_code == 204
    assert deleted.content == b""
    assert client.get(f"/tasks/{second['id']}").status_code == 404
    third = client.post("/tasks", json={"title": "Третья"}).json()
    assert first["id"] < second["id"] < third["id"]
    assert [task["id"] for task in client.get("/tasks").json()] == [1, 3]


def test_stats_follow_task_changes(client):
    assert client.get("/stats").json() == {"total": 0, "completed": 0, "pending": 0}
    client.post("/tasks", json={"title": "Первая"})
    client.post("/tasks", json={"title": "Вторая"})
    client.patch("/tasks/1", json={"completed": True})
    assert client.get("/stats").json() == {"total": 2, "completed": 1, "pending": 1}
    client.delete("/tasks/1")
    assert client.get("/stats").json() == {"total": 1, "completed": 0, "pending": 1}


def test_environment_name_and_capacity(monkeypatch, app_factory):
    monkeypatch.setenv("APP_NAME", "Учебный план")
    monkeypatch.setenv("MAX_TASKS", "1")
    with TestClient(app_factory()) as client:
        assert client.get("/").json()["name"] == "Учебный план"
        assert client.post("/tasks", json={"title": "Первая"}).status_code == 201
        response = client.post("/tasks", json={"title": "Вторая"})
        assert response.status_code == 409
        assert response.json() == {"detail": "Достигнут лимит задач"}
        assert len(client.get("/tasks").json()) == 1
        assert client.delete("/tasks/1").status_code == 204
        replacement = client.post("/tasks", json={"title": "Новая"})
        assert replacement.status_code == 201
        assert replacement.json()["id"] == 2


@pytest.mark.parametrize(
    "name,value",
    [("APP_NAME", " "), ("MAX_TASKS", "0"), ("MAX_TASKS", "-1"),
     ("MAX_TASKS", "many"), ("MAX_TASKS", ""), ("LOG_LEVEL", "UNKNOWN")],
)
def test_invalid_configuration_fails_clearly(monkeypatch, app_factory, name, value):
    monkeypatch.setenv(name, value)
    with pytest.raises(ValueError, match=name):
        app_factory()


def test_application_instances_have_independent_state(app_factory):
    with TestClient(app_factory()) as first, TestClient(app_factory()) as second:
        first.post("/tasks", json={"title": "Только в первом"})
        assert second.get("/tasks").json() == []
        response = second.post("/tasks", json={"title": "Только во втором"})
        assert response.json()["id"] == 1
        assert first.get("/tasks/1").json()["title"] == "Только в первом"


def test_logs_include_events_but_not_user_content(caplog, app_factory):
    marker = "private-task-marker"
    with caplog.at_level(logging.INFO, logger="study_tasks"):
        with TestClient(app_factory()) as client:
            client.post("/tasks", json={"title": marker})
            client.get(f"/tasks/1?note={marker}", headers={"X-Private": marker})
            client.get(f"/{marker}")
    messages = "\n".join(
        record.getMessage() for record in caplog.records if record.name == "study_tasks"
    )
    assert "Application started" in messages
    assert "Application stopped" in messages
    assert "Task created id=1" in messages
    assert "method=POST route=/tasks status=201" in messages
    assert "method=GET route=/tasks/{task_id} status=200" in messages
    assert "route=unmatched status=404" in messages
    assert marker not in messages
