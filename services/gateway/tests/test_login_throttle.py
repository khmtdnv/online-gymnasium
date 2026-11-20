"""Тесты ограничения частоты неудачных входов."""

from gateway_service.infrastructure.login_throttle import LoginThrottle


def test_blocks_only_after_limit_inside_window() -> None:
    throttle = LoginThrottle(max_failures=3, window_seconds=900)

    for _ in range(3):
        throttle.register_failure("student@example.com")

    assert throttle.is_blocked("student@example.com")
    assert 0 < throttle.retry_after_seconds("student@example.com") <= 900
    assert not throttle.is_blocked("other@example.com")


def test_success_resets_failures() -> None:
    throttle = LoginThrottle(max_failures=3, window_seconds=900)

    throttle.register_failure("student@example.com")
    throttle.register_failure("student@example.com")
    throttle.reset("student@example.com")

    assert not throttle.is_blocked("student@example.com")
    assert throttle.retry_after_seconds("student@example.com") == 0


def test_old_failures_expire_inside_window() -> None:
    throttle = LoginThrottle(max_failures=2, window_seconds=100)
    now = 1000.0

    throttle._failures["student@example.com"] = [now - 200, now - 150]

    assert not throttle.is_blocked("student@example.com")
    assert throttle._failures.get("student@example.com") is None
