"""LLM facade used by agents: picks the configured provider, enforces the budget, logs usage."""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

from app.integrations.llm.mock import MockLLM
from app.integrations.llm.providers import PROVIDERS, LLMConfig, LLMProvider, LLMResult
from app.integrations.registry import api_key_for, default_provider, model_config
from app.services import usage

log = logging.getLogger(__name__)


def build_llm(db: Session, task: str = "default", provider_name: str | None = None) -> tuple[LLMProvider, Any]:
    from app.integrations.registry import provider_by_name

    row = provider_by_name(db, "llm", provider_name) if provider_name else default_provider(db, "llm")
    mc = model_config(db, row, task)
    cfg = LLMConfig(
        name=row.name,
        model=mc.model_name if mc else "",
        api_key=api_key_for(row),
        base_url=row.base_url,
        params={**(row.config or {}), **((mc.params or {}) if mc else {})},
    )
    cls = PROVIDERS.get(row.name)
    return (cls(cfg) if cls else MockLLM(cfg)), mc


def generate(
    db: Session,
    *,
    task: str,
    system: str,
    prompt: str,
    context: dict[str, Any],
    expected_output_tokens: int = 2000,
    channel_id: int | None = None,
    workflow_run_id: int | None = None,
) -> LLMResult:
    provider, mc = build_llm(db, task)
    est = 0.0
    if provider.is_paid and mc:
        est = (len(system) + len(prompt)) / 4 / 1000 * mc.cost_per_1k_input + expected_output_tokens / 1000 * mc.cost_per_1k_output
        usage.guard(db, est, f"LLM {provider.name}/{task}")
    result = provider.generate_json(system, prompt, task=task, context=context)
    cost = 0.0
    if provider.is_paid and mc:
        cost = result.input_tokens / 1000 * mc.cost_per_1k_input + result.output_tokens / 1000 * mc.cost_per_1k_output
    usage.record(
        db, provider=provider.name, kind="llm", model=result.model or provider.cfg.model, task=task,
        input_tokens=result.input_tokens, output_tokens=result.output_tokens, cost_usd=round(cost, 6),
        estimated=not result.actual_usage, channel_id=channel_id, workflow_run_id=workflow_run_id,
    )
    db.commit()
    result.data.setdefault("_provider", provider.name)
    result.data.setdefault("_model", result.model or provider.cfg.model)
    return result
