"""Provider-neutral model routing contracts."""

from dataclasses import dataclass
from typing import Protocol

_RISK_ORDER = {"low": 0, "medium": 1, "high": 2, "critical": 3}


def _risk_is_allowed(requested: str, maximum: str) -> bool:
    try:
        return _RISK_ORDER[requested] <= _RISK_ORDER[maximum]
    except KeyError as exc:
        raise ValueError(f"unsupported model risk tier: {exc.args[0]}") from exc


@dataclass(frozen=True, slots=True)
class ModelRequest:
    instruction: str
    input_text: str
    required_capabilities: tuple[str, ...]
    data_region: str
    risk_tier: str
    max_output_tokens: int


@dataclass(frozen=True, slots=True)
class ModelUsage:
    input_tokens: int
    output_tokens: int
    cost_units: int


@dataclass(frozen=True, slots=True)
class ModelResponse:
    provider: str
    model: str
    output_text: str
    usage: ModelUsage
    route_reason: str


@dataclass(frozen=True, slots=True)
class ModelRoute:
    provider: str
    model: str
    capabilities: frozenset[str]
    data_regions: frozenset[str]
    maximum_risk_tier: str
    priority: int


class ModelAdapter(Protocol):
    provider: str

    async def generate(self, model: str, request: ModelRequest) -> ModelResponse: ...


class ModelGateway:
    def __init__(self, routes: tuple[ModelRoute, ...], adapters: dict[str, ModelAdapter]) -> None:
        self._routes = routes
        self._adapters = adapters

    async def generate(self, request: ModelRequest) -> ModelResponse:
        eligible = [
            route
            for route in self._routes
            if set(request.required_capabilities).issubset(route.capabilities)
            and request.data_region in route.data_regions
            and _risk_is_allowed(request.risk_tier, route.maximum_risk_tier)
            and route.provider in self._adapters
        ]
        if not eligible:
            raise LookupError("no model route satisfies hard constraints")
        failures: list[str] = []
        for route in sorted(eligible, key=lambda candidate: candidate.priority):
            try:
                response = await self._adapters[route.provider].generate(route.model, request)
                return ModelResponse(
                    provider=response.provider,
                    model=response.model,
                    output_text=response.output_text,
                    usage=response.usage,
                    route_reason=(
                        f"eligible by capabilities, region, and risk; priority={route.priority}"
                    ),
                )
            except (
                Exception
            ) as exc:  # adapters normalize provider-specific failures at this boundary
                failures.append(f"{route.provider}:{type(exc).__name__}")
        raise RuntimeError(f"all eligible model routes failed: {', '.join(failures)}")
