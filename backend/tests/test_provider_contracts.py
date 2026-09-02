from types import SimpleNamespace
from unittest.mock import MagicMock

from backend.app.schemas.decision import (
    CriticAnalysisOutput,
    DecisionAnalysisOutput,
)
from backend.app.services.llm.azure_provider import AzureProvider
from backend.app.services.llm.nvidia_provider import NvidiaProvider
from backend.app.services.llm import nvidia_provider as nvidia_module


class FakeResponses:
    def __init__(self):
        self.kwargs = None

    def parse(self, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace(
            output_text='{"symbol":"TEST"}',
            output_parsed=object(),
        )


class FakeCompletions:
    def __init__(self):
        self.kwargs = None

    def create(self, **kwargs):
        self.kwargs = kwargs
        message = SimpleNamespace(
            content=(
                '{"verdict":"PASS","confidence_adjustment":0.0,'
                '"thesis_consistency":0.9,"concerns":[]}'
            )
        )
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


def test_azure_requests_native_structured_output():
    provider = AzureProvider()
    responses = FakeResponses()
    provider.client = SimpleNamespace(responses=responses)

    provider.generate("prompt", response_model=DecisionAnalysisOutput)

    assert responses.kwargs["text_format"] is DecisionAnalysisOutput


def test_nvidia_requests_json_schema_and_low_reasoning():
    provider = NvidiaProvider()
    completions = FakeCompletions()
    provider.client = SimpleNamespace(
        chat=SimpleNamespace(completions=completions)
    )

    provider.generate("prompt", response_model=CriticAnalysisOutput)

    requested = completions.kwargs
    assert requested["response_format"]["type"] == "json_schema"
    assert requested["response_format"]["json_schema"]["strict"] is True
    assert requested["reasoning_effort"] == "low"


def test_nvidia_client_disables_automatic_retries(monkeypatch):
    constructor = MagicMock(return_value=MagicMock())
    monkeypatch.setattr(nvidia_module, "OpenAI", constructor)

    NvidiaProvider()

    assert constructor.call_args.kwargs["max_retries"] == 0
