"""Linear graph: load_targets → process_targets → END.

The fan-out/parallelism is INSIDE process_targets via asyncio.gather. Keeping
it inside the node (rather than as separate LangGraph nodes per target) means
LangGraph's state reducers don't have to manage N parallel writes — they get
one consolidated batch update at the end."""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from outreach.nodes import load_targets, process_targets
from outreach.state import OutreachState


def build_graph():
    g: StateGraph = StateGraph(OutreachState)
    g.add_node("load_targets", load_targets)
    g.add_node("process_targets", process_targets)
    g.add_edge(START, "load_targets")
    g.add_edge("load_targets", "process_targets")
    g.add_edge("process_targets", END)
    return g
