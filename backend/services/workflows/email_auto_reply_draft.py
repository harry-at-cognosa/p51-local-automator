"""Auto-Reply (Draft Only) runner.

Generates acknowledgment drafts for matching form-submission emails and saves
each draft into the account's Drafts folder via AppleScript. Nothing is sent.
User reviews drafts later in their email client.
"""
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import EmailAutoReplyLog, UserWorkflows, WorkflowRuns
from backend.services import mcp_client
from backend.services import workflow_engine as engine
from backend.services.logger_service import get_logger
from backend.services.workflows.email_auto_reply_engine import find_and_generate_candidates

log = get_logger("email_auto_reply_draft")


async def run_email_auto_reply_draft(
    session: AsyncSession,
    workflow: UserWorkflows,
    trigger: str = "manual",
) -> WorkflowRuns:
    run = await engine.create_run(session, workflow.workflow_id, total_steps=3, trigger=trigger, config=workflow.config)
    config = workflow.config or {}
    from_account = config.get("account", "iCloud")
    sender_filter = (config.get("sender_filter") or "").strip()
    body_contains = (config.get("body_contains") or "").strip()

    try:
        # Step 1+2+3: fetch, filter, LLM-draft (combined inside the engine)
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

        # Step 2: save each draft via AppleScript + log dedup (winner + siblings)
        step_save = await engine.start_step(session, run.run_id, 2, "Save drafts to Mail.app")
        saved = 0
        covered_total = 0  # count of older siblings folded into a saved draft
        errors: list[str] = []
        for c in candidates:
            try:
                await mcp_client.mail_save_draft(
                    to=c.to_address,
                    subject=c.reply_subject,
                    body=c.reply_body,
                    from_account=from_account,
                )
            except Exception as e:
                errors.append(f"{c.source_message_id}: {str(e)[:120]}")
                log.error("draft_save_failed", msg_id=c.source_message_id, error=str(e))
                continue

            # Dedup row for the chosen (winner) message
            session.add(
                EmailAutoReplyLog(
                    workflow_id=workflow.workflow_id,
                    source_message_id=c.source_message_id,
                    source_account=c.source_account,
                    action="draft_saved",
                )
            )
            # Dedup rows for each older sibling covered by this draft
            for sib_id in c.additional_handled_message_ids:
                session.add(
                    EmailAutoReplyLog(
                        workflow_id=workflow.workflow_id,
                        source_message_id=sib_id,
                        source_account=c.source_account,
                        action="draft_saved",
                    )
                )
            covered_total += len(c.additional_handled_message_ids)
            saved += 1

        await session.commit()

        summary = f"Saved {saved} of {len(candidates)} drafts to {from_account} Drafts."
        if covered_total:
            summary += f" Consolidated {covered_total} older sibling message(s) under their newer sender."
        if errors:
            summary += f" Errors: {'; '.join(errors[:3])}"
        if saved == 0 and errors:
            await engine.fail_step(session, step_save, summary)
            await engine.fail_run(session, run, summary)
            return run
        await engine.complete_step(session, step_save, output_summary=summary)

        # Step 3: summary artifact (a small text log of what was drafted)
        step_log = await engine.start_step(session, run.run_id, 3, "Write summary log")
        output_dir = await engine.get_run_output_dir(
            session, workflow.group_id, workflow.user_id, workflow.workflow_id, run.run_id
        )
        import os
        log_path = os.path.join(output_dir, "drafts_saved.txt")
        with open(log_path, "w") as f:
            f.write(f"Auto-Reply (Draft Only) — run #{run.run_id}\n")
            f.write(f"Workflow: #{workflow.workflow_id}  {workflow.name}\n")
            f.write(f"Account: {from_account}\n")
            f.write(f"Saved: {saved} / {len(candidates)}\n")
            if covered_total:
                f.write(f"Older sibling messages folded in (dedup'd): {covered_total}\n")
            f.write("\n")
            for i, c in enumerate(candidates, start=1):
                f.write("=" * 72 + "\n")
                f.write(f"Draft {i} of {len(candidates)}\n")
                f.write(f"  To:               {c.to_address}\n")
                f.write(f"  Subject:          {c.reply_subject}\n")
                f.write(f"  Source from:      {c.source_from}\n")
                f.write(f"  Source subject:   {c.source_subject}\n")
                f.write(f"  Winner msg id:    {c.source_message_id}\n")
                if c.additional_handled_message_ids:
                    f.write(
                        f"  Covered msg ids:  {', '.join(c.additional_handled_message_ids)}\n"
                    )
                f.write(f"  LLM tokens:       {c.llm_tokens}\n")
                f.write("\n  Source body (first 400 chars):\n")
                preview = (c.source_body or "")[:400].rstrip()
                for line in preview.splitlines() or [""]:
                    f.write(f"    | {line}\n")
                if len(c.source_body or "") > 400:
                    f.write(f"    | … (truncated, total {len(c.source_body)} chars)\n")
                f.write("\n  Generated reply body:\n")
                for line in (c.reply_body or "").splitlines() or [""]:
                    f.write(f"    | {line}\n")
                f.write("\n")
        await engine.record_artifact(session, run.run_id, step_log.step_id, log_path, "txt", "Drafts saved log")
        await engine.complete_step(session, step_log, output_summary=f"Wrote {log_path}")

        await engine.complete_run(session, run)
        log.info("auto_reply_draft_complete", run_id=run.run_id, saved=saved)
        return run

    except Exception as e:
        log.error("auto_reply_draft_error", run_id=run.run_id, error=str(e))
        await engine.fail_run(session, run, str(e)[:1000])
        return run
