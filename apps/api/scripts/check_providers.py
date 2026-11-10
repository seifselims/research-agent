"""Smoke test: make one small LiteLLM call to each configured model.

Run from apps/api:
    uv run python scripts/check_providers.py

Exits with code 1 if any call fails, so it can also run in CI later.
"""

import asyncio
import sys
import time

import litellm

from api.config import get_settings

PROMPT = "Reply with exactly: OK"


async def check_chat(label: str, model: str, api_key: str) -> bool:
    start = time.perf_counter()
    try:
        response = await litellm.acompletion(
            model=model,
            api_key=api_key,
            messages=[{"role": "user", "content": PROMPT}],
            max_tokens=200,
            timeout=60,
            num_retries=2,  # retry short outages such as 503 "high demand"
        )
    except Exception as error:  # report every failure instead of stopping at the first
        print(f"FAIL  {label:<10} {model}\n      {type(error).__name__}: {error}")
        return False

    seconds = time.perf_counter() - start
    reply = (response.choices[0].message.content or "").strip()
    tokens = response.usage.total_tokens if response.usage else "?"
    print(f"OK    {label:<10} {model}  {seconds:.1f}s  {tokens} tokens  reply={reply!r}")
    return True


async def check_embedding(model: str, api_key: str, dimensions: int) -> bool:
    start = time.perf_counter()
    try:
        response = await litellm.aembedding(
            model=model,
            api_key=api_key,
            input=["DeepScout provider check"],
            dimensions=dimensions,
            timeout=60,
            num_retries=2,  # retry short outages such as 503 "high demand"
        )
    except Exception as error:
        print(f"FAIL  {'embedding':<10} {model}\n      {type(error).__name__}: {error}")
        return False

    seconds = time.perf_counter() - start
    size = len(response.data[0]["embedding"])
    if size != dimensions:
        print(f"FAIL  {'embedding':<10} {model}  got {size} dimensions, expected {dimensions}")
        return False
    print(f"OK    {'embedding':<10} {model}  {seconds:.1f}s  {size} dimensions")
    return True


async def main() -> int:
    settings = get_settings()
    results = await asyncio.gather(
        check_chat("main", settings.llm_main_model, settings.api_key_for(settings.llm_main_model)),
        check_chat("fast", settings.llm_fast_model, settings.api_key_for(settings.llm_fast_model)),
        check_embedding(
            settings.embedding_model,
            settings.api_key_for(settings.embedding_model),
            settings.embedding_dimensions,
        ),
    )
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
