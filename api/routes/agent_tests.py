"""Tests of agents against customers played by the AI."""

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field

from api.db import db_client
from api.db.models import UserModel
from api.services.agent_tests import service as tests
from api.services.agent_tests.model import ModelUnavailable
from api.services.agent_tests.service import AgentTestError, AgentTestIn
from api.services.auth.depends import get_user

router = APIRouter(prefix="/agent-tests", tags=["agent-tests"])


def _org(user: UserModel) -> int:
    if not user.selected_organization_id:
        raise HTTPException(status_code=400, detail="Aucune organisation sélectionnée")
    return user.selected_organization_id


async def _call(coro):
    try:
        return await coro
    except AgentTestError as error:
        raise HTTPException(status_code=error.status, detail=str(error)) from error
    except ModelUnavailable as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


async def _workflow(org: int, workflow_id: int) -> None:
    if await db_client.get_workflow(workflow_id, organization_id=org) is None:
        raise HTTPException(status_code=404, detail="Agent introuvable")


class AgentTestCreate(AgentTestIn):
    workflow_id: int


class RunRequest(BaseModel):
    workflow_id: int
    test_ids: list[int] | None = Field(default=None, max_length=50)
    version: Literal["draft", "published"] = "draft"


class SuggestRequest(BaseModel):
    workflow_id: int
    count: int = Field(default=4, ge=1, le=6)


@router.get("")
async def list_agent_tests(
    workflow_id: int = Query(...), user: UserModel = Depends(get_user)
) -> list[dict[str, Any]]:
    """The agent's tests, each with its last run."""
    org = _org(user)
    await _workflow(org, workflow_id)
    last = await db_client.latest_agent_test_runs(org, workflow_id)
    return [
        tests.serialize_test(t, last.get(t.id))
        for t in await db_client.list_agent_tests(org, workflow_id)
    ]


@router.post("", status_code=201)
async def create_agent_test(
    body: AgentTestCreate, user: UserModel = Depends(get_user)
) -> dict[str, Any]:
    org = _org(user)
    await _workflow(org, body.workflow_id)
    values = body.model_dump(exclude={"workflow_id"})
    row = await db_client.save_agent_test(org, body.workflow_id, values)
    return tests.serialize_test(row)


@router.put("/{test_id}")
async def update_agent_test(
    test_id: int, body: AgentTestIn, user: UserModel = Depends(get_user)
) -> dict[str, Any]:
    org = _org(user)
    test = await db_client.get_agent_test(org, test_id)
    if test is None:
        raise HTTPException(status_code=404, detail="Test introuvable")
    row = await db_client.save_agent_test(
        org, test.workflow_id, body.model_dump(), test_id
    )
    return tests.serialize_test(row)


@router.delete("/{test_id}", status_code=204)
async def delete_agent_test(test_id: int, user: UserModel = Depends(get_user)):
    org = _org(user)
    test = await db_client.get_agent_test(org, test_id)
    if test is None or not await db_client.delete_agent_test(
        org, test.workflow_id, test_id
    ):
        raise HTTPException(status_code=404, detail="Test introuvable")
    return Response(status_code=204)


@router.post("/run", status_code=202)
async def run_agent_tests(
    body: RunRequest, user: UserModel = Depends(get_user)
) -> list[dict[str, Any]]:
    """Queue a run per test (all of the agent's tests by default)."""
    org = _org(user)
    await _workflow(org, body.workflow_id)
    return await _call(
        tests.queue_runs(
            org, body.workflow_id, body.test_ids, version=body.version, user_id=user.id
        )
    )


@router.post("/suggest")
async def suggest_agent_tests(
    body: SuggestRequest, user: UserModel = Depends(get_user)
) -> list[dict[str, Any]]:
    """Starter tests drafted from the agent's prompts (not saved)."""
    org = _org(user)
    await _workflow(org, body.workflow_id)
    return await _call(tests.suggest_tests(org, body.workflow_id, count=body.count))


@router.get("/{test_id}/runs")
async def list_agent_test_runs(
    test_id: int, user: UserModel = Depends(get_user)
) -> list[dict[str, Any]]:
    org = _org(user)
    if await db_client.get_agent_test(org, test_id) is None:
        raise HTTPException(status_code=404, detail="Test introuvable")
    return [
        tests.serialize_run(r)
        for r in await db_client.list_agent_test_runs(org, test_id)
    ]


@router.get("/runs/{run_id}")
async def read_agent_test_run(
    run_id: int, user: UserModel = Depends(get_user)
) -> dict[str, Any]:
    """One run: conversation, tool calls, checks, criteria and verdict."""
    run = await db_client.get_agent_test_run(_org(user), run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Exécution introuvable")
    return tests.serialize_run(run, full=True)
