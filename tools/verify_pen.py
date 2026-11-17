"""Проверяет две настоящие WS-сессии демо-ученика и его преподавателя.

Добавляет один идемпотентный демонстрационный штрих, ничего не удаляет.
Запуск из корня: poetry -C services/gateway run python ../../tools/verify_pen.py
"""

import asyncio
import json
from uuid import NAMESPACE_URL, uuid5

from create_demo_data import close_demo_sessions, load_apis, login
from websockets.asyncio.client import connect


async def bootstrap(ws, token, after=0):
    """Читает все страницы истории до подтверждения готовности."""
    await ws.send(json.dumps({"access_token": token, "after": after}))
    batches = []
    while True:
        message = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
        if message["type"] == "ready":
            return batches, message["after"]
        assert message["type"] == "batch"
        batches.append(message["batch"])


async def main():
    """Проверяет ACK, просмотр учителем и восстановление после reconnect."""
    _, _, _, public = load_apis()
    student = login(public, "student01.1@demo.og.test")
    teacher = login(public, "teacher01@demo.og.test")
    user_id = student.request("GET", "/api/v1/auth/me")["id"]
    lesson_id = 1
    assert any(
        row["id"] == user_id
        for row in teacher.request("GET", f"/api/v1/pen/lessons/{lesson_id}/students")
    )
    url = (
        public.base.replace("http://", "ws://")
        + f"/api/v1/pen/lessons/{lesson_id}/students/{user_id}"
    )
    origin = public.headers["Origin"]
    token = student.headers["Authorization"].removeprefix("Bearer ")
    teacher_token = teacher.headers["Authorization"].removeprefix("Bearer ")
    batch_id = str(uuid5(NAMESPACE_URL, f"og:pen:smoke:{lesson_id}:{user_id}"))
    async with connect(url, origin=origin, proxy=None) as sender:
        history, cursor = await bootstrap(sender, token)
        previous = next((row for row in history if row["batch_id"] == batch_id), None)
        body = {
            "batch_id": batch_id,
            "sequence": previous["sequence"] if previous else cursor + 1,
            "stroke_id": str(uuid5(NAMESPACE_URL, batch_id)),
            "points": [{"x": 0.2, "y": 0.3}, {"x": 0.4, "y": 0.5}],
            "finished": True,
        }
        async with connect(url, origin=origin, proxy=None) as viewer:
            teacher_history, _ = await bootstrap(viewer, teacher_token)
            await sender.send(json.dumps(body))
            ack = json.loads(await asyncio.wait_for(sender.recv(), timeout=10))
            assert ack["type"] == "ack" and ack["batch"]["batch_id"] == batch_id
            if not previous:
                update = json.loads(await asyncio.wait_for(viewer.recv(), timeout=10))
                assert update["type"] == "batch" and update["batch"] == ack["batch"]
            else:
                assert any(row["batch_id"] == batch_id for row in teacher_history)
            # Повтор неизвестного результата возвращает тот же ID строки.
            await sender.send(json.dumps(body))
            assert json.loads(await asyncio.wait_for(sender.recv(), timeout=10)) == ack
    async with connect(url, origin=origin, proxy=None) as restored:
        history, _ = await bootstrap(restored, token)
        assert sum(row["batch_id"] == batch_id for row in history) == 1
    print(
        "Pen live: student ACK, teacher live view, duplicate retry and reconnect history OK"
    )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    finally:
        close_demo_sessions()
