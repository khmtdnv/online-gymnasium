"""WebSocket не открывает чужую историю и перепроверяет класс перед записью."""

import asyncio
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from test_auth import make_fakes

from gateway_service.domain.user import Role


def pen_app():
    from gateway_service.api.pen import router

    app = FastAPI()
    uow, tokens = make_fakes()
    app.state.uow_factory = lambda: uow
    app.state.token_service = tokens
    app.state.settings = SimpleNamespace(
        public_origin="http://localhost:8080", enforce_tuition_access=False
    )
    app.state.schedule_client = SimpleNamespace(
        get_lesson=AsyncMock(
            return_value=SimpleNamespace(
                id=1, class_id=7, teacher_id=uuid4(), status="planned"
            )
        )
    )
    app.state.journal_client = SimpleNamespace(
        get_current_class_id=AsyncMock(return_value=7)
    )
    app.state.pen_client = SimpleNamespace(
        history=AsyncMock(return_value=[]), append=AsyncMock()
    )
    app.include_router(router)
    return app, uow.users.user


def test_access_checks_both_user_identity_and_authoritative_class():
    from gateway_service.api.pen import check_pen_access

    app, user = pen_app()

    async def run():
        await check_pen_access(app, user, 1, user.id)
        with pytest.raises(HTTPException) as error:
            await check_pen_access(app, user, 1, uuid4())
        assert error.value.status_code == 403
        app.state.journal_client.get_current_class_id.return_value = 8
        with pytest.raises(HTTPException) as error:
            await check_pen_access(app, user, 1, user.id)
        assert error.value.status_code == 403
        app.state.journal_client.get_current_class_id.return_value = 7
        teacher = replace(user, role=Role.TEACHER)
        with pytest.raises(HTTPException):
            await check_pen_access(app, teacher, 1, uuid4())
        app.state.schedule_client.get_lesson.return_value.teacher_id = teacher.id
        await check_pen_access(app, teacher, 1, uuid4())
        app.state.schedule_client.get_lesson.return_value.status = "canceled"
        with pytest.raises(HTTPException):
            await check_pen_access(app, teacher, 1, uuid4())

    asyncio.run(run())


def test_websocket_rejects_origin_auth_and_write_after_transfer():
    app, user = pen_app()
    path = f"/api/v1/pen/lessons/1/students/{user.id}"
    with TestClient(app) as client:
        with (
            pytest.raises(WebSocketDisconnect),
            client.websocket_connect(path, headers={"origin": "https://evil.test"}),
        ):
            pass
        with (
            pytest.raises(WebSocketDisconnect),
            client.websocket_connect(
                path, headers={"origin": "http://localhost:8080"}
            ) as ws,
        ):
            ws.send_json({"access_token": "bad", "after": 0})
            ws.receive_json()
        app.state.pen_client.history.assert_not_awaited()
        with client.websocket_connect(
            path, headers={"origin": "http://localhost:8080"}
        ) as ws:
            ws.send_json({"access_token": "valid-access-token", "after": 0})
            assert ws.receive_json() == {"type": "ready", "after": 0}
            app.state.journal_client.get_current_class_id.return_value = 8
            ws.send_json(
                {
                    "batch_id": str(uuid4()),
                    "sequence": 1,
                    "stroke_id": str(uuid4()),
                    "points": [{"x": 0.1, "y": 0.1}],
                    "finished": True,
                }
            )
            with pytest.raises(WebSocketDisconnect):
                ws.receive_json()
        app.state.pen_client.append.assert_not_awaited()


def test_role_change_does_not_keep_student_write_permission():
    from gateway_service.application.pen import SavedPenBatch

    app, user = pen_app()
    path = f"/api/v1/pen/lessons/1/students/{user.id}"
    body = {
        "batch_id": str(uuid4()),
        "sequence": 1,
        "stroke_id": str(uuid4()),
        "points": [{"x": 0.1, "y": 0.1}],
        "finished": True,
    }
    app.state.pen_client.append.return_value = SavedPenBatch(**body, id=1)
    with (
        TestClient(app) as client,
        client.websocket_connect(
            path, headers={"origin": "http://localhost:8080"}
        ) as ws,
    ):
        ws.send_json({"access_token": "valid-access-token", "after": 0})
        assert ws.receive_json()["type"] == "ready"
        app.state.uow_factory().users.user = replace(user, role=Role.TEACHER)
        app.state.schedule_client.get_lesson.return_value.teacher_id = user.id
        ws.send_json(body)
        with pytest.raises(WebSocketDisconnect):
            ws.receive_json()
