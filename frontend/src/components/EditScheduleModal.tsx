/**
 * Edit Schedule modal — used from both WorkflowDetail and the Schedules page.
 *
 * Schedule shapes mirror backend/services/schedule.py:
 *   { kind: "one_time", at_local, tz }
 *   { kind: "recurring", starts_on, ends_on, hour, minute, tz,
 *     days_of_week, week_interval }
 *
 * The form is local-time + browser-detected IANA TZ. The backend converts
 * to UTC at fire time so DST transitions don't drift the user's intent.
 */
import { useEffect, useRef, useState } from "react";
import { Modal, Button, Form, Row, Col, Alert } from "react-bootstrap";
import axiosClient from "../api/axiosClient";

type Mode = "none" | "one_time" | "recurring";
type Frequency = "workdays" | "every_day" | "specific_days" | "every_n_weeks";

interface Props {
  show: boolean;
  workflowId: number;
  workflowName: string;
  currentSchedule: Record<string, unknown> | null;
  onHide: () => void;
  onSaved: () => void;
}

interface PreviewResponse {
  summary: string;
  next_fires_utc: string[];
}

const BROWSER_TZ = Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
const TZ_ABBR = new Intl.DateTimeFormat("en-US", { timeZoneName: "short" })
  .formatToParts(new Date())
  .find((p) => p.type === "timeZoneName")?.value || BROWSER_TZ;

const DAY_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

function todayLocalISO(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function addYearISO(isoDate: string, years: number): string {
  const d = new Date(isoDate + "T00:00");
  d.setFullYear(d.getFullYear() + years);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function deriveModeFromSchedule(s: Record<string, unknown> | null): {
  mode: Mode;
  freq: Frequency;
} {
  if (!s) return { mode: "none", freq: "workdays" };
  const kind = s.kind as string | undefined;
  if (kind === "one_time") return { mode: "one_time", freq: "workdays" };
  // recurring (or legacy)
  const days = (s.days_of_week as number[] | undefined) ?? [0, 1, 2, 3, 4, 5, 6];
  const interval = (s.week_interval as number | undefined) ?? 1;
  if (interval > 1) return { mode: "recurring", freq: "every_n_weeks" };
  if (JSON.stringify(days) === JSON.stringify([0, 1, 2, 3, 4])) {
    return { mode: "recurring", freq: "workdays" };
  }
  if (JSON.stringify(days) === JSON.stringify([0, 1, 2, 3, 4, 5, 6])) {
    return { mode: "recurring", freq: "every_day" };
  }
  return { mode: "recurring", freq: "specific_days" };
}

export default function EditScheduleModal({
  show,
  workflowId,
  workflowName,
  currentSchedule,
  onHide,
  onSaved,
}: Props) {
  const initial = deriveModeFromSchedule(currentSchedule);

  const [mode, setMode] = useState<Mode>(initial.mode);
  const [frequency, setFrequency] = useState<Frequency>(initial.freq);

  // one_time fields
  const [oneTimeDate, setOneTimeDate] = useState<string>(
    (currentSchedule?.at_local as string | undefined)?.slice(0, 10) || todayLocalISO()
  );
  const [oneTimeTime, setOneTimeTime] = useState<string>(
    (currentSchedule?.at_local as string | undefined)?.slice(11, 16) || "08:00"
  );

  // recurring fields
  const [hour, setHour] = useState<number>((currentSchedule?.hour as number | undefined) ?? 8);
  const [minute, setMinute] = useState<number>((currentSchedule?.minute as number | undefined) ?? 0);
  const [days, setDays] = useState<number[]>(
    (currentSchedule?.days_of_week as number[] | undefined) ?? [0, 1, 2, 3, 4]
  );
  const [weekInterval, setWeekInterval] = useState<number>(
    (currentSchedule?.week_interval as number | undefined) ?? 1
  );
  const [startsOn, setStartsOn] = useState<string>(
    (currentSchedule?.starts_on as string | undefined) || todayLocalISO()
  );
  const [endsOn, setEndsOn] = useState<string>(
    (currentSchedule?.ends_on as string | undefined) || addYearISO(todayLocalISO(), 1)
  );

  const [preview, setPreview] = useState<PreviewResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  // Reset form when modal re-opens with a different schedule
  useEffect(() => {
    if (!show) return;
    const d = deriveModeFromSchedule(currentSchedule);
    setMode(d.mode);
    setFrequency(d.freq);
    setError(null);
    setPreview(null);
  }, [show, currentSchedule]);

  // Build the schedule dict the backend expects, given current form state
  function buildSchedule(): Record<string, unknown> | null {
    if (mode === "none") return null;
    if (mode === "one_time") {
      return {
        kind: "one_time",
        at_local: `${oneTimeDate}T${oneTimeTime}`,
        tz: BROWSER_TZ,
      };
    }
    // recurring
    let dow = days;
    let interval = 1;
    if (frequency === "workdays") {
      dow = [0, 1, 2, 3, 4];
    } else if (frequency === "every_day") {
      dow = [0, 1, 2, 3, 4, 5, 6];
    } else if (frequency === "every_n_weeks") {
      interval = weekInterval;
    }
    return {
      kind: "recurring",
      starts_on: startsOn,
      ends_on: endsOn,
      hour,
      minute,
      tz: BROWSER_TZ,
      days_of_week: dow,
      week_interval: interval,
    };
  }

  // Debounced preview refresh
  const previewTimer = useRef<number | undefined>(undefined);
  useEffect(() => {
    if (!show || mode === "none") {
      setPreview(null);
      return;
    }
    const sched = buildSchedule();
    if (!sched) return;

    if (previewTimer.current) window.clearTimeout(previewTimer.current);
    previewTimer.current = window.setTimeout(async () => {
      try {
        const res = await axiosClient.post<PreviewResponse>(
          `/workflows/${workflowId}/schedule/preview`,
          { schedule: sched, count: 5 }
        );
        setPreview(res.data);
        setError(null);
      } catch (e: unknown) {
        const err = e as { response?: { data?: { detail?: string } } };
        setPreview(null);
        setError(err.response?.data?.detail || "Invalid schedule shape.");
      }
    }, 250);

    return () => {
      if (previewTimer.current) window.clearTimeout(previewTimer.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [show, mode, frequency, oneTimeDate, oneTimeTime, hour, minute, days, weekInterval, startsOn, endsOn]);

  const handleSave = async () => {
    setSaving(true);
    setError(null);
    try {
      await axiosClient.put(`/workflows/${workflowId}`, {
        schedule: buildSchedule(),
        enabled: mode !== "none",
      });
      onSaved();
      onHide();
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } } };
      setError(err.response?.data?.detail || "Save failed.");
    } finally {
      setSaving(false);
    }
  };

  const toggleDay = (d: number) => {
    setDays((cur) => (cur.includes(d) ? cur.filter((x) => x !== d) : [...cur, d].sort()));
  };

  return (
    <Modal show={show} onHide={onHide} size="lg">
      <Modal.Header closeButton>
        <Modal.Title>Schedule: {workflowName}</Modal.Title>
      </Modal.Header>
      <Modal.Body>
        <Form.Group className="mb-3">
          <Form.Label className="fw-bold">Mode</Form.Label>
          <div className="d-flex gap-3">
            <Form.Check
              type="radio"
              id="mode-none"
              label="Not scheduled"
              checked={mode === "none"}
              onChange={() => setMode("none")}
            />
            <Form.Check
              type="radio"
              id="mode-one-time"
              label="One-time"
              checked={mode === "one_time"}
              onChange={() => setMode("one_time")}
            />
            <Form.Check
              type="radio"
              id="mode-recurring"
              label="Recurring"
              checked={mode === "recurring"}
              onChange={() => setMode("recurring")}
            />
          </div>
        </Form.Group>

        {mode === "none" && (
          <Alert variant="secondary" className="small mb-0">
            No schedule. The workflow will run only when you click <strong>Run Now</strong> or trigger it via API.
          </Alert>
        )}

        {mode === "one_time" && (
          <>
            <hr />
            <Row className="g-3 align-items-end">
              <Col md={4}>
                <Form.Group>
                  <Form.Label>Date</Form.Label>
                  <Form.Control
                    type="date"
                    value={oneTimeDate}
                    onChange={(e) => setOneTimeDate(e.target.value)}
                    min={todayLocalISO()}
                    max={addYearISO(todayLocalISO(), 1)}
                  />
                </Form.Group>
              </Col>
              <Col md={3}>
                <Form.Group>
                  <Form.Label>Time</Form.Label>
                  <Form.Control
                    type="time"
                    value={oneTimeTime}
                    onChange={(e) => setOneTimeTime(e.target.value)}
                  />
                </Form.Group>
              </Col>
              <Col md={5} className="text-muted small pb-2">
                Your local time ({TZ_ABBR})
              </Col>
            </Row>
            <Form.Text className="text-muted">
              The schedule will auto-disable after this run completes.
            </Form.Text>
          </>
        )}

        {mode === "recurring" && (
          <>
            <hr />
            <Row className="g-3">
              <Col md={6}>
                <Form.Group>
                  <Form.Label>Frequency</Form.Label>
                  <Form.Select value={frequency} onChange={(e) => setFrequency(e.target.value as Frequency)}>
                    <option value="workdays">Workdays (Mon–Fri)</option>
                    <option value="every_day">Every day</option>
                    <option value="specific_days">Specific days of week</option>
                    <option value="every_n_weeks">Every N weeks on specific day(s)</option>
                  </Form.Select>
                </Form.Group>
              </Col>
              <Col md={3}>
                <Form.Group>
                  <Form.Label>Time</Form.Label>
                  <Form.Control
                    type="time"
                    value={`${String(hour).padStart(2, "0")}:${String(minute).padStart(2, "0")}`}
                    onChange={(e) => {
                      const [h, m] = e.target.value.split(":").map(Number);
                      setHour(h); setMinute(m);
                    }}
                  />
                </Form.Group>
              </Col>
              <Col md={3} className="text-muted small pb-2 d-flex align-items-end">
                Your local time ({TZ_ABBR})
              </Col>
            </Row>

            {(frequency === "specific_days" || frequency === "every_n_weeks") && (
              <Form.Group className="mt-3">
                <Form.Label>Days of week</Form.Label>
                <div className="d-flex gap-3">
                  {DAY_LABELS.map((label, i) => (
                    <Form.Check
                      key={i}
                      type="checkbox"
                      id={`day-${i}`}
                      label={label}
                      checked={days.includes(i)}
                      onChange={() => toggleDay(i)}
                    />
                  ))}
                </div>
              </Form.Group>
            )}

            {frequency === "every_n_weeks" && (
              <Form.Group className="mt-3">
                <Form.Label>Repeat every</Form.Label>
                <div className="d-flex gap-2 align-items-center">
                  <Form.Select
                    value={weekInterval}
                    onChange={(e) => setWeekInterval(Number(e.target.value))}
                    style={{ width: 80 }}
                  >
                    <option value={2}>2</option>
                    <option value={3}>3</option>
                    <option value={4}>4</option>
                  </Form.Select>
                  <span>weeks (on the selected day(s) above)</span>
                </div>
              </Form.Group>
            )}

            <Row className="g-3 mt-1">
              <Col md={6}>
                <Form.Group>
                  <Form.Label>Start date</Form.Label>
                  <Form.Control
                    type="date"
                    value={startsOn}
                    onChange={(e) => setStartsOn(e.target.value)}
                    max={endsOn}
                  />
                </Form.Group>
              </Col>
              <Col md={6}>
                <Form.Group>
                  <Form.Label>End date <span className="text-muted small">(max 1 year out)</span></Form.Label>
                  <Form.Control
                    type="date"
                    value={endsOn}
                    onChange={(e) => setEndsOn(e.target.value)}
                    min={startsOn}
                    max={addYearISO(startsOn, 1)}
                  />
                </Form.Group>
              </Col>
            </Row>
          </>
        )}

        {error && <Alert variant="warning" className="mt-3 mb-0 small">{error}</Alert>}

        {mode !== "none" && preview && (
          <div className="mt-4">
            <h6 className="text-muted">Next fires</h6>
            <div className="small mb-1"><em>{preview.summary}</em></div>
            {preview.next_fires_utc.length === 0 ? (
              <div className="text-muted small">No upcoming fires — check the date range.</div>
            ) : (
              <ul className="small mb-0">
                {preview.next_fires_utc.map((iso, i) => (
                  <li key={i}>
                    {new Date(iso).toLocaleString(undefined, {
                      weekday: "short",
                      month: "short",
                      day: "numeric",
                      year: "numeric",
                      hour: "numeric",
                      minute: "2-digit",
                      timeZoneName: "short",
                    })}
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
      </Modal.Body>
      <Modal.Footer>
        <Button variant="secondary" onClick={onHide} disabled={saving}>
          Cancel
        </Button>
        <Button variant="primary" onClick={handleSave} disabled={saving || !!error}>
          {saving ? "Saving…" : "Save"}
        </Button>
      </Modal.Footer>
    </Modal>
  );
}
