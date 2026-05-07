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
import os
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import UserWorkflows, WorkflowRuns, WorkflowSteps
from backend.services import workflow_engine as engine
from backend.services.logger_service import get_logger
from backend.services.skills import SKILL_REGISTRY, SkillContext

log = get_logger("agentic_engine")


_SUMMARY_MAX_CHARS = 2000


def _truncate_summary(value: Any) -> str:
    """Compact JSON serialization for output_summary, capped at _SUMMARY_MAX_CHARS."""
    try:
        s = json.dumps(value, default=str)
    except (TypeError, ValueError):
        s = str(value)
    if len(s) > _SUMMARY_MAX_CHARS:
        return s[: _SUMMARY_MAX_CHARS - 16] + "...[truncated]"
    return s


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
        inputs_dir: str,
    ):
        self.session = session
        self.run = run
        self.workflow = workflow
        self.ctx = ctx
        # Absolute path to the user's inputs sandbox; data_definition file
        # paths are relative to this. Resolved by the runner before
        # constructing the engine so the engine doesn't need DB access for
        # group_settings / api_settings lookup.
        self.inputs_dir = inputs_dir
        self._step_counter = 0
        self._current_stage: str | None = None
        # Per-stage rollup state. Populated as stages run; consumed by
        # later stages (e.g. synthesize reads self.profile_summary).
        self.table_descriptions: dict[str, str] = {}
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

    async def _enter_stage(self, name: str) -> WorkflowSteps:
        """Begin a stage: open the start marker and remember the name so
        skill_call rows know which stage they belong to."""
        self._current_stage = name
        return await self._stage_marker_start(name)

    # ── skill dispatch ───────────────────────────────────────────────

    async def _call_skill(self, skill_name: str, **kwargs) -> Any:
        """Invoke a registered skill, write a kind=skill_call step row,
        return the result. Honors the skill's on_failure policy:
        - abort: re-raise
        - skip: log and return None
        - retry_once: try a second time, then act per skip
        """
        if skill_name not in SKILL_REGISTRY:
            raise KeyError(f"Unknown skill {skill_name!r}")
        skill = SKILL_REGISTRY[skill_name]
        step = await self._start(
            step_name=skill_name,
            stage=self._current_stage or "",
            kind="skill_call",
        )
        try:
            result = await skill.run(self.ctx, **kwargs)
            await engine.complete_step(
                self.session, step, output_summary=_truncate_summary(result)
            )
            return result
        except Exception as e:  # noqa: BLE001 - intentional broad catch per on_failure policy
            err = f"{type(e).__name__}: {e}"
            if skill.on_failure == "retry_once":
                log.info("skill_retry", skill=skill_name, error=err)
                try:
                    result = await skill.run(self.ctx, **kwargs)
                    await engine.complete_step(
                        self.session,
                        step,
                        output_summary=_truncate_summary(result) + " [recovered after retry]",
                    )
                    return result
                except Exception as e2:  # noqa: BLE001
                    err = f"{type(e2).__name__}: {e2}"
            await engine.fail_step(self.session, step, error=err[:1000])
            if skill.on_failure == "abort":
                raise
            log.info("skill_skipped_after_error", skill=skill_name, error=err)
            return None

    @staticmethod
    def _table_name_for_row(index: int) -> str:
        """Stable, predictable table key. The LLM references tables by these
        keys in subsequent stages, so deterministic naming matters."""
        return f"t{index + 1}"

    @staticmethod
    def _ext_of(rel_path: str) -> str:
        return rel_path.rsplit(".", 1)[-1].lower() if "." in rel_path else ""

    # ── stages ───────────────────────────────────────────────────────

    async def stage_ingest(self) -> None:
        """Load every data_definition row into ctx.tables under a stable key."""
        marker = await self._enter_stage("ingest")
        try:
            rows = self.workflow.config.get("data_definition") or []
            rows = [r for r in rows if isinstance(r, dict) and (r.get("file") or "").strip()]
            if not rows:
                raise ValueError(
                    "data_definition is empty — at least one table is required to run AWF-1"
                )
            for i, row in enumerate(rows):
                rel = row["file"].strip()
                table_name = self._table_name_for_row(i)
                abs_path = os.path.normpath(os.path.join(self.inputs_dir, rel))
                if not abs_path.startswith(os.path.normpath(self.inputs_dir) + os.sep) and \
                   abs_path != os.path.normpath(self.inputs_dir):
                    raise ValueError(f"Path {rel!r} escapes the user's inputs sandbox")
                ext = self._ext_of(rel)
                if ext == "csv":
                    await self._call_skill("load_csv", table_name=table_name, file_path=abs_path)
                elif ext in ("xlsx", "xls"):
                    await self._call_skill("load_xlsx", table_name=table_name, file_path=abs_path)
                else:
                    raise ValueError(
                        f"Unsupported file extension {ext!r} for {rel!r} — only csv/xlsx are loadable"
                    )
                self.table_descriptions[table_name] = (row.get("description") or "").strip()
            await self._stage_marker_complete(
                marker, summary=f"Loaded {len(self.ctx.tables)} table(s): {sorted(self.ctx.tables)}"
            )
        except Exception as e:
            await self._stage_marker_fail(marker, f"ingest failed: {e}")
            raise

    async def stage_profile(self) -> None:
        """Describe every column of every loaded table. Result feeds analyze
        and synthesize."""
        marker = await self._enter_stage("profile")
        try:
            profile: dict[str, Any] = {}
            for table_name, df in self.ctx.tables.items():
                cols = []
                for col in df.columns:
                    out = await self._call_skill(
                        "describe_column", table_name=table_name, column=str(col)
                    )
                    if out is not None:
                        cols.append(out)
                profile[table_name] = {
                    "shape": [int(df.shape[0]), int(df.shape[1])],
                    "description": self.table_descriptions.get(table_name, ""),
                    "columns": cols,
                }
            self.profile_summary = profile
            n_rows = sum(p["shape"][0] for p in profile.values())
            await self._stage_marker_complete(
                marker,
                summary=f"Profiled {len(profile)} table(s) totaling {n_rows} rows",
            )
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
