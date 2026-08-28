"""Tests for architecture module (event bus, DI, middleware, commands)."""

import asyncio

import pytest

from webscout_mcp.architecture import (
    Command,
    CommandBus,
    DIContainer,
    Event,
    EventBus,
    MiddlewarePipeline,
    ServiceLocator,
    di_container,
    event_bus,
    get_service,
    publish_event,
    register_service,
    subscribe_event,
)

# ============ Event Tests ============


class TestEvent:
    """Test Event class."""

    def test_creation(self):
        event = Event(name="test.event", data={"key": "value"})
        assert event.name == "test.event"
        assert event.data["key"] == "value"
        assert event.timestamp > 0
        assert len(event.event_id) == 8

    def test_to_dict(self):
        event = Event(name="test", data={"key": "value"}, source="test_source")
        data = event.to_dict()
        assert data["name"] == "test"
        assert data["source"] == "test_source"
        assert "event_id" in data


# ============ Event Bus Tests ============


class TestEventBus:
    """Test EventBus class."""

    def test_creation(self):
        bus = EventBus()
        assert bus is not None

    def test_subscribe_and_publish(self):
        bus = EventBus()
        received = []

        def handler(event):
            received.append(event)

        bus.subscribe("test.event", handler)
        bus.publish("test.event", data={"key": "value"})

        assert len(received) == 1
        assert received[0].name == "test.event"
        assert received[0].data["key"] == "value"

    def test_publish_event_object(self):
        bus = EventBus()
        received = []

        def handler(event):
            received.append(event)

        bus.subscribe("test.event", handler)
        event = Event(name="test.event", data={"key": "value"})
        bus.publish(event)

        assert len(received) == 1
        assert received[0] is event

    def test_multiple_handlers(self):
        bus = EventBus()
        received1 = []
        received2 = []

        bus.subscribe("test.event", lambda e: received1.append(e))
        bus.subscribe("test.event", lambda e: received2.append(e))
        bus.publish("test.event")

        assert len(received1) == 1
        assert len(received2) == 1

    def test_unsubscribe(self):
        bus = EventBus()
        received = []

        def handler(event):
            received.append(event)

        bus.subscribe("test.event", handler)
        bus.publish("test.event")
        assert len(received) == 1

        bus.unsubscribe("test.event", handler)
        bus.publish("test.event")
        assert len(received) == 1  # Still 1, handler was unsubscribed

    def test_on_decorator(self):
        bus = EventBus()
        received = []

        @bus.on("decorator.event")
        def handler(event):
            received.append(event)

        bus.publish("decorator.event")
        assert len(received) == 1

    def test_async_publish(self):
        bus = EventBus()
        received = []

        async def async_handler(event):
            received.append(event)

        def sync_handler(event):
            received.append(event)

        bus.subscribe_async("async.event", async_handler)
        bus.subscribe("async.event", sync_handler)

        asyncio.run(bus.publish_async("async.event"))
        assert len(received) == 2

    def test_event_history(self):
        bus = EventBus()
        bus.publish("event1")
        bus.publish("event2")
        bus.publish("event1")

        history = bus.get_event_history()
        assert len(history) == 3

        history_filtered = bus.get_event_history(event_name="event1")
        assert len(history_filtered) == 2

    def test_clear_history(self):
        bus = EventBus()
        bus.publish("event1")
        assert len(bus.get_event_history()) == 1
        bus.clear_history()
        assert len(bus.get_event_history()) == 0

    def test_get_stats(self):
        bus = EventBus()
        bus.subscribe("test.event", lambda e: None)
        bus.publish("test.event")
        stats = bus.get_stats()
        assert stats["total_events_published"] == 1
        assert "test.event" in stats["sync_handlers"]

    def test_global_event_bus(self):
        assert event_bus is not None
        assert isinstance(event_bus, EventBus)


# ============ DI Container Tests ============


class TestDIContainer:
    """Test DIContainer class."""

    def test_creation(self):
        container = DIContainer()
        assert container is not None

    def test_register_singleton_instance(self):
        container = DIContainer()

        class Service:
            pass

        instance = Service()
        container.register_singleton(Service, instance)
        resolved = container.resolve(Service)
        assert resolved is instance

    def test_register_singleton_class(self):
        container = DIContainer()

        class Service:
            pass

        container.register_singleton(Service, Service)
        resolved1 = container.resolve(Service)
        resolved2 = container.resolve(Service)
        assert resolved1 is resolved2  # Same instance (singleton)

    def test_register_transient(self):
        container = DIContainer()

        class Service:
            pass

        container.register_transient(Service, Service)
        resolved1 = container.resolve(Service)
        resolved2 = container.resolve(Service)
        assert resolved1 is not resolved2  # Different instances (transient)

    def test_register_named_instance(self):
        container = DIContainer()
        instance = {"key": "value"}
        container.register_instance("config", instance)
        resolved = container.resolve_named("config")
        assert resolved is instance

    def test_resolve_not_registered(self):
        container = DIContainer()

        class Unregistered:
            pass

        with pytest.raises(KeyError):
            container.resolve(Unregistered)

    def test_is_registered(self):
        container = DIContainer()

        class Service:
            pass

        assert container.is_registered(Service) is False
        container.register_singleton(Service, Service())
        assert container.is_registered(Service) is True

    def test_inject_decorator(self):
        container = DIContainer()

        class ServiceA:
            pass

        class ServiceB:
            pass

        container.register_singleton(ServiceA, ServiceA())
        container.register_singleton(ServiceB, ServiceB())

        @container.inject(ServiceA, ServiceB)
        def my_function(service_a, service_b, extra_arg):
            assert isinstance(service_a, ServiceA)
            assert isinstance(service_b, ServiceB)
            return extra_arg

        result = my_function("test")
        assert result == "test"

    def test_get_stats(self):
        container = DIContainer()
        container.register_singleton(str, "test")
        stats = container.get_stats()
        assert stats["singletons"] == 1

    def test_global_di_container(self):
        assert di_container is not None
        assert isinstance(di_container, DIContainer)


# ============ Middleware Pipeline Tests ============


class TestMiddlewarePipeline:
    """Test MiddlewarePipeline class."""

    def test_creation(self):
        pipeline = MiddlewarePipeline()
        assert pipeline is not None

    def test_execute_no_middleware(self):
        pipeline = MiddlewarePipeline()
        result = pipeline.execute("request", lambda req: f"processed:{req}")
        assert result == "processed:request"

    def test_single_middleware(self):
        pipeline = MiddlewarePipeline()

        def middleware(request, next_handler):
            modified = request + "_modified"
            response = next_handler(modified)
            return response + "_middleware"

        pipeline.use(middleware)
        result = pipeline.execute("request", lambda req: f"result:{req}")
        assert result == "result:request_modified_middleware"

    def test_multiple_middlewares(self):
        pipeline = MiddlewarePipeline()

        def middleware1(request, next_handler):
            return next_handler(request + "_1")

        def middleware2(request, next_handler):
            return next_handler(request + "_2")

        pipeline.use(middleware1)
        pipeline.use(middleware2)
        result = pipeline.execute("request", lambda req: req)
        assert result == "request_1_2"

    def test_middleware_short_circuit(self):
        pipeline = MiddlewarePipeline()

        def middleware(request, next_handler):
            return "short_circuited"

        pipeline.use(middleware)
        result = pipeline.execute("request", lambda req: "should_not_reach")
        assert result == "short_circuited"

    def test_get_stats(self):
        pipeline = MiddlewarePipeline()

        def mw1(request, next_handler):
            return next_handler(request)

        pipeline.use(mw1)
        stats = pipeline.get_stats()
        assert stats["middleware_count"] == 1


# ============ Command Pattern Tests ============


class TestCommand:
    """Test Command and CommandBus classes."""

    def test_command_base(self):
        cmd = Command()
        with pytest.raises(NotImplementedError):
            cmd.execute()

    def test_command_bus_execute(self):
        bus = CommandBus()

        class AddCommand(Command):
            def __init__(self, a, b):
                self.a = a
                self.b = b

            def execute(self):
                return self.a + self.b

        result = bus.execute(AddCommand(2, 3))
        assert result == 5

    def test_command_bus_handler(self):
        bus = CommandBus()

        class CustomCommand(Command):
            def __init__(self, value):
                self.value = value

        def handler(command):
            return f"handled:{command.value}"

        bus.register_handler(CustomCommand, handler)
        result = bus.execute(CustomCommand("test"))
        assert result == "handled:test"

    def test_command_history(self):
        bus = CommandBus()

        class TestCommand(Command):
            def execute(self):
                return "done"

        bus.execute(TestCommand())
        bus.execute(TestCommand())
        history = bus.get_history()
        assert len(history) == 2

    def test_command_clear_history(self):
        bus = CommandBus()

        class TestCommand(Command):
            def execute(self):
                return "done"

        bus.execute(TestCommand())
        bus.clear_history()
        assert len(bus.get_history()) == 0


# ============ Service Locator Tests ============


class TestServiceLocator:
    """Test ServiceLocator class."""

    def test_register_and_get(self):
        ServiceLocator.register("test_service", {"key": "value"})
        service = ServiceLocator.get("test_service")
        assert service["key"] == "value"

    def test_get_not_found(self):
        with pytest.raises(KeyError):
            ServiceLocator.get("nonexistent_service_xyz")

    def test_has(self):
        ServiceLocator.register("has_test", "value")
        assert ServiceLocator.has("has_test") is True
        assert ServiceLocator.has("nonexistent_xyz") is False

    def test_list_services(self):
        ServiceLocator.register("list_test_1", "value1")
        ServiceLocator.register("list_test_2", "value2")
        services = ServiceLocator.list_services()
        assert "list_test_1" in services
        assert "list_test_2" in services


# ============ Convenience Function Tests ============


class TestConvenienceFunctions:
    """Test convenience functions."""

    def test_publish_and_subscribe_event(self):
        received = []

        def handler(event):
            received.append(event)

        subscribe_event("convenience.test", handler)
        publish_event("convenience.test", data={"key": "value"})
        assert len(received) == 1
        assert received[0].data["key"] == "value"

    def test_register_and_get_service(self):
        register_service("conv_service", "test_value")
        service = get_service("conv_service")
        assert service == "test_value"
