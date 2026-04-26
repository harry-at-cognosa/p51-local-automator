"""Auto-Reply (Approve Before Send) runner.

Generates acknowledgment replies and inserts each into pending_email_replies
with status='pending'. The user visits the workflow's approval queue to
approve / edit-and-send / save-as-draft / reject each one.

A row is ALSO written to email_auto_reply_log with action='queued_for_approval'
so the next scheduled run doesn't re-queue the same message while it's still
awaiting user review. When the user resolves a pending item, the API updates
the log row's action to the terminal state (sent_direct / saved_as_draft /
edited_and_sent / rejected).
"""
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import (
    EmailAutoReplyLog,
    PendingEmailReplies,
    UserWorkflows,
    WorkflowRuns,
)
from backend.services import workflow_engine as engine
from backend.services.logger_service import get_logger
from backend.services.workflows.email_auto_reply_engine import find_and_generate_candidates

log = get_logger("email_auto_reply_approve")


async def run_email_auto_reply_approve(
    session: AsyncSession,
    workflow: UserWorkflows,
    trigger: str = "manual",
) -> WorkflowRuns:
    run = await engine.create_run(session, workflow.workflow_id, total_steps=2, trigger=trigger)
    config = workflow.config or {}
    sender_filter = (config.get("sender_filter") or "").strip()
    body_contains = (config.get("body_contains") or "").strip()

    try:
        # Step 1: fetch + filter + LLM-draft
        step_fetch = await engine.start_step(session, run.run_id, 1, "Fetch + filter + draft")
        batch = await find_and_generate_candidates(session, workflow)
        candidates = batch.candidates
        total_tokens = sum(c.llm_tokens for c in candidates)
        funnel = batch.funnel_summary(sender_filter, body_contains)
        await engine.complete_step(
            session,
            step_fetch,
            output_summary=funnel,
            llm_tokens=total_tokens,
        )

        if not candidates:
            await engine.complete_run(session, run)
            return run

        # Step 2: insert each into pending_email_replies + dedup log (winner + siblings)
        step_queue = await engine.start_step(session, run.run_id, 2, "Queue for approval")
        queued = 0
        covered_total = 0  # count of older siblings folded into a queued reply
        for c in candidates:
            pending = PendingEmailReplies(
                workflow_id=workflow.workflow_id,
                run_id=run.run_id,
                source_message_id=c.source_message_id,
                source_account=c.source_account,
                source_mailbox=c.source_mailbox,
                source_from=c.source_from,
                source_subject=c.source_subject,
                to_address=c.to_address,
                subject=c.reply_subject,
                body_draft=c.reply_body,
                status="pending",
            )
            session.add(pending)
            await session.flush()  # need pending.pending_id for the log FK

            # Dedup row for the chosen (winner) message — pending_id linked
            session.add(
                EmailAutoReplyLog(
                    workflow_id=workflow.workflow_id,
                    source_message_id=c.source_message_id,
                    source_account=c.source_account,
                    action="queued_for_approval",
                    pending_id=pending.pending_id,
                )
            )
            # Dedup rows for older siblings (no pending_id — they're not in the queue,
            # they're just covered by the winner so they don't reappear in future runs)
            for sib_id in c.additional_handled_message_ids:
                session.add(
                    EmailAutoReplyLog(
                        workflow_id=workflow.workflow_id,
                        source_message_id=sib_id,
                        source_account=c.source_account,
                        action="queued_for_approval",
                    )
                )
            covered_total += len(c.additional_handled_message_ids)
            queued += 1

        await session.commit()

        summary = f"Queued {queued} reply/replies for human approval."
        if covered_total:
            summary += f" Consolidated {covered_total} older sibling message(s)."
        await engine.complete_step(session, step_queue, output_summary=summary)

        await engine.complete_run(session, run)
        log.info("auto_reply_approve_complete", run_id=run.run_id, queued=queued)
        return run

    except Exception as e:
        log.error("auto_reply_approve_error", run_id=run.run_id, error=str(e))
        await engine.fail_run(session, run, str(e)[:1000])
        return run
