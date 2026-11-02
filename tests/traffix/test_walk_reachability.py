"""Pedestrian reachability must match the per-edge search it replaces, using memory linear in the network."""
import os

import pytest

from traffix.demand.generator import DemandGenerator

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
TUNIS = os.path.join(ROOT, "data", "networks", "tunis_centre.net.xml")


def _search_from(gen, a, vclass):
    """The old per-edge breadth-first search, kept here as the reference answer."""
    nxt = gen._successors(vclass)
    seen, todo = {a}, [a]
    while todo:
        for n in nxt.get(todo.pop(), ()):
            if n not in seen:
                seen.add(n)
                todo.append(n)
    return seen


@pytest.mark.skipif(not os.path.exists(TUNIS), reason="Tunis network not generated")
def test_walk_component_matches_per_edge_search_on_tunis():
    gen = DemandGenerator(TUNIS)
    edges = [e for e in gen.net.getEdges(withInternal=False) if e.allows("pedestrian")][:60]
    assert edges, "expected walkable edges"
    for a in edges:
        assert gen._reachable(a, "pedestrian") == _search_from(gen, a, "pedestrian")


@pytest.mark.skipif(not os.path.exists(TUNIS), reason="Tunis network not generated")
def test_walk_components_are_shared_not_copied():
    gen = DemandGenerator(TUNIS)
    edges = [e for e in gen.net.getEdges(withInternal=False) if e.allows("pedestrian")][:200]
    sets = {id(gen._reachable(a, "pedestrian")) for a in edges}
    # one shared set per component: far fewer distinct objects than start edges
    assert len(sets) < len(edges)
