"""Analysis-only NVIDIA Kimi smoke test; no trading client is used."""

from backend.app.schemas.decision import CriticAnalysisOutput
from backend.app.services.llm.json_utils import extract_json_object
from backend.app.services.llm.nvidia_provider import nvidia_provider


def main() -> None:
    prompt = """
You are the adversarial critic in a paper-trading research system.
Do not create, approve, reject, or execute a trade.
Return a JSON object with verdict PASS, confidence_adjustment 0.0,
thesis_consistency 1.0, and an empty concerns array.
"""
    raw = nvidia_provider.generate(
        prompt,
        response_model=CriticAnalysisOutput,
    )
    result = CriticAnalysisOutput.model_validate(extract_json_object(raw))

    print("REGRET_KIMI_OK")
    print(f"verdict={result.verdict}")
    print(f"confidence_adjustment={result.confidence_adjustment}")
    print(f"concern_count={len(result.concerns)}")
    print("structured_output=VALID")
    print("order_submitted=False")


if __name__ == "__main__":
    main()
