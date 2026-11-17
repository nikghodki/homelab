"""Temporal workflows (deterministic code only; the work is in activities.py)."""
from __future__ import annotations

import asyncio
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from . import activities as A

INVESTIGATE_QUEUE = "ops-investigate"


@workflow.defn
class IncidentWorkflow:
    """One per incident: analyse (first look, recall, investigate), notify, wait for resolution, postmortem."""

    def __init__(self) -> None:
        self.resolved = False

    @workflow.signal
    def resolve(self) -> None:
        self.resolved = True

    @workflow.run
    async def run(self, incident_id: int) -> str:
        # During one of the owner's own changes most warnings are the change settling (a pod rolling, a sync in
        # progress): wait 10 minutes and investigate only if it is still happening (design §4.2 "during-change").
        if workflow.patched("during-change-recheck"):
            wait = await workflow.execute_activity(A.recheck_delay, incident_id, start_to_close_timeout=timedelta(minutes=1))
            if wait:
                await workflow.sleep(timedelta(seconds=wait))
                if not await workflow.execute_activity(A.still_relevant, incident_id,
                                                       start_to_close_timeout=timedelta(minutes=1)):
                    return "transient during a change"
        await workflow.execute_activity(
            A.analyse_incident, incident_id, task_queue=INVESTIGATE_QUEUE,
            start_to_close_timeout=timedelta(minutes=30), heartbeat_timeout=timedelta(minutes=3),
            retry_policy=RetryPolicy(maximum_attempts=2, initial_interval=timedelta(minutes=1),
                                     non_retryable_error_types=["Stopped"]))
        await workflow.execute_activity(A.notify_incident, incident_id, start_to_close_timeout=timedelta(minutes=2),
                                        retry_policy=RetryPolicy(maximum_attempts=3))
        try:
            await workflow.wait_condition(lambda: self.resolved, timeout=timedelta(days=7))
        except asyncio.TimeoutError:
            pass
        await workflow.execute_activity(A.close_incident, incident_id, start_to_close_timeout=timedelta(minutes=2),
                                        retry_policy=RetryPolicy(maximum_attempts=3))
        return "closed"


@workflow.defn
class DigestWorkflow:
    """The 08:00 digest (Temporal Schedule ops-agent-digest)."""

    @workflow.run
    async def run(self) -> str:
        return await workflow.execute_activity(A.send_digest, start_to_close_timeout=timedelta(minutes=5),
                                               retry_policy=RetryPolicy(maximum_attempts=3))
