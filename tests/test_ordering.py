# tests/test_ordering.py

"""Tests for the generic constraint-based ordering logic."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from commamatrix.core.classes.ordering import (
    CyclicConstraintError,
    normalize_constraint_refs,
    resolve_order,
)


@dataclass
class Item:
    name: str
    priority: int = 0
    _before: tuple[str, ...] = ()
    _after: tuple[str, ...] = ()

    @property
    def aliases(self) -> tuple[str, ...]:
        return (self.name,)


def _names(items: list[Item]) -> list[str]:
    return [i.name for i in items]


# ---------------------------------------------------------------------------
# normalize_constraint_refs
# ---------------------------------------------------------------------------


class TestNormalizeConstraintRefs:
    def test_none_returns_empty(self):
        assert normalize_constraint_refs(None) == ()

    def test_string_returns_tuple(self):
        assert normalize_constraint_refs("foo") == ("foo",)

    def test_callable_returns_name(self):
        def my_hook(): ...
        assert normalize_constraint_refs(my_hook) == ("my_hook",)

    def test_list_of_strings(self):
        assert normalize_constraint_refs(["a", "b"]) == ("a", "b")

    def test_mixed_list(self):
        def handler(): ...
        assert normalize_constraint_refs(["a", handler]) == ("a", "handler")

    def test_callable_without_name_raises(self):
        from functools import partial

        with pytest.raises(TypeError, match="__name__"):
            normalize_constraint_refs(partial(lambda: None))

    def test_unsupported_type_raises(self):
        with pytest.raises(TypeError):
            normalize_constraint_refs(42)

    def test_nested_iterable_raises(self):
        with pytest.raises(TypeError):
            normalize_constraint_refs([["a"], ["b", "c"]])


# ---------------------------------------------------------------------------
# resolve_order — basic cases
# ---------------------------------------------------------------------------


class TestResolveOrderBasic:
    def test_empty_list(self):
        assert resolve_order([], aliases=lambda i: (), priority=lambda i: 0, before=lambda i: (), after=lambda i: ()) == []

    def test_single_item(self):
        item = Item("a")
        result = resolve_order([item], aliases=lambda i: (i.name,), priority=lambda i: i.priority, before=lambda i: (), after=lambda i: ())
        assert result == [item]

    def test_no_constraints_priority_descending(self):
        items = [Item("a", 1), Item("b", 3), Item("c", 2)]
        result = resolve_order(items, aliases=lambda i: (i.name,), priority=lambda i: i.priority, before=lambda i: (), after=lambda i: ())
        assert _names(result) == ["b", "c", "a"]

    def test_equal_priority_preserves_original_order(self):
        items = [Item("a"), Item("b"), Item("c")]
        result = resolve_order(items, aliases=lambda i: (i.name,), priority=lambda i: i.priority, before=lambda i: (), after=lambda i: ())
        assert _names(result) == ["a", "b", "c"]


# ---------------------------------------------------------------------------
# resolve_order — before/after constraints
# ---------------------------------------------------------------------------


class TestResolveOrderConstraints:
    def test_before_pulls_forward(self):
        items = [Item("a", 10), Item("b", 0, _before=("a",))]
        result = resolve_order(
            items,
            aliases=lambda i: (i.name,),
            priority=lambda i: i.priority,
            before=lambda i: i._before,
            after=lambda i: i._after,
        )
        assert _names(result) == ["b", "a"]

    def test_after_pushes_back(self):
        items = [Item("a", 0, _after=("b",)), Item("b", 10)]
        result = resolve_order(
            items,
            aliases=lambda i: (i.name,),
            priority=lambda i: i.priority,
            before=lambda i: i._before,
            after=lambda i: i._after,
        )
        assert _names(result) == ["b", "a"]

    def test_constraint_overrides_priority(self):
        items = [
            Item("a", 100, _after=("b",)),
            Item("b", 0),
        ]
        result = resolve_order(
            items,
            aliases=lambda i: (i.name,),
            priority=lambda i: i.priority,
            before=lambda i: i._before,
            after=lambda i: i._after,
        )
        assert _names(result) == ["b", "a"]

    def test_transitive_chain(self):
        items = [
            Item("a", 0, _before=("b",)),
            Item("b", 0, _before=("c",)),
            Item("c", 0),
        ]
        result = resolve_order(
            items,
            aliases=lambda i: (i.name,),
            priority=lambda i: i.priority,
            before=lambda i: i._before,
            after=lambda i: i._after,
        )
        assert _names(result) == ["a", "b", "c"]

    def test_many_after_same_target_ordered_by_priority(self):
        items = [
            Item("a", 5, _after=("x",)),
            Item("b", 10, _after=("x",)),
            Item("x", 0),
        ]
        result = resolve_order(
            items,
            aliases=lambda i: (i.name,),
            priority=lambda i: i.priority,
            before=lambda i: i._before,
            after=lambda i: i._after,
        )
        assert _names(result) == ["x", "b", "a"]

    def test_unknown_reference_ignored(self):
        items = [Item("a", 0, _before=("nonexistent",)), Item("b", 10)]
        result = resolve_order(
            items,
            aliases=lambda i: (i.name,),
            priority=lambda i: i.priority,
            before=lambda i: i._before,
            after=lambda i: i._after,
        )
        assert _names(result) == ["b", "a"]

    def test_self_reference_ignored(self):
        items = [Item("a", 0, _before=("a",)), Item("b", 5)]
        result = resolve_order(
            items,
            aliases=lambda i: (i.name,),
            priority=lambda i: i.priority,
            before=lambda i: i._before,
            after=lambda i: i._after,
        )
        assert _names(result) == ["b", "a"]


# ---------------------------------------------------------------------------
# resolve_order — alias collisions and qualified names
# ---------------------------------------------------------------------------


class TestResolveOrderAliases:
    def test_constraint_applies_to_all_matches(self):
        items = [
            Item("a", 0, _after=("shared",)),
            Item("shared", 10),
        ]

        def aliases(i):
            if i.name == "shared":
                return ("shared",)
            return (i.name,)

        result = resolve_order(
            items,
            aliases=aliases,
            priority=lambda i: i.priority,
            before=lambda i: i._before,
            after=lambda i: i._after,
        )
        assert _names(result) == ["shared", "a"]

    def test_qualified_name_targets_specific_item(self):
        items = [
            Item("a", 0, _before=("mod.hook_b",)),
            Item("b", 10),
        ]

        def aliases(i):
            if i.name == "b":
                return ("b", "mod.hook_b")
            return (i.name,)

        result = resolve_order(
            items,
            aliases=aliases,
            priority=lambda i: i.priority,
            before=lambda i: i._before,
            after=lambda i: i._after,
        )
        assert _names(result) == ["a", "b"]


# ---------------------------------------------------------------------------
# resolve_order — cycle detection
# ---------------------------------------------------------------------------


class TestResolveOrderCycles:
    def test_direct_cycle(self):
        items = [
            Item("a", 0, _before=("b",)),
            Item("b", 0, _before=("a",)),
        ]
        with pytest.raises(CyclicConstraintError, match="a -> b -> a|b -> a -> b"):
            resolve_order(
                items,
                aliases=lambda i: (i.name,),
                priority=lambda i: i.priority,
                before=lambda i: i._before,
                after=lambda i: i._after,
            )

    def test_long_cycle(self):
        items = [
            Item("a", 0, _before=("b",)),
            Item("b", 0, _before=("c",)),
            Item("c", 0, _before=("a",)),
        ]
        with pytest.raises(CyclicConstraintError, match="a -> b -> c -> a"):
            resolve_order(
                items,
                aliases=lambda i: (i.name,),
                priority=lambda i: i.priority,
                before=lambda i: i._before,
                after=lambda i: i._after,
            )

    def test_compatible_before_after_no_cycle(self):
        """before on A and after on B that agree (both A->B) don't form a cycle."""
        items = [
            Item("a", 0, _before=("b",)),
            Item("b", 0, _after=("a",)),
        ]
        result = resolve_order(
            items,
            aliases=lambda i: (i.name,),
            priority=lambda i: i.priority,
            before=lambda i: i._before,
            after=lambda i: i._after,
        )
        assert _names(result) == ["a", "b"]

    def test_cycle_error_has_names(self):
        items = [
            Item("x", 0, _before=("y",)),
            Item("y", 0, _before=("x",)),
        ]
        with pytest.raises(CyclicConstraintError) as exc_info:
            resolve_order(
                items,
                aliases=lambda i: (i.name,),
                priority=lambda i: i.priority,
                before=lambda i: i._before,
                after=lambda i: i._after,
            )
        assert "x" in exc_info.value.cycle
        assert "y" in exc_info.value.cycle
