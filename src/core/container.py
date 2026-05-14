from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

T = TypeVar("T")

_LifecycleHook = Callable[[], Awaitable[None]]


class ServiceContainer:
    """
    Explicit DI container. No magic — register instances, get them by type.
    Lifecycle hooks run in registration order on startup, reversed on shutdown.
    """

    def __init__(self) -> None:
        self._services: dict[type, Any] = {}
        self._startup_hooks: list[_LifecycleHook] = []
        self._shutdown_hooks: list[_LifecycleHook] = []

    def register(self, service_type: type[T], instance: T) -> None:
        self._services[service_type] = instance

    def get(self, service_type: type[T]) -> T:
        instance = self._services.get(service_type)
        if instance is None:
            raise KeyError(f"Service not registered: {service_type.__name__}")
        return instance

    def on_startup(self, hook: _LifecycleHook) -> None:
        self._startup_hooks.append(hook)

    def on_shutdown(self, hook: _LifecycleHook) -> None:
        self._shutdown_hooks.append(hook)

    async def startup(self) -> None:
        for hook in self._startup_hooks:
            await hook()

    async def shutdown(self) -> None:
        for hook in reversed(self._shutdown_hooks):
            await hook()


_container: ServiceContainer | None = None


def get_container() -> ServiceContainer:
    global _container
    if _container is None:
        _container = ServiceContainer()
    return _container
