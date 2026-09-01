import json


def extract_json_object(text: str) -> dict:
    if not text:
        raise ValueError("LLM returned empty output")

    cleaned = text.strip()

    if cleaned.startswith("```"):
        cleaned = cleaned.replace("```json", "", 1)
        cleaned = cleaned.replace("```", "")
        cleaned = cleaned.strip()

    start = cleaned.find("{")
    end = cleaned.rfind("}")

    if start == -1 or end == -1:
        raise ValueError(
            "No JSON object found in LLM response"
        )

    payload = cleaned[start : end + 1]

    return json.loads(payload)