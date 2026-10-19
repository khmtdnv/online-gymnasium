"""Проверки сборки обработчиков без преждевременного открытия транзакций."""

from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from starlette.requests import Request

from journal_service.api.dependencies import (
    get_create_class_handler,
    get_list_classes_handler,
)
from journal_service.application.classes import CreateClassHandler, ListClassesHandler


@pytest.mark.parametrize(
    ("dependency", "handler_type"),
    [
        (get_create_class_handler, CreateClassHandler),
        (get_list_classes_handler, ListClassesHandler),
    ],
)
def test_dependency_returns_handler_without_opening_unit_of_work(
    dependency, handler_type
) -> None:
    """Возвращает новый обработчик и сохраняет фабрику для будущего сценария."""
    app = FastAPI()
    factory = Mock()
    app.state.uow_factory = factory
    request = Request({"type": "http", "app": app})

    first = dependency(request)
    second = dependency(request)

    assert isinstance(first, handler_type)
    assert first is not second
    assert first._uow_factory is factory
    factory.assert_not_called()
