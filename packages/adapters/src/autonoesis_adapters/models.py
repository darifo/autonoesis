"""OpenAI, Anthropic, OpenAI-compatible, and deterministic model adapters."""

from typing import Any

from anthropic import AsyncAnthropic
from autonoesis_runtime import ModelRequest, ModelResponse, ModelUsage
from openai import AsyncOpenAI


class FakeModelAdapter:
    provider = "fake"

    def __init__(self, output: str = "deterministic model output") -> None:
        self.output = output

    async def generate(self, model: str, request: ModelRequest) -> ModelResponse:
        return ModelResponse(
            provider=self.provider,
            model=model,
            output_text=self.output,
            usage=ModelUsage(
                input_tokens=len(request.input_text.split()),
                output_tokens=len(self.output.split()),
                cost_units=0,
            ),
            route_reason="direct adapter response",
        )


class OpenAIResponsesAdapter:
    provider = "openai"

    def __init__(self, client: AsyncOpenAI) -> None:
        self._client = client

    async def generate(self, model: str, request: ModelRequest) -> ModelResponse:
        response = await self._client.responses.create(
            model=model,
            instructions=request.instruction,
            input=request.input_text,
            max_output_tokens=request.max_output_tokens,
        )
        usage: Any = response.usage
        return ModelResponse(
            provider=self.provider,
            model=model,
            output_text=response.output_text,
            usage=ModelUsage(
                input_tokens=int(usage.input_tokens if usage else 0),
                output_tokens=int(usage.output_tokens if usage else 0),
                cost_units=0,
            ),
            route_reason="direct adapter response",
        )


class OpenAICompatibleAdapter(OpenAIResponsesAdapter):
    provider = "openai-compatible"


class AnthropicMessagesAdapter:
    provider = "anthropic"

    def __init__(self, client: AsyncAnthropic) -> None:
        self._client = client

    async def generate(self, model: str, request: ModelRequest) -> ModelResponse:
        response = await self._client.messages.create(
            model=model,
            system=request.instruction,
            messages=[{"role": "user", "content": request.input_text}],
            max_tokens=request.max_output_tokens,
        )
        output = "".join(
            str(getattr(block, "text", ""))
            for block in response.content
            if getattr(block, "type", "") == "text"
        )
        return ModelResponse(
            provider=self.provider,
            model=model,
            output_text=output,
            usage=ModelUsage(
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
                cost_units=0,
            ),
            route_reason="direct adapter response",
        )
