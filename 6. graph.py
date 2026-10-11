"""LangGraph orchestration of every tool call coming from the Gemini Live voice model."""
from __future__ import annotations

from typing import Any, Optional, TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from pydantic import ValidationError

from . import clinic, config
from .guardrails import INJECTION_RE
from .schemas import TOOL_MODELS


class CallState(TypedDict, total=False):
    # per tool call (reset on every invocation)
    tool: str
    args: dict
    result: dict
    blocked: bool
    trace: list
    # persists for the whole phone call
    calls_made: int
    failed_verifications: int
    pending_booking: Optional[dict]


NODE_FOR_TOOL = {
    "get_clinic_info": "info_node",
    "check_availability": "availability_node",
    "book_appointment": "booking_node",
    "lookup_appointments": "lookup_node",
    "cancel_appointment": "cancel_node",
    "reschedule_appointment": "reschedule_node",
    "request_callback": "callback_node",
    "flag_dental_emergency": "emergency_node",
}
VERIFIED_TOOLS = {"lookup_appointments", "cancel_appointment", "reschedule_appointment"}
MAX_FAILED_VERIFICATIONS = 3


def _t(state: CallState, name: str) -> list:
    return list(state.get("trace") or []) + [name]


def _blocked(state: CallState, code: str, say: str, **extra) -> dict:
    return {"blocked": True, "trace": _t(state, "guard_input"),
            "result": {"ok": False, "error": code, "say": say, **extra}}


# ---- guard_input
def guard_input(state: CallState) -> dict:
    tool = state.get("tool", "")
    raw = state.get("args") or {}
    calls = int(state.get("calls_made", 0)) + 1

    if tool not in TOOL_MODELS:                                  # 1. allow-list
        return _blocked(state, "unknown_tool", "That action isn't available. Carry on without it.")
    if calls > config.MAX_TOOL_CALLS_PER_CALL:                   # 2. runaway / abuse cap
        return _blocked(state, "tool_budget_exceeded",
                        "Too many actions on this call. Offer to have the front desk call the caller back.")
    if tool in VERIFIED_TOOLS and int(state.get("failed_verifications", 0)) >= MAX_FAILED_VERIFICATIONS:
        return _blocked(state, "locked_out",                     # 3. brute-force lock-out
                        "Too many failed verification attempts. Do not try again. Offer request_callback.")
    for k, v in raw.items():                                     # 4. injection smuggled into arguments
        if isinstance(v, str) and (len(v) > 300 or INJECTION_RE.search(v)):
            return _blocked(state, "suspicious_argument", "Ask the caller to rephrase; do not repeat that text.")
    try:                                                         # 5. strict schema validation
        parsed = TOOL_MODELS[tool](**raw)
    except ValidationError as e:
        problems = "; ".join(f"{'.'.join(map(str, err['loc']))}: {err['msg']}" for err in e.errors())[:400]
        return _blocked(state, "invalid_arguments",
                        "Ask the caller for the missing or unclear detail, politely, then try again.", details=problems)
    return {"args": parsed.model_dump(), "calls_made": calls, "blocked": False, "trace": _t(state, "guard_input")}


def route_after_guard(state: CallState) -> str:
    return "guard_output" if state.get("blocked") else NODE_FOR_TOOL[state["tool"]]


# ---- tool nodes
def info_node(state: CallState) -> dict:
    a = state["args"]
    return {"result": clinic.get_clinic_info(a["topic"], a.get("service")), "trace": _t(state, "info_node")}


def availability_node(state: CallState) -> dict:
    a = state["args"]
    return {"result": clinic.check_availability(a["date"], a.get("treatment"), a.get("doctor")),
            "trace": _t(state, "availability_node")}


def booking_node(state: CallState) -> dict:
    """Two-phase commit: nothing is written until the caller has heard a read-back and said yes."""
    a = state["args"]
    key = {k: str(a[k]).strip().lower() for k in ("patient_name", "phone", "date", "time", "treatment")}
    err, plan = clinic.validate_booking(a)
    if err:
        return {"result": err, "pending_booking": None, "trace": _t(state, "booking_node")}
    if not (a["caller_confirmed"] and state.get("pending_booking") == key):
        return {"pending_booking": key, "trace": _t(state, "booking_node"),
                "result": {"ok": False, "needs_confirmation": True, "readback": clinic.readback(a, plan),
                           "say": ("Read these details back to the caller, with the phone number digit by digit, and ask 'Shall I confirm "
                                   "this?'. Only after a clear yes call book_appointment again with identical details and "
                                   "caller_confirmed=true.")}}
    return {"result": clinic.create_booking(a, plan), "pending_booking": None, "trace": _t(state, "booking_node")}


def _verified(state: CallState, node: str, result: dict) -> dict:
    out = {"result": result, "trace": _t(state, node)}
    if result.get("error") == "verification_failed":
        out["failed_verifications"] = int(state.get("failed_verifications", 0)) + 1
    return out


def lookup_node(state: CallState) -> dict:
    a = state["args"]
    return _verified(state, "lookup_node", clinic.lookup_appointments(a["phone"], a["patient_name"]))


def cancel_node(state: CallState) -> dict:
    a = state["args"]
    return _verified(state, "cancel_node", clinic.cancel_appointment(a["booking_id"], a["phone"]))


def reschedule_node(state: CallState) -> dict:
    a = state["args"]
    return _verified(state, "reschedule_node",
                     clinic.reschedule_appointment(a["booking_id"], a["phone"], a["new_date"], a["new_time"]))


def callback_node(state: CallState) -> dict:
    a = state["args"]
    return {"result": clinic.request_callback(a["reason"], a.get("callback_phone")), "trace": _t(state, "callback_node")}


def emergency_node(state: CallState) -> dict:
    return {"result": clinic.emergency_guidance(state["args"]["symptoms"]), "trace": _t(state, "emergency_node")}


# ---- guard_output
def _clean(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _clean(v) for k, v in obj.items() if not str(k).startswith("_")}
    if isinstance(obj, list):
        return [_clean(v) for v in obj[:12]]
    if isinstance(obj, str):
        return obj[:1200]
    return obj


def guard_output(state: CallState) -> dict:
    res = state.get("result") or {"ok": False, "error": "no_result", "say": "Something went wrong; offer the front desk number."}
    return {"result": _clean(res), "trace": _t(state, "guard_output")}


# ---- build + public API
def build_graph():
    g = StateGraph(CallState)
    g.add_node("guard_input", guard_input)
    for node_name, fn in [("info_node", info_node), ("availability_node", availability_node), ("booking_node", booking_node),
                          ("lookup_node", lookup_node), ("cancel_node", cancel_node), ("reschedule_node", reschedule_node),
                          ("callback_node", callback_node), ("emergency_node", emergency_node)]:
        g.add_node(node_name, fn)
        g.add_edge(node_name, "guard_output")
    g.add_node("guard_output", guard_output)
    g.add_edge(START, "guard_input")
    g.add_conditional_edges("guard_input", route_after_guard,
                            {**{n: n for n in NODE_FOR_TOOL.values()}, "guard_output": "guard_output"})
    g.add_edge("guard_output", END)
    return g.compile(checkpointer=MemorySaver())


GRAPH = build_graph()


async def run_tool(call_id: str, tool: str, args: dict) -> dict:
    out = await GRAPH.ainvoke(
        {"tool": tool, "args": dict(args or {}), "result": {}, "blocked": False, "trace": []},
        config={"configurable": {"thread_id": call_id}})
    return {"result": out["result"], "trace": out["trace"], "blocked": bool(out.get("blocked"))}


def end_call(call_id: str) -> None:
    try:
        GRAPH.checkpointer.delete_thread(call_id)
    except Exception:
        pass
