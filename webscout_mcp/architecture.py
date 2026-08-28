"""Architecture module for webscout-mcp.

Provides event-driven architecture, dependency injection, and plugin system
for building extensible and maintainable applications.

Features:
- Event bus (sync + async)
- Dependency injection container
- Service locator
- Middleware pipeline
- Plugin lifecycle management
- Command pattern
- Observer pattern
"""
from __future__ import annotations
import asyncio
import inspect
from dataclasses import dataclass, field
from typing import (
    Optional, Dict, Any, List, Tuple, Callable, Type, TypeVar,
    Awaitable, Union,
)
from collections import defaultdict
from .logging import get_logger

log = get_logger(__name__)

T = TypeVar("T")


# ============ Event Bus ============

@dataclass
class Event:
    """Base event class."""
    name: str = ""
    data: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = 0.0
    source: str = ""
    event_id: str = ""

    def __post_init__(self):
        import time
        import uuid
        if not self.timestamp:
            self.timestamp = time.time()
        if not self.event_id:
            self.event_id = str(uuid.uuid4())[:8]

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "data": self.data,
            "timestamp": self.timestamp,
            "source": self.source,
            "event_id": self.event_id,
        }


class EventBus:
    """Event bus for publish-subscribe pattern.

    Supports both sync and async event handlers.
    """

    def __init__(self) -> None:
        self._handlers: Dict[str, List[Callable]] = defaultdict(list)
        self._async_handlers: Dict[str, List[Callable]] = defaultdict(list)
        self._event_history: List[Event] = []
        self._max_history: int = 1000

    def subscribe(self, event_name: str, handler: Callable) -> None:
        """Subscribe a sync handler to an event.

        Args:
            event_name: Name of the event.
            handler: Handler function (event) -> None.
        """
        self._handlers[event_name].append(handler)
        log.debug(f"Subscribed handler to event: {event_name}")

    def subscribe_async(self, event_name: str, handler: Callable[..., Awaitable]) -> None:
        """Subscribe an async handler to an event."""
        self._async_handlers[event_name].append(handler)
        log.debug(f"Subscribed async handler to event: {event_name}")

    def unsubscribe(self, event_name: str, handler: Callable) -> None:
        """Unsubscribe a handler from an event."""
        if handler in self._handlers.get(event_name, []):
            self._handlers[event_name].remove(handler)
        if handler in self._async_handlers.get(event_name, []):
            self._async_handlers[event_name].remove(handler)

    def publish(self, event: Union[Event, str], data: Optional[Dict[str, Any]] = None, source: str = "") -> Event:
        """Publish an event synchronously.

        Args:
            event: Event object or event name string.
            data: Event data (if event is a string).
            source: Event source.

        Returns:
            The published event.
        """
        if isinstance(event, str):
            event = Event(name=event, data=data or {}, source=source)

        self._event_history.append(event)
        if len(self._event_history) > self._max_history:
            self._event_history.pop(0)

        # Call sync handlers
        for handler in self._handlers.get(event.name, []):
            try:
                handler(event)
            except Exception as exc:
                log.error(f"Error in event handler for {event.name}: {exc}")

        # Note: async handlers are not called in sync publish
        if self._async_handlers.get(event.name):
            log.debug(f"Async handlers for {event.name} not called in sync publish")

        return event

    async def publish_async(self, event: Union[Event, str], data: Optional[Dict[str, Any]] = None, source: str = "") -> Event:
        """Publish an event asynchronously.

        Calls both sync and async handlers.
        """
        if isinstance(event, str):
            event = Event(name=event, data=data or {}, source=source)

        self._event_history.append(event)
        if len(self._event_history) > self._max_history:
            self._event_history.pop(0)

        # Call sync handlers
        for handler in self._handlers.get(event.name, []):
            try:
                handler(event)
            except Exception as exc:
                log.error(f"Error in event handler for {event.name}: {exc}")

        # Call async handlers
        tasks = []
        for handler in self._async_handlers.get(event.name, []):
            try:
                tasks.append(handler(event))
            except Exception as exc:
                log.error(f"Error creating async handler task for {event.name}: {exc}")

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

        return event

    def on(self, event_name: str) -> Callable:
        """Decorator to subscribe a function to an event.

        Usage:
            @bus.on("user.created")
            def handle_user_created(event):
                pass
        """
        def decorator(func):
            if inspect.iscoroutinefunction(func):
                self.subscribe_async(event_name, func)
            else:
                self.subscribe(event_name, func)
            return func
        return decorator

    def get_event_history(self, event_name: Optional[str] = None, limit: int = 100) -> List[Event]:
        """Get event history.

        Args:
            event_name: Filter by event name (optional).
            limit: Maximum number of events to return.

        Returns:
            List of events.
        """
        if event_name:
            filtered = [e for e in self._event_history if e.name == event_name]
        else:
            filtered = list(self._event_history)
        return filtered[-limit:]

    def clear_history(self) -> None:
        """Clear event history."""
        self._event_history.clear()

    def get_stats(self) -> Dict[str, Any]:
        """Get event bus statistics."""
        return {
            "total_events_published": len(self._event_history),
            "unique_event_types": len(set(e.name for e in self._event_history)),
            "sync_handlers": {name: len(handlers) for name, handlers in self._handlers.items()},
            "async_handlers": {name: len(handlers) for name, handlers in self._async_handlers.items()},
        }


# Global event bus instance
event_bus = EventBus()


# ============ Dependency Injection Container ============

class DIContainer:
    """Simple dependency injection container.

    Supports singleton and transient service registration and resolution.
    """

    def __init__(self) -> None:
        self._singletons: Dict[Type, Any] = {}
        self._factories: Dict[Type, Callable] = {}
        self._instances: Dict[Type, Any] = {}

    def register_singleton(self, interface: Type, implementation: Any) -> None:
        """Register a singleton service.

        Args:
            interface: Interface or base class.
            implementation: Implementation instance or class.
        """
        if inspect.isclass(implementation):
            self._factories[interface] = implementation
            self._singletons[interface] = None  # Will be created on first resolve
        else:
            self._singletons[interface] = implementation
        log.debug(f"Registered singleton: {interface.__name__}")

    def register_transient(self, interface: Type, factory: Callable) -> None:
        """Register a transient service (new instance each time).

        Args:
            interface: Interface or base class.
            factory: Factory function or class.
        """
        self._factories[interface] = factory
        log.debug(f"Registered transient: {interface.__name__}")

    def register_instance(self, name: str, instance: Any) -> None:
        """Register a named instance.

        Args:
            name: Instance name.
            instance: Instance to register.
        """
        self._instances[name] = instance

    def resolve(self, interface: Type) -> Any:
        """Resolve a service by interface.

        Args:
            interface: Interface or base class.

        Returns:
            Service instance.

        Raises:
            KeyError: If service is not registered.
        """
        if interface in self._singletons:
            instance = self._singletons[interface]
            if instance is None and interface in self._factories:
                # Lazy creation
                instance = self._factories[interface]()
                self._singletons[interface] = instance
            return instance

        if interface in self._factories:
            return self._factories[interface]()

        raise KeyError(f"Service not registered: {interface.__name__}")

    def resolve_named(self, name: str) -> Any:
        """Resolve a named instance.

        Args:
            name: Instance name.

        Returns:
            Instance.

        Raises:
            KeyError: If instance is not registered.
        """
        if name not in self._instances:
            raise KeyError(f"Instance not registered: {name}")
        return self._instances[name]

    def is_registered(self, interface: Type) -> bool:
        """Check if a service is registered."""
        return interface in self._singletons or interface in self._factories

    def inject(self, *interfaces: Type) -> Callable:
        """Decorator to inject dependencies into a function.

        Usage:
            @container.inject(ServiceA, ServiceB)
            def my_function(service_a, service_b):
                pass
        """
        def decorator(func):
            def wrapper(*args, **kwargs):
                resolved = [self.resolve(interface) for interface in interfaces]
                return func(*resolved, *args, **kwargs)
            return wrapper
        return decorator

    def get_stats(self) -> Dict[str, Any]:
        """Get container statistics."""
        return {
            "singletons": len(self._singletons),
            "factories": len(self._factories),
            "named_instances": len(self._instances),
        }


# Global DI container instance
di_container = DIContainer()


# ============ Middleware Pipeline ============

class MiddlewarePipeline:
    """Middleware pipeline for processing requests.

    Allows chaining multiple middleware functions that can modify
    the request, response, or short-circuit the pipeline.
    """

    def __init__(self) -> None:
        self._middlewares: List[Callable] = []

    def use(self, middleware: Callable) -> None:
        """Add a middleware to the pipeline.

        Middleware signature: (request, next) -> response
        """
        self._middlewares.append(middleware)

    def execute(self, request: Any, handler: Callable) -> Any:
        """Execute the pipeline with a final handler.

        Args:
            request: Initial request.
            handler: Final handler function.

        Returns:
            Final response.
        """
        def create_next(index: int) -> Callable:
            if index >= len(self._middlewares):
                return lambda req: handler(req)

            middleware = self._middlewares[index]
            next_handler = create_next(index + 1)
            return lambda req: middleware(req, next_handler)

        return create_next(0)(request)

    def get_stats(self) -> Dict[str, Any]:
        """Get pipeline statistics."""
        return {
            "middleware_count": len(self._middlewares),
            "middlewares": [m.__name__ for m in self._middlewares],
        }


# ============ Command Pattern ============

class Command:
    """Base command class for command pattern."""

    def execute(self, *args, **kwargs) -> Any:
        """Execute the command."""
        raise NotImplementedError

    def undo(self) -> None:
        """Undo the command (optional)."""
        pass


class CommandBus:
    """Command bus for executing and tracking commands."""

    def __init__(self) -> None:
        self._handlers: Dict[Type[Command], Callable] = {}
        self._history: List[Tuple[Command, Any]] = []

    def register_handler(self, command_type: Type[Command], handler: Callable) -> None:
        """Register a handler for a command type."""
        self._handlers[command_type] = handler

    def execute(self, command: Command) -> Any:
        """Execute a command.

        Args:
            command: Command to execute.

        Returns:
            Command result.
        """
        handler = self._handlers.get(type(command))
        if handler:
            result = handler(command)
        else:
            result = command.execute()

        self._history.append((command, result))
        return result

    def get_history(self, limit: int = 100) -> List[Tuple[Command, Any]]:
        """Get command execution history."""
        return self._history[-limit:]

    def clear_history(self) -> None:
        """Clear command history."""
        self._history.clear()


# ============ Service Locator ============

class ServiceLocator:
    """Simple service locator pattern.

    Provides a global access point for services.
    """

    _services: Dict[str, Any] = {}

    @classmethod
    def register(cls, name: str, service: Any) -> None:
        """Register a service."""
        cls._services[name] = service

    @classmethod
    def get(cls, name: str) -> Any:
        """Get a service by name."""
        if name not in cls._services:
            raise KeyError(f"Service not found: {name}")
        return cls._services[name]

    @classmethod
    def has(cls, name: str) -> bool:
        """Check if a service is registered."""
        return name in cls._services

    @classmethod
    def list_services(cls) -> List[str]:
        """List all registered services."""
        return list(cls._services.keys())


# ============ Convenience Functions ============

def publish_event(event_name: str, data: Optional[Dict[str, Any]] = None, source: str = "") -> Event:
    """Publish an event using the global event bus."""
    return event_bus.publish(event_name, data=data, source=source)


def subscribe_event(event_name: str, handler: Callable) -> None:
    """Subscribe to an event using the global event bus."""
    event_bus.subscribe(event_name, handler)


def register_service(name: str, service: Any) -> None:
    """Register a service in the global service locator."""
    ServiceLocator.register(name, service)


def get_service(name: str) -> Any:
    """Get a service from the global service locator."""
    return ServiceLocator.get(name)
