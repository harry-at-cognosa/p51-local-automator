/**
 * Job status derivation for a workflow's schedule.
 *
 * "Job status" answers "will this schedule fire again?", which is a different
 * question from "how did the last run go?" (that's run status, rendered by
 * <StatusBadge>). A workflow can have a green "completed" run status and an
 * "Expired" job status at the same time — exactly the state every scheduled
 * workflow on this box landed in after its `ends_on` lapsed.
 *
 * Note the ordering: `expired` is tested BEFORE `enabled`. The scheduler's
 * sweep flips `enabled` to false when a schedule lapses, but only on its next
 * pass, so an enabled-but-lapsed schedule exists for up to a day. Testing
 * enabled first (as Schedules.tsx statusBadge currently does) labels that
 * window "Active" even though nothing will fire.
 */

export type JobStatus = "active" | "expired" | "paused" | "unscheduled";

export const JOB_STATUS_LABELS: Record<JobStatus, string> = {
  active: "Active",
  expired: "Expired",
  paused: "Paused",
  unscheduled: "—",
};

export const JOB_STATUS_VARIANTS: Record<JobStatus, string> = {
  active: "success",
  expired: "warning",
  paused: "secondary",
  unscheduled: "light text-dark",
};

/** Now as YYYY-MM-DDTHH:MM in the *browser's* timezone.
 *  `new Date().toISOString()` is UTC and reads a day ahead for Pacific
 *  evenings, which would expire a schedule several hours early. */
function nowLocalIso(): string {
  const d = new Date();
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}` +
    `T${p(d.getHours())}:${p(d.getMinutes())}`;
}

/**
 * @param schedule the raw `schedule` JSON from the API, or null/undefined
 * @param enabled  the workflow's `enabled` flag
 */
export function jobStatus(
  schedule: Record<string, unknown> | null | undefined,
  enabled: boolean,
): JobStatus {
  if (!schedule) return "unscheduled";

  const kind = schedule.kind as string | undefined;

  if (kind === "recurring") {
    // ends_on is inclusive, so a schedule is live through the end of that day.
    const endsOn = schedule.ends_on as string | undefined;
    if (endsOn && endsOn < nowLocalIso().slice(0, 10)) return "expired";
  } else if (kind === "one_time") {
    // at_local is an offset-less local ISO datetime — compare it against a
    // local-frame string, never against toISOString() (which is UTC).
    const atLocal = schedule.at_local as string | undefined;
    if (atLocal && atLocal.slice(0, 16) < nowLocalIso()) return "expired";
  }

  return enabled ? "active" : "paused";
}
