# core/classes/ordering.py

from __future__ import annotations

import heapq
from collections.abc import Callable, Iterable
from typing import Any, TypeVar

T = TypeVar("T")

type ConstraintRef = str | Callable[..., Any]


class CyclicConstraintError(ValueError):
    """before/after constraints form a cycle. The message contains the cycle path."""

    def __init__(self, cycle: list[str]) -> None:
        self.cycle = cycle
        path = " -> ".join(cycle)
        super().__init__(f"Cyclic before/after constraints: {path}")


def normalize_constraint_refs(refs: Any) -> tuple[str, ...]:
    """Normalize before/after values into a flat tuple of string names.

    Accepts:
        None          -> ()
        str           -> (str, )
        callable      -> (__name__, )
        iterable      -> recursively flattened (str elements kept as-is, callables converted to __name__)

    Raises TypeError on unsupported element types.
    """
    if refs is None:
        return ()
    if isinstance(refs, str):
        return (refs, )
    if callable(refs):
        name: str | None = getattr(refs, "__name__", None)
        if name is None:
            raise TypeError(f"Cannot extract __name__ from {refs!r}")
        return (name, )
    if isinstance(refs, Iterable):
        result: list[str] = []
        for item in refs:
            if isinstance(item, str):
                result.append(item)
            elif callable(item):
                name: str | None = getattr(item, "__name__", None)
                if name is None:
                    raise TypeError(f"Cannot extract __name__ from {item!r}")
                result.append(name)
            else:
                raise TypeError(f"Unsupported constraint ref type: {type(item)!r}")
        return tuple(result)
    raise TypeError(f"Unsupported constraint ref type: {type(refs)!r}")


def resolve_order(
    items: Iterable[T],
    *,
    aliases: Callable[[T], Iterable[str]],
    priority: Callable[[T], int],
    before: Callable[[T], Iterable[str]],
    after: Callable[[T], Iterable[str]],
) -> list[T]:
    """Topologically sort items respecting before/after constraints,
    breaking ties by priority (higher first) then by original order (stable).

    Constraints whose targets are not found among the items are silently
    ignored.  Self-references (an item constraining itself) are also ignored.
    Duplicate edges are deduplicated.

    Raises CyclicConstraintError if the constraints form a cycle.

    Args:
        items:    the elements to sort.
        aliases:  callable returning all names by which an item is addressable.
        priority: callable returning the numeric priority (higher = earlier).
        before:   callable returning target names this item must precede.
        after:    callable returning target names this item must follow.
    """
    items_list = list(items)
    n = len(items_list)
    if n < 2:
        return items_list

    alias_map: dict[str, list[int]] = {}
    item_aliases: list[frozenset[str]] = []
    for i, item in enumerate(items_list):
        als = frozenset(aliases(item))
        item_aliases.append(als)
        for a in als:
            alias_map.setdefault(a, []).append(i)

    edges: set[tuple[int, int]] = set()
    for i, item in enumerate(items_list):
        for ref in before(item):
            for j in alias_map.get(ref, []):
                if j != i:
                    edges.add((i, j))
        for ref in after(item):
            for j in alias_map.get(ref, []):
                if j != i:
                    edges.add((j, i))

    successors: list[list[int]] = [[] for _ in range(n)]
    indegree: list[int] = [0] * n
    for src, dst in edges:
        successors[src].append(dst)
        indegree[dst] += 1

    heap: list[tuple[int, int, int]] = []
    for i, item in enumerate(items_list):
        if indegree[i] == 0:
            heapq.heappush(heap, (-priority(item), i, i))

    result: list[T] = []
    processed = 0
    while heap:
        _, _, idx = heapq.heappop(heap)
        result.append(items_list[idx])
        processed += 1
        for succ in successors[idx]:
            indegree[succ] -= 1
            if indegree[succ] == 0:
                heapq.heappush(heap, (-priority(items_list[succ]), succ, succ))

    if processed == n:
        return result

    remaining = [i for i in range(n) if indegree[i] > 0]
    start = remaining[0]
    visited: dict[int, int] = {}
    path: list[int] = []
    node = start
    while True:
        if node in visited:
            cycle_start = visited[node]
            cycle_indices = path[cycle_start:]
            cycle_names = []
            for idx in cycle_indices:
                als = item_aliases[idx]
                cycle_names.append(next(iter(als)) if als else f"<{idx}>")
            cycle_names.append(cycle_names[0])
            raise CyclicConstraintError(cycle_names)
        visited[node] = len(path)
        path.append(node)
        next_node = None
        for succ in successors[node]:
            if indegree[succ] > 0:
                next_node = succ
                break
        if next_node is None:
            break
        node = next_node

    cycle_names = [next(iter(item_aliases[i]), f"<{i}>") for i in path]
    cycle_names.append(cycle_names[0])
    raise CyclicConstraintError(cycle_names)
