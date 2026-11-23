"""A text conversation between a saved agent and a simulated customer.

Same machinery as the builder's mocked rehearsals
(``api.services.workflow.builder_runtime.scenarios``): production prompt
composition for each node, the node's tool schemas and transition functions,
the workflow graph's moves. Differences, because a *saved* agent is tested
against a *customer played by the AI*:

* the customer's lines are generated turn by turn (``Customer``);
* no tool ever acts on the world: their results are simulated (the test's own
  results, else a neutral success). Two read-only tools run for real, on the
  company's data: the catalog search, and nothing else;
* hanging up, transferring and ending a call are recorded as the outcome of
  the conversation instead of being refused.

Voice (timing, interruptions, audio), extraction and pre-call fetches are not
covered: the result says so.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Protocol

from jsonschema import ValidationError as SchemaError
from jsonschema import validate

from api.services.workflow.pipecat_engine_context_composer import (
    compose_system_prompt_for_node,
)
from api.services.workflow.tools.calculator import get_calculator_tools
from api.services.workflow.tools.custom_tool import tool_to_function_schema
from api.services.workflow.tools.knowledge_base import get_knowledge_base_tool
from api.services.workflow.workflow_graph import WorkflowGraph
from api.utils.template_renderer import render_template

TERMINAL = {
    "end_call": "ended_by_agent",
    "transfer_call": "transferred",
    "transfer_agent": "transferred",
}
LIVE_READ_ONLY = {"search_catalog"}
MAX_MODEL_CALLS_PER_TURN = 6
SIMULATED = {
    "status": "success",
    "simulated": True,
    "note": "Résultat simulé pour un test : aucune action réelle n'a été faite.",
}


class Customer(Protocol):
    async def next(self, transcript: list[dict[str, Any]]) -> tuple[str, bool]:
        """The customer's next line, and whether they hang up after it."""


@dataclass
class Conversation:
    transcript: list[dict[str, Any]] = field(default_factory=list)
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    visited: list[str] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    outcome: str = "max_turns"
    model_calls: int = 0
    turns: int = 0


def uncovered_nodes(graph: WorkflowGraph) -> list[str]:
    """Nodes whose behaviour the text simulation only approximates."""
    names = []
    for node in graph.nodes.values():
        if (
            node.pre_call_fetch_mode != "disabled"
            or (node.extraction_enabled and node.extraction_variables)
            or node.greeting_type == "audio"
        ):
            names.append(node.name)
    return names


async def converse(
    *,
    organization_id: int,
    graph: WorkflowGraph,
    tools: list[Any],
    agent_model,
    customer: Customer,
    initial_context: dict[str, Any],
    mock_results: dict[str, Any],
    max_turns: int,
    run_action=None,
) -> Conversation:
    if run_action is None:
        from api.services.actions.dispatch import run_action
    from api.services.actions.common import ActionContext

    conv = Conversation()
    schemas_by_tool: dict[str, list[dict]] = {}
    category_of: dict[str, Any] = {}
    for tool in tools:
        schemas = (
            get_calculator_tools()
            if tool.category == "calculator"
            else [tool_to_function_schema(tool)]
        )
        schemas_by_tool[tool.tool_uuid] = schemas
        for schema in schemas:
            category_of[schema["function"]["name"]] = tool
    uncovered = uncovered_nodes(graph)
    if uncovered:
        conv.notes.append(
            "Nœuds approchés en texte seulement (extraction, chargement avant "
            "l'appel ou message audio) : " + ", ".join(uncovered)
        )

    node = graph.nodes[graph.start_node_id]
    conv.visited.append(node.name)
    messages: list[dict[str, Any]] = []

    def render(value: str | None) -> str:
        return render_template(value or "", initial_context)

    def spoken(text: str | None) -> None:
        if text and text.strip():
            conv.transcript.append(
                {"role": "agent", "node": node.name, "text": text.strip()}
            )

    if node.greeting:
        greeting = render(node.greeting)
        messages.append({"role": "assistant", "content": greeting})
        spoken(greeting)

    finished = False
    while not finished and conv.turns < max_turns:
        line, hangs_up = await customer.next(conv.transcript)
        line = (line or "").strip()
        if not line:
            conv.outcome = "customer_ended"
            break
        conv.turns += 1
        messages.append({"role": "user", "content": line})
        conv.transcript.append({"role": "customer", "text": line})

        for _ in range(MAX_MODEL_CALLS_PER_TURN):
            schemas = [
                s
                for uuid in node.tool_uuids or []
                for s in schemas_by_tool.get(uuid, [])
            ]
            if node.document_uuids:
                schemas.append(get_knowledge_base_tool(node.document_uuids))
            transitions = (
                {edge.get_function_name(): edge for edge in node.out_edges}
                if not node.is_end
                else {}
            )
            schemas.extend(
                {
                    "type": "function",
                    "function": {
                        "name": name,
                        "description": edge.condition,
                        "parameters": {
                            "type": "object",
                            "properties": {},
                            "additionalProperties": False,
                        },
                    },
                }
                for name, edge in transitions.items()
            )
            by_name = {s["function"]["name"]: s["function"] for s in schemas}
            prompt = compose_system_prompt_for_node(
                node=node, workflow=graph, format_prompt=render, has_recordings=False
            ).text
            reply = await agent_model.complete(
                messages, tools=schemas or None, system=prompt
            )
            conv.model_calls += 1
            calls = reply.get("tool_calls") or []
            assistant: dict[str, Any] = {
                "role": "assistant",
                "content": reply.get("content") or "",
            }
            if calls:
                assistant["tool_calls"] = [
                    {
                        "id": c["id"],
                        "type": "function",
                        "function": {
                            "name": c["name"],
                            "arguments": json.dumps(c["args"], ensure_ascii=False),
                        },
                    }
                    for c in calls
                ]
            messages.append(assistant)
            spoken(reply.get("content"))
            if not calls:
                if node.is_end:
                    conv.outcome, finished = "ended_by_agent", True
                break
            moved = False
            for call in calls:
                name, args = call["name"], call["args"]
                schema = by_name.get(name)
                result: Any = None
                if schema is None or moved:
                    conv.failures.append(f"Outil indisponible à cette étape : {name}")
                    result = {"error": "Tool unavailable in this node"}
                else:
                    try:
                        validate(args, schema["parameters"])
                    except SchemaError:
                        conv.failures.append(f"Arguments invalides pour {name}")
                        result = {"error": "Arguments do not match the tool schema"}
                if result is None and name in transitions:
                    edge = transitions[name]
                    if edge.transition_speech:
                        spoken(render(edge.transition_speech))
                    node = graph.nodes[edge.target]
                    conv.visited.append(node.name)
                    moved = True
                    result = {"status": "success"}
                elif result is None:
                    tool = category_of.get(name)
                    category = getattr(tool, "category", None)
                    record = {
                        "name": name,
                        "arguments": args,
                        "node": node.name,
                        "live": False,
                    }
                    conv.tool_calls.append(record)
                    if name in mock_results:
                        result = mock_results[name]
                    elif category in LIVE_READ_ONLY and tool is not None:
                        record["live"] = True
                        result = await run_action(
                            category,
                            ActionContext(
                                organization_id=organization_id,
                                tool_uuid=tool.tool_uuid,
                                tool_name=tool.name,
                                initial_context=initial_context,
                            ),
                            (tool.definition or {}).get("config", {}),
                            args,
                        )
                    elif name == "retrieve_from_knowledge_base":
                        result = {
                            "results": [],
                            "note": "Base de connaissances non interrogée pendant les tests : "
                            "fournissez un résultat simulé dans le test pour la couvrir.",
                        }
                    else:
                        result = SIMULATED
                    if category in TERMINAL:
                        conv.outcome, finished = TERMINAL[category], True
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call["id"],
                        "content": json.dumps(result, ensure_ascii=False, default=str),
                    }
                )
            if finished:
                break
        else:
            conv.failures.append(
                "L'agent a enchaîné trop d'actions sans répondre au client."
            )
            finished = True
        if hangs_up and not finished:
            conv.outcome, finished = "customer_ended", True
    return conv
