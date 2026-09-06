# tests/test_model_selection.py

"""Tests for agentic_model-driven default model selection."""

from __future__ import annotations

import re
from collections.abc import Iterator

import pytest

from commamatrix.components.hook import RunCtx
from commamatrix.components.llm_adapter import Cost, LLM
from commamatrix.core.agent.agent import Agent, agentic_model
from tests.conftest import stub_origin


class _Adapter:
    def __init__(self, llms: list[LLM]) -> None:
        self.llms = llms


class _AdapterManager:
    def __init__(self, adapters: list[_Adapter]) -> None:
        self._adapters = adapters

    def iter_llms(self) -> Iterator[tuple[_Adapter, LLM]]:
        for adapter in self._adapters:
            yield from ((adapter, llm) for llm in adapter.llms)


def _make_agent(model_filter: str | re.Pattern[str], names: list[str]) -> tuple[Agent, RunCtx]:
    agent = Agent("test", config={agentic_model: model_filter}, auto_load_main=False, auto_load_plugins=False)
    llms = [
        LLM(model_name=name, cost=Cost(input_tokens=float(len(names) - index)))
        for index, name in enumerate(names)
    ]
    agent.llm_adapter = _AdapterManager([_Adapter(llms)])
    run = RunCtx(agent=agent, origin=stub_origin(), user="tester")
    return agent, run


def test_no_filter_selects_cheapest_model():
    agent, run = _make_agent("", ["expensive-model", "cheap-model"])
    agent._select_model(run)
    assert run.llm.model_name == "cheap-model"


def test_exact_string_selects_exact_model():
    agent, run = _make_agent("cheap-model", ["expensive-model", "cheap-model"])
    agent._select_model(run)
    assert run.llm.model_name == "cheap-model"


def test_string_substring_does_not_match():
    agent, run = _make_agent("cheap", ["expensive-model", "cheap-model"])
    with pytest.raises(RuntimeError, match="No LLM model matches agentic_model 'cheap'"):
        agent._select_model(run)


def test_string_no_match_raises():
    agent, run = _make_agent("missing-model", ["cheap-model"])
    with pytest.raises(RuntimeError, match="No LLM model matches agentic_model 'missing-model'"):
        agent._select_model(run)


def test_pattern_selects_first_matching_model_in_order():
    agent, run = _make_agent(re.compile(r"-model$"), ["expensive-model", "cheap-model"])
    agent._select_model(run)
    assert run.llm.model_name == "expensive-model"
    assert run.adapter is not None


def test_pattern_uses_search_semantics():
    agent, run = _make_agent(re.compile(r"^cheap"), ["expensive-model", "cheap-model"])
    agent._select_model(run)
    assert run.llm.model_name == "cheap-model"


def test_pattern_no_match_raises():
    agent, run = _make_agent(re.compile(r"nomatch"), ["cheap-model"])
    with pytest.raises(RuntimeError, match="No LLM model matches agentic_model pattern 'nomatch'"):
        agent._select_model(run)


def test_pattern_selects_across_adapters_in_order() -> None:
    agent = Agent("test", config={agentic_model: re.compile(r"beta")}, auto_load_main=False, auto_load_plugins=False)
    adapter_a = _Adapter([LLM(model_name="alpha-1")])
    adapter_b = _Adapter([LLM(model_name="beta-1"), LLM(model_name="beta-2")])
    agent.llm_adapter = _AdapterManager([adapter_a, adapter_b])
    run = RunCtx(agent=agent, origin=stub_origin(), user="tester")
    agent._select_model(run)
    assert run.llm.model_name == "beta-1"
    assert run.adapter is adapter_b
