"""LangGraphHost — the LangGraph-in-Bone spike adapter (docs/idea/17 clause 2).

Drives a REAL LangGraph `StateGraph` — a genuine loop with a model node and an
iteration edge — against the harness's four probes. This is deliberately the
shape a Bone `loop-driver` would take: LangGraph imported as a library into an
existing Python process, no daemon, no port, no checkpointer.

Where the callbacks live, and why. LangGraph's own mechanism for "policy that
can stop the run before the model is reached" is a NODE on the path to the
model node — the same shape as `Runner.php:495` putting `assertSessionCeiling`
ahead of every send. So the graph is:

    START → boundary → gate → model ─┬→ boundary   (iteration edge)
                                     └→ END        (when turn == max)

  * `boundary` runs the harness's `before_iteration` — the top-of-iteration
    seam (`Runner.php:681`).
  * `gate` runs `before_call` — the pre-send ceiling check (`Runner.php:495`).
  * `model` calls `FakeModel.send()` and nothing else.

A `Refusal` raised inside a node propagates out of `compiled.invoke()` because
no `retry_policy` is set — LangGraph 1.2.x retries nothing by default. The
same is true of the model's own `ModelBroke`, which is item 3: the exact
instance escapes, unretried, un-wrapped.

Spend accounting (item 4) is written by this adapter in a `finally` around
`invoke()`, from the model's own counters — the same construction as the
harness's NullHost, and the same seam Bone's ledger writer would use. The
graph's internal state is NOT the ledger: measured on 1.2.11, a run that ends
in an exception yields no final state from `invoke()` (it raises), and without
a checkpointer the partial state is unrecoverable — which is precisely why the
tally must be recorded on the way out by the caller that owns the ledger, not
by a node inside the graph.

`Ledger` and `Run` are structural twins of the harness's dataclasses, not
imports: the harness file is hyphenated (`orchestrator-acceptance.py`) and its
probes assert by attribute access (`run.ledger.tokens_in`, `run.raised`) and
by isinstance on `Refusal`/`ModelBroke` only — which are raised by the
harness's own callbacks/model and merely propagated here, so class identity
is preserved where it is checked.

Runs with the isolated spike venv:

    .spike-venv/bin/python tools/orchestrator-acceptance.py --host langgraph

Under any interpreter without langgraph, `available()` returns the one-line
skip reason and never raises.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass
class Ledger:
    """Structural twin of the harness's Ledger (see module docstring)."""

    tokens_in: int = 0
    tokens_out: int = 0
    finished: bool = False
    stop_reason: str | None = None


@dataclass
class Run:
    """Structural twin of the harness's Run."""

    ledger: Ledger
    raised: BaseException | None = None


class LangGraphHost:
    """`Host`-protocol adapter driving a compiled LangGraph StateGraph."""

    name = "langgraph"

    def available(self) -> str | None:
        try:
            from langgraph.graph import StateGraph  # noqa: F401
        except Exception as exc:  # noqa: BLE001 — a skip, never a raise
            return (f"langgraph not importable ({type(exc).__name__}) — "
                    f"run via .spike-venv/bin/python")
        return None

    def provenance(self) -> str:
        """Name the exact subject of the measurement.

        Added after an undeclared langgraph in the operator's global python
        was measured by a bare harness run and passed — for a version nobody
        had chosen. Version AND path: two installs can share a version.
        """
        try:
            from importlib.metadata import distribution
            from importlib.util import find_spec

            dist = distribution("langgraph")
            spec = find_spec("langgraph")
            # `langgraph` is a NAMESPACE package and has no `__file__`, so the
            # obvious `langgraph.__file__` reports nothing. The search location
            # is the answer to "which one is this".
            where = (list(spec.submodule_search_locations or []) or
                     [str(dist.locate_file(""))])[0]
            return f"langgraph {dist.version} from {where}"
        except Exception as exc:  # noqa: BLE001
            return f"langgraph present but unreportable ({type(exc).__name__})"

    def run(
        self,
        model: Any,
        max_iterations: int,
        before_call: Callable[[int], None] | None = None,
        before_iteration: Callable[[int], None] | None = None,
    ) -> Run:
        from langgraph.graph import END, START, StateGraph
        from typing_extensions import TypedDict

        class LoopState(TypedDict):
            turn: int

        # The node/branch callables are deliberately UN-annotated: LangGraph's
        # branch-schema inference runs `get_type_hints()` on them, and under
        # `from __future__ import annotations` a method-local class like
        # LoopState is an unresolvable string forward-ref (NameError). The
        # state schema is already declared once, to StateGraph(LoopState).
        def boundary(state):
            turn = state["turn"] + 1
            if before_iteration is not None:
                before_iteration(turn)
            return {"turn": turn}

        def gate(state):
            if before_call is not None:
                before_call(state["turn"])
            return {}

        def call_model(state):
            model.send(f"turn {state['turn']}")
            return {}

        def loop_or_end(state):
            return "boundary" if state["turn"] < max_iterations else END

        graph = StateGraph(LoopState)
        graph.add_node("boundary", boundary)
        graph.add_node("gate", gate)
        graph.add_node("model", call_model)
        graph.add_edge(START, "boundary")
        graph.add_edge("boundary", "gate")
        graph.add_edge("gate", "model")
        graph.add_conditional_edges("model", loop_or_end)
        # No checkpointer: durability must be a parameter, not a requirement
        # (doc 17's one objection with bite — a mandatory checkpointer would
        # duplicate the Bone ledger).
        compiled = graph.compile()

        ledger = Ledger()
        raised: BaseException | None = None
        try:
            # 3 nodes per iteration + START; headroom over the default 25 so
            # the recursion limit never masquerades as a policy stop.
            compiled.invoke(
                {"turn": 0},
                config={"recursion_limit": 3 * max_iterations + 8},
            )
        except BaseException as exc:  # noqa: BLE001 — the point is to see everything
            raised = exc
        finally:
            # Item 4: the tally is written on the way out, whatever the way
            # out was. The graph cannot do this for us — on an exception,
            # invoke() yields no state and, checkpointer-less, the partial
            # state is gone.
            ledger.tokens_in = model.tokens_in
            ledger.tokens_out = model.tokens_out
            ledger.finished = True
            ledger.stop_reason = type(raised).__name__ if raised else "completed"
        return Run(ledger=ledger, raised=raised)
