"""What each node type does with the text that flows into it."""

import httpx

from studio.config import get_settings


class RunError(Exception):
    """A problem with the workflow itself; shown to the user as the run's error."""


def run_template(template: str, text: str) -> str:
    # Plain replacement, not str.format(): braces in user text can't break it.
    return template.replace("{input}", text)


def llm_complete(prompt: str, model: str | None) -> str:
    """One call to OpenAI's Responses API."""
    settings = get_settings()
    if not settings.openai_api_key:
        raise RunError("an llm node needs OPENAI_API_KEY on the server")
    response = httpx.post(
        "https://api.openai.com/v1/responses",
        headers={"Authorization": f"Bearer {settings.openai_api_key}"},
        json={"model": model or settings.openai_model, "input": prompt, "store": False},
        timeout=60,
    )
    if response.status_code != 200:
        raise RunError(f"the model call failed ({response.status_code})")
    parts = [
        c["text"]
        for item in response.json().get("output", [])
        if item.get("type") == "message"
        for c in item.get("content", [])
        if c.get("type") == "output_text"
    ]
    return "".join(parts)
