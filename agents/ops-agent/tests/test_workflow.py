"""IncidentWorkflow with stub activities in Temporal's time-skipping test server (skipped if it can't start)."""
import asyncio
import uuid

import pytest
from temporalio import activity
from temporalio.client import WorkflowFailureError
from temporalio.worker import Worker

from ops_agent.worker.workflows import INVESTIGATE_QUEUE, IncidentWorkflow

calls: list[str] = []


def stubs(wait: int, relevant: bool):
    @activity.defn(name="recheck_delay")
    async def recheck_delay(i: int) -> int:
        calls.append("recheck_delay")
        return wait

    @activity.defn(name="still_relevant")
    async def still_relevant(i: int) -> bool:
        calls.append("still_relevant")
        return relevant

    @activity.defn(name="analyse_incident")
    async def analyse_incident(i: int) -> int:
        calls.append("analyse")
        return 1

    @activity.defn(name="notify_incident")
    async def notify_incident(i: int) -> str:
        calls.append("notify")
        return "held"

    @activity.defn(name="close_incident")
    async def close_incident(i: int) -> str:
        calls.append("close")
        return "closed"

    return [recheck_delay, still_relevant, notify_incident, close_incident], [analyse_incident]


async def run_case(wait: int, relevant: bool, resolve: bool) -> str:
    from temporalio.testing import WorkflowEnvironment
    try:
        env = await WorkflowEnvironment.start_time_skipping()
    except Exception as e:  # no test server download possible here
        pytest.skip(f"Temporal test server unavailable: {e}")
    async with env:
        main, inv = stubs(wait, relevant)
        async with Worker(env.client, task_queue="t", workflows=[IncidentWorkflow], activities=main), \
                Worker(env.client, task_queue=INVESTIGATE_QUEUE, activities=inv):
            h = await env.client.start_workflow(IncidentWorkflow.run, 7, id=str(uuid.uuid4()), task_queue="t")
            if resolve:
                await asyncio.sleep(1)
                await h.signal(IncidentWorkflow.resolve)
            return await h.result()


@pytest.mark.parametrize("wait,relevant,expect,seq", [
    (600, False, "transient during a change", ["recheck_delay", "still_relevant"]),
    (600, True, "closed", ["recheck_delay", "still_relevant", "analyse", "notify", "close"]),
    (0, True, "closed", ["recheck_delay", "analyse", "notify", "close"]),
])
def test_incident_workflow(wait, relevant, expect, seq):
    calls.clear()
    assert asyncio.run(run_case(wait, relevant, resolve=True)) == expect
    assert calls == seq
