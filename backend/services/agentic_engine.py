"""AgenticEngine — six-stage lifecycle for AWF-1 ("Analyze Data Collection").

Stages:
    ingest      → deterministic; load_csv / load_xlsx per data_definition row
    profile     → deterministic; describe_column on every column
    analyze     → LLM-as-agent; descriptive_stats + charts skills as tools
    synthesize  → LLM call (no tools); produces draft_report.md
    audit       → A3: no-op. A4: LLM critique with read-only inspection skills
    scribe      → A3: no-op. A4: LLM polish using voice_and_style + audit notes

Step granularity (per the design review, fine-grained from day one):
    - Each stage entrance writes a `kind=stage_marker` start row.
    - Each skill invocation writes its own `kind=skill_call` row with the
      skill name in step_name.
    - Each LLM turn (Anthropic SDK message) writes its own `kind=llm_turn` row
      with token usage attached.
    - Each stage exit completes the start_marker and writes a matching end
      marker (status reflects whether the stage ran cleanly).

A3 covers ingest/profile/analyze/synthesize end-to-end plus no-op
markers for audit/scribe. A4 will replace the no-ops.
"""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import UserWorkflows, WorkflowRuns, WorkflowSteps
from backend.services import workflow_engine as engine
from backend.services.logger_service import get_logger
from backend.services.skills import SKILL_REGISTRY, SkillContext

log = get_logger("agentic_engine")


STAGES = ("ingest", "profile", "analyze", "synthesize", "audit", "scribe")


class AgenticEngine:
    """Drives a single AWF-1 run through all six lifecycle stages.

    Construct one per run. The runner module instantiates this, calls
    `run()`, and lets the engine handle step bookkeeping + skill
    orchestration. The engine is stateful within a run but stateless
    across runs.
    """

    def __init__(
        self,
        session: AsyncSession,
        run: WorkflowRuns,
        workflow: UserWorkflows,
        ctx: SkillContext,
    ):
        self.session = session
        self.run = run
        self.workflow = workflow
        self.ctx = ctx
        self._step_counter = 0
        # Per-stage rollup state. Populated as stages run; consumed by
        # later stages (e.g. synthesize reads self.profile_summary).
        self.profile_summary: dict[str, Any] = {}
        self.analyze_findings: list[str] = []
        self.draft_report_path: str | None = None

    # ── step helpers ─────────────────────────────────────────────────

    def _next_step_number(self) -> int:
        self._step_counter += 1
        return self._step_counter

    async def _start(self, step_name: str, stage: str, kind: str) -> WorkflowSteps:
        return await engine.start_step(
            self.session,
            run_id=self.run.run_id,
            step_number=self._next_step_number(),
            step_name=step_name,
            stage=stage,
            kind=kind,
        )

    async def _stage_marker_start(self, stage: str) -> WorkflowSteps:
        return await self._start(f"[{stage}] start", stage=stage, kind="stage_marker")

    async def _stage_marker_complete(self, marker: WorkflowSteps, summary: str = "") -> None:
        await engine.complete_step(self.session, marker, output_summary=summary)

    async def _stage_marker_fail(self, marker: WorkflowSteps, error: str) -> None:
        await engine.fail_step(self.session, marker, error=error)

    # ── stage stubs (filled in A3.2-A3.4) ────────────────────────────

    async def stage_ingest(self) -> None:
        marker = await self._stage_marker_start("ingest")
        try:
            # A3.2: iterate config.data_definition, dispatch load_csv / load_xlsx
            await self._stage_marker_complete(marker, summary="(ingest stub — A3.2)")
        except Exception as e:
            await self._stage_marker_fail(marker, f"ingest failed: {e}")
            raise

    async def stage_profile(self) -> None:
        marker = await self._stage_marker_start("profile")
        try:
            # A3.2: describe_column over every column of every loaded table
            await self._stage_marker_complete(marker, summary="(profile stub — A3.2)")
        except Exception as e:
            await self._stage_marker_fail(marker, f"profile failed: {e}")
            raise

    async def stage_analyze(self) -> None:
        marker = await self._stage_marker_start("analyze")
        try:
            # A3.3: LLM-as-agent loop with descriptive_stats + charts tools
            await self._stage_marker_complete(marker, summary="(analyze stub — A3.3)")
        except Exception as e:
            await self._stage_marker_fail(marker, f"analyze failed: {e}")
            raise

    async def stage_synthesize(self) -> None:
        marker = await self._stage_marker_start("synthesize")
        try:
            # A3.4: single LLM call producing draft_report.md
            await self._stage_marker_complete(marker, summary="(synthesize stub — A3.4)")
        except Exception as e:
            await self._stage_marker_fail(marker, f"synthesize failed: {e}")
            raise

    async def stage_audit(self) -> None:
        marker = await self._stage_marker_start("audit")
        # A4 will replace this with a real LLM critique.
        await self._stage_marker_complete(marker, summary="(audit no-op — scheduled for A4)")

    async def stage_scribe(self) -> None:
        marker = await self._stage_marker_start("scribe")
        # A4 will replace this with the final polish pass.
        await self._stage_marker_complete(marker, summary="(scribe no-op — scheduled for A4)")

    # ── public driver ────────────────────────────────────────────────

    async def run_all(self) -> None:
        """Drive all six stages in order. Caller wraps this in try/except
        and calls workflow_engine.complete_run / fail_run as appropriate."""
        log.info("agentic_run_start", run_id=self.run.run_id, workflow_id=self.workflow.workflow_id)
        for stage in STAGES:
            method = getattr(self, f"stage_{stage}")
            await method()
        log.info("agentic_run_complete", run_id=self.run.run_id, total_steps=self._step_counter)
