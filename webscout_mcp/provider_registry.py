"""Provider Registry - unified registration, enable/disable, and health management.

The registry is the single place that knows which providers exist, what
capabilities they advertise, whether they are enabled, and how healthy they
are. The dynamic router consults the registry to select the best provider for
a given capability.

Design goals:
- One registry for both search and fetch providers (and future capabilities).
- Register / unregister / enable / disable without touching router internals.
- Health status always comes from the provider itself (ProviderHealth).
- No duplicate circuit-breaker / metrics / SLO logic here; those live in the
  router, health manager and SLO aggregator respectively (reused as-is).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from .logging_config import get_logger
from .provider_router import ProviderCapability, ProviderCostTier, ProviderRouter

log = get_logger(__name__)


class ProviderProtocol(Protocol):
    """Structural interface expected of any registered provider."""

    name: str

    async def close(self) -> None:
        raise NotImplementedError

    def get_health(self) -> Any:
        raise NotImplementedError


@dataclass
class RegisteredProvider:
    """A provider registered with the registry."""

    name: str
    provider: Any
    capabilities: set[ProviderCapability] = field(default_factory=set)
    cost_tier: ProviderCostTier = ProviderCostTier.FREE
    description: str = ""
    enabled: bool = True

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a dictionary for reports."""
        return {
            "name": self.name,
            "capabilities": sorted(c.value for c in self.capabilities),
            "cost_tier": self.cost_tier.value,
            "description": self.description,
            "enabled": self.enabled,
        }


class ProviderRegistry:
    """Unified registry for providers across all capabilities.

    Usage:
        registry = ProviderRegistry()
        registry.register(bing_provider, {ProviderCapability.SEARCH}, ProviderCostTier.FREE)
        registry.register(fetch_provider, {ProviderCapability.FETCH}, ProviderCostTier.FREE)
        best = registry.select(ProviderCapability.SEARCH)
    """

    def __init__(self, router: ProviderRouter | None = None):
        """Initialize the registry.

        Args:
            router: Optional shared ProviderRouter. If not provided, one is
                created lazily on first registration.
        """
        self._providers: dict[str, RegisteredProvider] = {}
        self.router = router

    # ------------------------------------------------------------------
    # Registration / unregistration
    # ------------------------------------------------------------------
    def register(
        self,
        provider: Any,
        capabilities: set[ProviderCapability] | None = None,
        cost_tier: ProviderCostTier = ProviderCostTier.FREE,
        description: str = "",
        enabled: bool = True,
    ) -> str:
        """Register a provider.

        Args:
            provider: Provider instance. Must expose a ``name`` attribute and
                either ``get_health()`` or ``health()`` for health reporting.
            capabilities: Set of capabilities the provider supports.
                Defaults to an empty set (must be set explicitly).
            cost_tier: Cost tier used for routing decisions.
            description: Human-readable description.
            enabled: Whether the provider starts enabled.

        Returns:
            The registered provider name.
        """
        name = getattr(provider, "name", None)
        if not name:
            raise ValueError("Provider must expose a non-empty 'name' attribute")

        caps = capabilities or set()
        self._providers[name] = RegisteredProvider(
            name=name,
            provider=provider,
            capabilities=set(caps),
            cost_tier=cost_tier,
            description=description,
            enabled=enabled,
        )

        # Ensure the router knows about this provider and its cost tier.
        if self.router is not None:
            self.router.add_provider(name, cost_tier)
            self.router.set_capabilities({n: p.capabilities for n, p in self._providers.items() if p.enabled})

        log.info("Registered provider '%s' (capabilities=%s)", name, sorted(c.value for c in caps))
        return str(name)

    def unregister(self, name: str) -> bool:
        """Remove a provider from the registry.

        Args:
            name: Provider name to remove.

        Returns:
            True if the provider was removed, False if it was not registered.
        """
        if name not in self._providers:
            return False
        del self._providers[name]
        if self.router is not None:
            self.router.metrics.pop(name, None)
            self.router.cost_tiers.pop(name, None)
            self.router.set_capabilities({n: p.capabilities for n, p in self._providers.items() if p.enabled})
        log.info("Unregistered provider '%s'", name)
        return True

    # ------------------------------------------------------------------
    # Enable / disable
    # ------------------------------------------------------------------
    def enable(self, name: str) -> bool:
        """Enable a registered provider.

        Args:
            name: Provider name.

        Returns:
            True on success, False if not registered.
        """
        if name not in self._providers:
            return False
        self._providers[name].enabled = True
        self._sync_router_capabilities()
        return True

    def disable(self, name: str) -> bool:
        """Disable a registered provider (excluded from routing).

        Args:
            name: Provider name.

        Returns:
            True on success, False if not registered.
        """
        if name not in self._providers:
            return False
        self._providers[name].enabled = False
        self._sync_router_capabilities()
        return True

    def is_enabled(self, name: str) -> bool:
        """Check whether a provider is registered and enabled."""
        entry = self._providers.get(name)
        return entry is not None and entry.enabled

    # ------------------------------------------------------------------
    # Lookup
    # ------------------------------------------------------------------
    def get(self, name: str) -> Any | None:
        """Get the provider instance by name (None if not registered)."""
        entry = self._providers.get(name)
        return entry.provider if entry else None

    def names(self) -> list[str]:
        """List all registered provider names."""
        return list(self._providers.keys())

    def enabled_names(self) -> list[str]:
        """List enabled provider names."""
        return [n for n, p in self._providers.items() if p.enabled]

    def get_providers_by_capability(self, capability: ProviderCapability) -> list[RegisteredProvider]:
        """Get all enabled providers that advertise the given capability."""
        return [p for p in self._providers.values() if p.enabled and capability in p.capabilities]

    def get_capabilities(self, name: str) -> set[ProviderCapability]:
        """Get the capabilities advertised by a provider."""
        entry = self._providers.get(name)
        return set(entry.capabilities) if entry else set()

    # ------------------------------------------------------------------
    # Routing
    # ------------------------------------------------------------------
    def select(
        self,
        capability: ProviderCapability,
        exclude: list[str] | None = None,
    ) -> str | None:
        """Select the best provider for a capability via the dynamic router.

        Args:
            capability: Required capability.
            exclude: Provider names to skip (already tried).

        Returns:
            Best provider name, or None if none available/enabled.
        """
        if self.router is None:
            # No router configured: fall back to registration order.
            for p in self.get_providers_by_capability(capability):
                if p.name not in (exclude or []):
                    return p.name
            return None
        return self.router.get_next_provider(exclude=exclude, capability=capability)

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------
    def health_report(self) -> dict[str, Any]:
        """Build a health report across all registered providers.

        Health status is read from each provider (``get_health()`` preferred,
        ``health()`` fallback) so it always reflects real provider state.

        Returns:
            Dict with registry summary and per-provider health entries.
        """
        providers: list[dict[str, Any]] = []
        unavailable = 0
        for entry in self._providers.values():
            health = self._read_provider_health(entry)

            # Merge router-level circuit state (the router owns circuit
            # breaker state for routing decisions).
            circuit_open = False
            if self.router is not None:
                metrics = self.router.metrics.get(entry.name)
                if metrics is not None:
                    circuit_open = bool(metrics.circuit_open)
            if circuit_open:
                health["circuit_open"] = True
                health["status"] = "circuit_open"

            providers.append(
                {
                    "name": entry.name,
                    "enabled": entry.enabled,
                    "capabilities": sorted(c.value for c in entry.capabilities),
                    "cost_tier": entry.cost_tier.value,
                    "health": health,
                }
            )
            if not entry.enabled or health.get("status") == "circuit_open":
                unavailable += 1

        return {
            "total_providers": len(self._providers),
            "enabled_providers": sum(1 for p in self._providers.values() if p.enabled),
            "unavailable_providers": unavailable,
            "providers": providers,
        }

    def provider_health(self, name: str) -> dict[str, Any] | None:
        """Get health for a single provider (None if not registered)."""
        entry = self._providers.get(name)
        if entry is None:
            return None
        return {
            "name": entry.name,
            "enabled": entry.enabled,
            "capabilities": sorted(c.value for c in entry.capabilities),
            "cost_tier": entry.cost_tier.value,
            "health": self._read_provider_health(entry),
        }

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _read_provider_health(self, entry: RegisteredProvider) -> dict[str, Any]:
        """Read health dict from a provider instance."""
        provider = entry.provider
        try:
            if hasattr(provider, "get_health"):
                health = provider.get_health()
            elif hasattr(provider, "health"):
                health = provider.health()
            else:
                health = None
            if hasattr(health, "to_dict"):
                return dict(health.to_dict())
            if hasattr(health, "__dict__"):
                return {k: v for k, v in vars(health).items() if not k.startswith("_")}
            if isinstance(health, dict):
                return dict(health)
            return {"status": str(health)}
        except Exception as exc:  # pragma: no cover - defensive
            log.warning("Could not read health for provider '%s': %s", entry.name, exc)
            return {"status": "unknown", "error": str(exc)}

    def _sync_router_capabilities(self) -> None:
        """Push the current enabled capability map to the router."""
        if self.router is None:
            return
        self.router.set_capabilities({n: p.capabilities for n, p in self._providers.items() if p.enabled})

    async def close_all(self) -> None:
        """Close all registered providers (best effort)."""
        for entry in self._providers.values():
            try:
                await entry.provider.close()
            except Exception as exc:  # pragma: no cover - defensive
                log.warning("Error closing provider '%s': %s", entry.name, exc)
