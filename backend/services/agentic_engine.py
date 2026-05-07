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
import re
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import UserWorkflows, WorkflowRuns, WorkflowSteps
from backend.services import workflow_engine as engine
from backend.services.logger_service import get_logger
from backend.services.skills import SKILL_REGISTRY, SkillContext

log = get_logger("agentic_engine")


_SUMMARY_MAX_CHARS = 2000

# Anthropic model defaults. Opus for reasoning-heavy stages.
DEFAULT_REASONING_MODEL = "claude-opus-4-7"

# Stage-tool mapping. analyze gets the read-write computation surface;
# audit (A4) will get the read-only inspection surface; data_io is never
# exposed to the LLM (loaders run deterministically in ingest).
ANALYZE_TOOL_NAMES = (
    "describe_column",
    "value_distribution",
    "correlation_matrix",
    "groupby_aggregate",
    "create_scatter_plot",
    "create_histogram",
    "create_bar_chart",
    "create_correlation_heatmap",
)

# Audit gets the read-only inspection surface: it can re-query tables to
# check claims but cannot run new chart-rendering or filesystem-writing
# skills. Charts and write_artifact are intentionally excluded — audit's
# job is to critique, not to add to the artifact set.
AUDIT_TOOL_NAMES = (
    "describe_column",
    "value_distribution",
    "correlation_matrix",
    "groupby_aggregate",
)

# Cap on agent-loop iterations per stage. Defensive against runaway
# tool-call loops; A5 will add a real token budget.
MAX_AGENT_TURNS = 25


_SLUG_RE = re.compile(r"[^A-Za-z0-9_-]+")


def _sanitize_slug(s: str, max_len: int = 60) -> str:
    """Lowercase, replace non-alnum/dash/underscore runs with `_`,
    collapse repeats, trim to max_len. Returns 'report' if empty."""
    s = (s or "").strip().lower()
    s = _SLUG_RE.sub("_", s)
    s = re.sub(r"_+", "_", s).strip("_")
    if not s:
        return "report"
    return s[:max_len]


def _final_report_filename(workflow_name: str, slug_override: str | None = None) -> str:
    """`<slug>_<YYMMDD>_FinalReport.md`. Slug priority:
    user-supplied report_filename slug, else sanitized workflow_name."""
    if slug_override and slug_override.strip():
        slug = _sanitize_slug(slug_override)
    else:
        slug = _sanitize_slug(workflow_name)
    yymmdd = datetime.now().strftime("%y%m%d")
    return f"{slug}_{yymmdd}_FinalReport.md"


def _truncate_summary(value: Any) -> str:
    """Compact JSON serialization for output_summary, capped at _SUMMARY_MAX_CHARS."""
    try:
        s = json.dumps(value, default=str)
    except (TypeError, ValueError):
        s = str(value)
    if len(s) > _SUMMARY_MAX_CHARS:
        return s[: _SUMMARY_MAX_CHARS - 16] + "...[truncated]"
    return s


def _extract_trailing_json(text: str) -> dict | None:
    """Scan an assistant reply for a trailing JSON object. Returns the
    parsed dict if found, else None. Stages validate the keys they
    expect ('findings' for analyze, 'weak_claims' etc. for audit)."""
    if not text:
        return None
    # Try the last fenced block first.
    fenced = text.rsplit("```", 2)
    candidates = []
    if len(fenced) >= 3:
        body = fenced[-2]
        if body.lower().startswith("json\n"):
            body = body[5:]
        candidates.append(body.strip())
    # Then the last { ... } substring.
    last_open = text.rfind("{")
    if last_open != -1:
        candidates.append(text[last_open:].strip())
    for c in candidates:
        try:
            obj = json.loads(c)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            return obj
    return None


# Backwards-compatible alias for any external callers; remove when the
# only user is the engine itself.
_extract_findings_json = _extract_trailing_json


def _content_blocks_to_dict(content: list[Any]) -> list[dict]:
    """Convert SDK Message.content blocks (mixed objects) to plain dicts so
    they can be appended to the messages list for the next request."""
    out: list[dict] = []
    for block in content:
        # Each block exposes a model_dump() in the SDK; fall back to attrs.
        if hasattr(block, "model_dump"):
            out.append(block.model_dump())
        else:
            out.append({k: getattr(block, k) for k in ("type", "text", "id", "name", "input")
                        if hasattr(block, k)})
    return out


STAGES = ("ingest", "profile", "analyze", "synthesize", "audit", "scribe")


class TokenBudgetExceeded(Exception):
    """Raised when the run's accumulated token usage would exceed the
    configured budget. Caught at run_all() so the engine can write a
    partial-report artifact before propagating the failure."""

    def __init__(self, used: int, budget: int):
        self.used = used
        self.budget = budget
        super().__init__(f"token budget exceeded: used={used}, budget={budget}")


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
        token_budget: int | None = None,
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
        # None means no cap. When set, _check_budget raises TokenBudgetExceeded
        # before each new LLM call if total_tokens_used would otherwise grow.
        self.token_budget = token_budget
        self._step_counter = 0
        self._current_stage: str | None = None
        # Per-stage rollup state. Populated as stages run; consumed by
        # later stages (e.g. synthesize reads self.profile_summary).
        self.table_descriptions: dict[str, str] = {}
        self.profile_summary: dict[str, Any] = {}
        self.analyze_findings: list[str] = []
        self.draft_report_path: str | None = None
        self.audit_critique: dict[str, list[str]] = {}
        self.final_report_path: str | None = None
        # Cost tracking — accumulated across every LLM turn (analyze loop +
        # synthesize + audit loop + scribe).
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.total_cache_creation_tokens = 0
        self.total_cache_read_tokens = 0

    @property
    def total_tokens_used(self) -> int:
        return self.total_input_tokens + self.total_output_tokens

    def _check_budget(self) -> None:
        """Raises TokenBudgetExceeded if the run is over its cap. Called
        before each new LLM SDK call. The check is deliberately on
        *already-used* tokens — a single in-flight call may push slightly
        over, but the next call won't fire."""
        if self.token_budget is not None and self.total_tokens_used >= self.token_budget:
            raise TokenBudgetExceeded(self.total_tokens_used, self.token_budget)

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
            await self._maybe_record_artifact(step.step_id, skill_name, result)
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

    async def _maybe_record_artifact(
        self, step_id: int, skill_name: str, result: Any
    ) -> None:
        """If a skill returns a {path, kind, ...} payload, register a
        workflow_artifacts row pointing at the file. Charts and
        write_artifact use this convention; descriptive stats don't."""
        if not isinstance(result, dict):
            return
        path = result.get("path")
        kind = result.get("kind")
        if not (isinstance(path, str) and isinstance(kind, str)):
            return
        if not os.path.exists(path):
            return
        await engine.record_artifact(
            self.session,
            run_id=self.run.run_id,
            step_id=step_id,
            file_path=path,
            file_type=kind,
            description=f"produced by {skill_name}",
        )

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
            # FilePicker stores file as {path, name}; keep tolerant of bare strings.
            def _file_rel(row: Any) -> str:
                f = row.get("file") if isinstance(row, dict) else None
                if isinstance(f, dict):
                    return (f.get("path") or "").strip()
                if isinstance(f, str):
                    return f.strip()
                return ""
            rows = [r for r in rows if isinstance(r, dict) and _file_rel(r)]
            if not rows:
                raise ValueError(
                    "data_definition is empty — at least one table is required to run AWF-1"
                )
            for i, row in enumerate(rows):
                rel = _file_rel(row)
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

    # ── LLM-as-agent loop ────────────────────────────────────────────

    def _accumulate_usage(self, usage: dict) -> None:
        """Roll an SDK usage dict into the engine's running totals."""
        self.total_input_tokens += int(usage.get("input_tokens", 0))
        self.total_output_tokens += int(usage.get("output_tokens", 0))
        self.total_cache_creation_tokens += int(usage.get("cache_creation_input_tokens", 0))
        self.total_cache_read_tokens += int(usage.get("cache_read_input_tokens", 0))

    async def _record_llm_turn(
        self,
        *,
        stage: str,
        purpose: str,
        usage: dict,
        stop_reason: str | None,
        text_preview: str = "",
    ) -> WorkflowSteps:
        """Write a kind=llm_turn workflow_steps row capturing one SDK call.
        Returns the completed step (already finalized)."""
        step = await self._start(
            step_name=f"llm: {purpose}",
            stage=stage,
            kind="llm_turn",
        )
        total_tokens = int(usage.get("input_tokens", 0)) + int(usage.get("output_tokens", 0))
        summary_obj = {
            "stop_reason": stop_reason,
            "usage": usage,
        }
        if text_preview:
            summary_obj["text_preview"] = text_preview[:500]
        await engine.complete_step(
            self.session,
            step,
            output_summary=_truncate_summary(summary_obj),
            llm_tokens=total_tokens,
        )
        return step

    async def _run_agent_loop(
        self,
        *,
        stage: str,
        system: str,
        user_prompt: str,
        tool_names: tuple[str, ...],
        model: str = DEFAULT_REASONING_MODEL,
        max_tokens: int = 4096,
        max_turns: int = MAX_AGENT_TURNS,
    ) -> tuple[str, int]:
        """Run an LLM-as-agent loop with tool use until the model emits
        end_turn. Returns (final_assistant_text, total_tokens). Each SDK
        call writes a kind=llm_turn row; each tool dispatch writes a
        kind=skill_call row via _call_skill.

        Imports the Anthropic client lazily so unit tests / module imports
        without ANTHROPIC_API_KEY don't fail.
        """
        from backend.services.llm_service import get_client  # lazy
        from backend.services.skills import to_anthropic_tools

        client = get_client()
        tools = to_anthropic_tools(names=list(tool_names))
        system_block = [{
            "type": "text",
            "text": system,
            "cache_control": {"type": "ephemeral"},
        }]
        messages: list[dict] = [{"role": "user", "content": user_prompt}]
        total_tokens = 0
        final_text = ""

        for turn in range(1, max_turns + 1):
            self._check_budget()
            response = client.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=system_block,
                tools=tools,
                messages=messages,
            )
            usage = {
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens,
                "cache_creation_input_tokens": getattr(
                    response.usage, "cache_creation_input_tokens", 0
                ),
                "cache_read_input_tokens": getattr(
                    response.usage, "cache_read_input_tokens", 0
                ),
            }
            self._accumulate_usage(usage)
            text_blocks = [b.text for b in response.content if getattr(b, "type", None) == "text"]
            preview = "\n".join(text_blocks)[:500] if text_blocks else ""
            await self._record_llm_turn(
                stage=stage,
                purpose=f"{stage} turn {turn}",
                usage=usage,
                stop_reason=response.stop_reason,
                text_preview=preview,
            )
            total_tokens += int(usage["input_tokens"]) + int(usage["output_tokens"])

            if response.stop_reason == "end_turn":
                final_text = "\n\n".join(text_blocks)
                break

            if response.stop_reason == "tool_use":
                # Append the assistant turn so the next request can resolve
                # tool_use_id references in the tool_result blocks.
                messages.append({
                    "role": "assistant",
                    "content": _content_blocks_to_dict(response.content),
                })
                tool_results: list[dict] = []
                for block in response.content:
                    if getattr(block, "type", None) != "tool_use":
                        continue
                    skill_name = block.name
                    tool_input = block.input or {}
                    try:
                        result = await self._call_skill(skill_name, **tool_input)
                        is_error = False
                        content_str = json.dumps(result, default=str)
                    except Exception as e:  # noqa: BLE001
                        result = None
                        is_error = True
                        content_str = f"{type(e).__name__}: {e}"
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": content_str,
                        "is_error": is_error,
                    })
                messages.append({"role": "user", "content": tool_results})
                continue

            # Any other stop_reason (max_tokens, stop_sequence, etc.) —
            # fold what we have and exit the loop.
            final_text = "\n\n".join(text_blocks)
            log.info(
                "agent_loop_unexpected_stop",
                stage=stage,
                stop_reason=response.stop_reason,
                turn=turn,
            )
            break
        else:
            # Hit max_turns without an end_turn signal.
            log.info("agent_loop_max_turns", stage=stage, max_turns=max_turns)

        return final_text, total_tokens

    async def stage_analyze(self) -> None:
        """LLM-as-agent loop. The analyst is given the goal, processing
        steps, profile summary, and a curated tool set; it iterates until
        it stops calling tools."""
        marker = await self._enter_stage("analyze")
        try:
            cfg = self.workflow.config or {}
            goal = (cfg.get("analysis_goal") or "").strip()
            steps = (cfg.get("processing_steps") or "").strip()
            if not goal:
                raise ValueError("analysis_goal is required")

            system = (
                "You are a careful data analyst. You have been given one or more "
                "tables loaded into the workflow's tables dict, a stated goal, and "
                "a set of analysis tools (descriptive statistics + chart rendering). "
                "Use the tools to gather evidence relevant to the goal. Render "
                "charts when they materially aid the analysis. When you have "
                "enough evidence, end your turn with a short JSON object on the "
                "last line of the form:\n"
                '  {"findings": ["<one-sentence finding>", ...], '
                '"artifacts_produced": ["<chart filename>", ...]}\n'
                "Keep findings to 3-8 items. Reference tables by their key (t1, t2, ...). "
                "Do not call a tool you have already called with identical arguments."
            )
            user_prompt = (
                f"## Goal\n{goal}\n\n"
                f"## Processing steps\n{steps or '(none specified — use your judgment)'}\n\n"
                f"## Profile summary\n```json\n{json.dumps(self.profile_summary, indent=2, default=str)}\n```\n\n"
                "Begin analysis. Call tools as needed."
            )

            text, tokens = await self._run_agent_loop(
                stage="analyze",
                system=system,
                user_prompt=user_prompt,
                tool_names=ANALYZE_TOOL_NAMES,
            )

            findings = _extract_trailing_json(text)
            if findings:
                self.analyze_findings = list(findings.get("findings") or [])
            await self._stage_marker_complete(
                marker,
                summary=_truncate_summary({
                    "tokens_used": tokens,
                    "n_findings": len(self.analyze_findings),
                    "raw_tail": text[-500:],
                }),
            )
        except Exception as e:
            await self._stage_marker_fail(marker, f"analyze failed: {e}")
            raise

    async def stage_synthesize(self) -> None:
        """Single LLM call (no tools) that produces a markdown draft report.
        Saved as draft_report.md and registered as a workflow_artifact."""
        marker = await self._enter_stage("synthesize")
        try:
            from backend.services.llm_service import get_client  # lazy

            cfg = self.workflow.config or {}
            goal = (cfg.get("analysis_goal") or "").strip()
            report_structure = (cfg.get("report_structure") or "").strip()

            # Surface the charts produced during analyze so the model can
            # cite them by filename in the draft.
            chart_files = sorted(
                f for f in os.listdir(self.ctx.artifacts_dir)
                if os.path.isfile(os.path.join(self.ctx.artifacts_dir, f))
                and f.lower().endswith(".png")
            ) if os.path.isdir(self.ctx.artifacts_dir) else []

            system = (
                "You are a technical writer. You will receive an analyst's "
                "findings, a description of the data, and a structural outline. "
                "Produce a markdown report that addresses the stated goal. "
                "Reference any chart files by their filename using markdown "
                "image syntax: ![caption](filename.png). Keep the prose tight; "
                "no preamble or sign-off. Output ONLY the markdown — no fences, "
                "no surrounding commentary."
            )

            user_prompt = (
                f"## Analysis goal\n{goal}\n\n"
                f"## Requested report structure\n"
                f"{report_structure or '(no structure specified — use your judgment)'}\n\n"
                f"## Tables\n```json\n"
                f"{json.dumps({k: v.get('description', '') for k, v in self.profile_summary.items()}, indent=2)}\n"
                f"```\n\n"
                f"## Findings from analysis\n"
                + ("\n".join(f"- {f}" for f in self.analyze_findings)
                   if self.analyze_findings else "(no structured findings — synthesize from the profile summary)")
                + "\n\n"
                f"## Chart files available\n"
                + ("\n".join(f"- {f}" for f in chart_files) if chart_files else "(none)")
                + "\n\n"
                f"## Profile summary (compact)\n```json\n"
                f"{json.dumps(self.profile_summary, indent=2, default=str)[:6000]}\n"
                f"```\n\n"
                "Write the markdown report now."
            )

            client = get_client()
            self._check_budget()
            # Manually issued so we can write a single llm_turn row for this
            # stage rather than using _run_agent_loop (no tools here).
            response = client.messages.create(
                model=DEFAULT_REASONING_MODEL,
                max_tokens=4096,
                system=[{
                    "type": "text",
                    "text": system,
                    "cache_control": {"type": "ephemeral"},
                }],
                messages=[{"role": "user", "content": user_prompt}],
            )
            usage = {
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens,
                "cache_creation_input_tokens": getattr(
                    response.usage, "cache_creation_input_tokens", 0
                ),
                "cache_read_input_tokens": getattr(
                    response.usage, "cache_read_input_tokens", 0
                ),
            }
            self._accumulate_usage(usage)
            text_blocks = [b.text for b in response.content if getattr(b, "type", None) == "text"]
            draft_md = "\n\n".join(text_blocks).strip()
            # Strip any accidental code fences (the system prompt forbids them
            # but models occasionally add anyway).
            if draft_md.startswith("```"):
                lines = draft_md.split("\n")
                draft_md = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

            await self._record_llm_turn(
                stage="synthesize",
                purpose="draft report",
                usage=usage,
                stop_reason=response.stop_reason,
                text_preview=draft_md[:500],
            )

            # Persist the draft via write_artifact (records its own
            # skill_call row + workflow_artifacts row via _maybe_record).
            artifact = await self._call_skill(
                "write_artifact",
                name="draft_report.md",
                content=draft_md,
                kind="md",
            )
            self.draft_report_path = artifact["path"] if artifact else None
            await self._stage_marker_complete(
                marker,
                summary=_truncate_summary({
                    "draft_path": self.draft_report_path,
                    "tokens": int(usage["input_tokens"]) + int(usage["output_tokens"]),
                    "char_count": len(draft_md),
                }),
            )
        except Exception as e:
            await self._stage_marker_fail(marker, f"synthesize failed: {e}")
            raise

    async def stage_audit(self) -> None:
        """LLM-as-agent critique pass over the synthesize draft.

        The auditor receives the draft, the analysis goal, the profile
        summary, and a read-only descriptive_stats tool surface. It can
        re-query tables to check claims but cannot generate new charts
        or write files. Output: a structured critique JSON saved as
        audit_critique.json. Scribe consumes it to drive the polish."""
        marker = await self._enter_stage("audit")
        try:
            cfg = self.workflow.config or {}
            goal = (cfg.get("analysis_goal") or "").strip()
            draft_md = ""
            if self.draft_report_path and os.path.exists(self.draft_report_path):
                with open(self.draft_report_path, encoding="utf-8") as f:
                    draft_md = f.read()

            if not draft_md:
                # Nothing to audit. Mark the stage complete and let scribe
                # fall through with no critique. Avoids paying for an LLM
                # call on a missing draft.
                await self._stage_marker_complete(
                    marker, summary="(no draft present — audit skipped)"
                )
                self.audit_critique = {}
                return

            system = (
                "You are a critical reviewer of an analytical report draft. You "
                "have access to read-only tools to re-query the underlying "
                "tables when you want to verify a specific claim. You cannot "
                "render new charts or write files — your job is to critique, "
                "not to extend the analysis. Be direct and specific. End your "
                "turn with a JSON object on the last line of the form:\n"
                '  {"weak_claims": ["<claim with reason it is weak>", ...], '
                '"overlooked_angles": ["<angle that should have been explored>", ...], '
                '"suggested_revisions": ["<actionable revision>", ...]}\n'
                "Each list 0-6 items. Empty lists are valid if the draft is solid. "
                "Reference tables by their key (t1, t2, ...)."
            )
            user_prompt = (
                f"## Goal\n{goal or '(unspecified)'}\n\n"
                f"## Profile summary (compact)\n```json\n"
                f"{json.dumps(self.profile_summary, indent=2, default=str)[:6000]}\n"
                f"```\n\n"
                f"## Draft report\n{draft_md}\n\n"
                "Critique the draft now. Use the read-only tools to verify any "
                "claim you want to challenge before flagging it."
            )

            text, tokens = await self._run_agent_loop(
                stage="audit",
                system=system,
                user_prompt=user_prompt,
                tool_names=AUDIT_TOOL_NAMES,
                max_turns=12,  # tighter than analyze; audit shouldn't sprawl
            )

            critique = _extract_trailing_json(text) or {}
            # Normalize: keep only the three documented keys, with list values.
            self.audit_critique = {
                k: list(critique.get(k) or [])
                for k in ("weak_claims", "overlooked_angles", "suggested_revisions")
            }

            # Persist the critique as a downloadable artifact.
            await self._call_skill(
                "write_artifact",
                name="audit_critique.json",
                content=self.audit_critique,
                kind="json",
            )

            await self._stage_marker_complete(
                marker,
                summary=_truncate_summary({
                    "tokens_used": tokens,
                    "weak_claims": len(self.audit_critique["weak_claims"]),
                    "overlooked_angles": len(self.audit_critique["overlooked_angles"]),
                    "suggested_revisions": len(self.audit_critique["suggested_revisions"]),
                }),
            )
        except Exception as e:
            await self._stage_marker_fail(marker, f"audit failed: {e}")
            raise

    async def stage_scribe(self) -> None:
        """Single LLM call (no tools) producing the polished final report.

        Receives the audited draft, the audit critique (weak_claims,
        overlooked_angles, suggested_revisions), and the user-supplied
        voice_and_style profile. Output filename per the polished-rule:
        `<slug>_<YYMMDD>_FinalReport.md`. Slug = config.report_filename
        if set, else the sanitized workflow name."""
        marker = await self._enter_stage("scribe")
        try:
            from backend.services.llm_service import get_client  # lazy

            cfg = self.workflow.config or {}
            voice_and_style = (cfg.get("voice_and_style") or "").strip()
            slug_override = (cfg.get("report_filename") or "").strip() or None

            draft_md = ""
            if self.draft_report_path and os.path.exists(self.draft_report_path):
                with open(self.draft_report_path, encoding="utf-8") as f:
                    draft_md = f.read()

            if not draft_md:
                # Nothing to polish. Mark skipped without paying for an LLM call.
                await self._stage_marker_complete(
                    marker, summary="(no draft present — scribe skipped)"
                )
                return

            critique_block = json.dumps(self.audit_critique, indent=2) if self.audit_critique else "(no critique)"

            system = (
                "You are a careful technical writer producing a final, polished "
                "report. You will be given an analyst's draft, a structured "
                "critique of that draft, and a voice/style profile. Apply the "
                "suggested revisions, address the weak claims, and incorporate "
                "the overlooked angles where appropriate. Match the voice and "
                "style profile. Preserve any markdown image references "
                "(![alt](file.png)) the draft included — they point at chart "
                "artifacts the user wants to see in the final report. Output "
                "ONLY the markdown report — no preamble, no fences, no sign-off."
            )
            user_prompt = (
                f"## Voice and style\n"
                f"{voice_and_style or '(no profile specified — write in a clear, neutral, exec-summary tone)'}\n\n"
                f"## Critique to address\n```json\n{critique_block}\n```\n\n"
                f"## Draft to polish\n{draft_md}\n\n"
                "Produce the final polished markdown report now."
            )

            client = get_client()
            response = client.messages.create(
                model=DEFAULT_REASONING_MODEL,
                max_tokens=4096,
                system=[{
                    "type": "text",
                    "text": system,
                    "cache_control": {"type": "ephemeral"},
                }],
                messages=[{"role": "user", "content": user_prompt}],
            )
            usage = {
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens,
                "cache_creation_input_tokens": getattr(
                    response.usage, "cache_creation_input_tokens", 0
                ),
                "cache_read_input_tokens": getattr(
                    response.usage, "cache_read_input_tokens", 0
                ),
            }
            text_blocks = [b.text for b in response.content if getattr(b, "type", None) == "text"]
            polished = "\n\n".join(text_blocks).strip()
            if polished.startswith("```"):
                lines = polished.split("\n")
                polished = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

            await self._record_llm_turn(
                stage="scribe",
                purpose="final polish",
                usage=usage,
                stop_reason=response.stop_reason,
                text_preview=polished[:500],
            )

            filename = _final_report_filename(self.workflow.name, slug_override)
            artifact = await self._call_skill(
                "write_artifact",
                name=filename,
                content=polished,
                kind="md",
            )
            self.final_report_path = artifact["path"] if artifact else None

            await self._stage_marker_complete(
                marker,
                summary=_truncate_summary({
                    "final_path": self.final_report_path,
                    "tokens": int(usage["input_tokens"]) + int(usage["output_tokens"]),
                    "char_count": len(polished),
                }),
            )
        except Exception as e:
            await self._stage_marker_fail(marker, f"scribe failed: {e}")
            raise

    # ── public driver ────────────────────────────────────────────────

    async def run_all(self) -> None:
        """Drive all six stages in order. Caller wraps this in try/except
        and calls workflow_engine.complete_run / fail_run as appropriate.

        On clean exit, updates run.total_steps to match the actual step
        count (the create_run estimate of 6 stages would otherwise
        understate the trajectory and confuse the UI progress bar).

        If TokenBudgetExceeded fires during a stage, writes a partial
        report artifact summarizing whatever stages completed before
        re-raising so the runner can call fail_run."""
        from sqlalchemy import update as _update
        log.info("agentic_run_start", run_id=self.run.run_id, workflow_id=self.workflow.workflow_id)
        try:
            for stage in STAGES:
                method = getattr(self, f"stage_{stage}")
                await method()
        except TokenBudgetExceeded as e:
            log.info("agentic_run_budget_exceeded", run_id=self.run.run_id, used=e.used, budget=e.budget)
            await self._write_partial_report(reason=f"token budget exceeded ({e.used}/{e.budget})")
            await self.session.execute(
                _update(WorkflowRuns)
                .where(WorkflowRuns.run_id == self.run.run_id)
                .values(total_steps=self._step_counter)
            )
            await self.session.commit()
            raise
        await self.session.execute(
            _update(WorkflowRuns)
            .where(WorkflowRuns.run_id == self.run.run_id)
            .values(total_steps=self._step_counter)
        )
        await self.session.commit()
        log.info(
            "agentic_run_complete",
            run_id=self.run.run_id,
            total_steps=self._step_counter,
            tokens=self.total_tokens_used,
            cache_read=self.total_cache_read_tokens,
        )

    async def _write_partial_report(self, *, reason: str) -> None:
        """Best-effort markdown summary of whatever stages completed.
        Saved as partial_report.md so the user has *something* to look
        at after a budgeted-out or timed-out run.

        Deterministic — no LLM call. Avoids charging more tokens after
        the budget was exhausted."""
        lines = [
            "# Partial Report",
            "",
            f"**Reason run did not complete:** {reason}",
            "",
            f"- Tokens used: {self.total_tokens_used}",
            f"- Cache reads: {self.total_cache_read_tokens}",
            "",
        ]
        if self.profile_summary:
            lines.append("## Tables loaded")
            for tname, info in self.profile_summary.items():
                shape = info.get("shape") or [0, 0]
                desc = info.get("description") or ""
                lines.append(f"- **{tname}** — {shape[0]} rows × {shape[1]} cols. {desc}")
            lines.append("")
        if self.analyze_findings:
            lines.append("## Findings (analyze stage)")
            for f in self.analyze_findings:
                lines.append(f"- {f}")
            lines.append("")
        if self.draft_report_path and os.path.exists(self.draft_report_path):
            lines.append("## Draft report (synthesize stage)")
            lines.append("")
            try:
                with open(self.draft_report_path, encoding="utf-8") as fh:
                    lines.append(fh.read())
            except OSError as e:
                lines.append(f"_(failed to read draft: {e})_")
        # Best-effort: swallow any error from artifact write so we don't
        # mask the original budget/timeout failure.
        try:
            await self._call_skill(
                "write_artifact",
                name="partial_report.md",
                content="\n".join(lines),
                kind="md",
            )
        except Exception as e:  # noqa: BLE001
            log.error("partial_report_write_failed", error=str(e))
