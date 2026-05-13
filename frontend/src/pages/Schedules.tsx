/**
 * Schedules cockpit — /app/schedules
 *
 * Lists every scheduled workflow visible to the caller under the standard
 * role-scope rule (own → group for managers/groupadmins → all for superuser).
 *
 * Sorted by next_fire so the most imminent jobs are visually the "background"
 * a user sees before adding new ones.
 */
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Container, Table, Button, Modal, Form, Alert } from "react-bootstrap";
import axiosClient from "../api/axiosClient";
import { useAuthStore } from "../stores/useAuthStore";
import EditScheduleModal from "../components/EditScheduleModal";

interface ScheduleListItem {
  workflow_id: number;
  workflow_name: string;
  user_id: number;
  user_email: string;
  type_id: number;
  type_long_name: string;
  enabled: boolean;
  schedule: Record<string, unknown>;
  summary: string;
  next_fires_utc: string[];
  last_run_at: string | null;
  last_run_id: number | null;
  latest_run_status: string | null;
}

function statusBadge(item: ScheduleListItem): { label: string; variant: string } {
  if (item.latest_run_status === "running") return { label: "Running", variant: "info" };
  if (item.enabled) return { label: "Active", variant: "success" };

  const kind = item.schedule.kind as string | undefined;
  if (kind === "one_time" && item.last_run_id != null) {
    if (item.latest_run_status === "completed") return { label: "Completed", variant: "success" };
    if (item.latest_run_status === "failed") return { label: "Failed", variant: "danger" };
    return { label: "Done", variant: "secondary" };
  }
  if (kind === "recurring") {
    const endsOn = item.schedule.ends_on as string | undefined;
    if (endsOn) {
      const todayLocalIso = new Date().toISOString().slice(0, 10);
      if (endsOn < todayLocalIso) return { label: "Expired", variant: "warning" };
    }
  }
  return { label: "Paused", variant: "secondary" };
}

interface WorkflowSummary {
  workflow_id: number;
  name: string;
  user_id: number;
  type_id: number;
  schedule: Record<string, unknown> | null;
  type?: { schedulable?: boolean; long_name?: string };
}

function formatFireTime(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString(undefined, {
    weekday: "short",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    timeZoneName: "short",
  });
}

export default function Schedules() {
  const navigate = useNavigate();
  const auth = useAuthStore();
  const [items, setItems] = useState<ScheduleListItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Modal state — editing an existing schedule
  const [editing, setEditing] = useState<ScheduleListItem | null>(null);

  // Modal state — picking a workflow to schedule
  const [showPicker, setShowPicker] = useState(false);
  const [pickerWorkflows, setPickerWorkflows] = useState<WorkflowSummary[] | null>(null);
  const [pickerError, setPickerError] = useState<string | null>(null);
  const [newScheduleTarget, setNewScheduleTarget] = useState<WorkflowSummary | null>(null);

  const fetchSchedules = () => {
    axiosClient
      .get<ScheduleListItem[]>("/schedules")
      .then((res) => { setItems(res.data); setError(null); })
      .catch((e: unknown) => {
        const err = e as { response?: { data?: { detail?: string } } };
        setError(err.response?.data?.detail || "Failed to load schedules.");
      });
  };

  useEffect(() => { fetchSchedules(); }, []);

  const openPicker = () => {
    setPickerError(null);
    setShowPicker(true);
    axiosClient
      .get<WorkflowSummary[]>("/workflows")
      .then((res) => {
        // Show only workflows the caller owns that are schedulable and not
        // already scheduled. Scheduling someone else's workflow from here
        // would be confusing; admins can still hit those via WorkflowDetail.
        const eligible = res.data.filter(
          (w) =>
            w.user_id === auth.user_id &&
            !w.schedule &&
            (w.type?.schedulable !== false)
        );
        setPickerWorkflows(eligible);
      })
      .catch((e: unknown) => {
        const err = e as { response?: { data?: { detail?: string } } };
        setPickerError(err.response?.data?.detail || "Failed to load workflows.");
      });
  };

  const togglePause = async (item: ScheduleListItem) => {
    await axiosClient.put(`/workflows/${item.workflow_id}`, { enabled: !item.enabled });
    fetchSchedules();
  };

  const cancelSchedule = async (item: ScheduleListItem) => {
    if (!confirm(`Clear the schedule for "${item.workflow_name}"? The workflow itself stays.`)) return;
    await axiosClient.put(`/workflows/${item.workflow_id}`, { schedule: null, enabled: false });
    fetchSchedules();
  };

  if (error) {
    return (
      <Container fluid className="p-4">
        <Alert variant="danger">{error}</Alert>
      </Container>
    );
  }

  return (
    <Container fluid className="p-4">
      <div className="d-flex justify-content-between align-items-center mb-3">
        <h3 className="mb-0">Schedules</h3>
        <Button variant="primary" onClick={openPicker}>+ Schedule a job</Button>
      </div>

      {items === null ? (
        <p className="text-muted">Loading…</p>
      ) : items.length === 0 ? (
        <Alert variant="info" className="small">
          No scheduled workflows yet. Click <strong>+ Schedule a job</strong> above, or open a workflow's detail page and add a schedule there.
        </Alert>
      ) : (
        <Table hover responsive>
          <thead>
            <tr>
              <th style={{ width: 56 }}>ID</th>
              <th>Workflow</th>
              <th>When</th>
              <th>Next fire</th>
              <th>Last run</th>
              <th>Owner</th>
              <th>Status</th>
              <th style={{ width: 280 }}>Actions</th>
            </tr>
          </thead>
          <tbody>
            {items.map((item) => (
              <tr
                key={item.workflow_id}
                style={item.enabled ? undefined : { opacity: 0.55 }}
              >
                <td className="text-muted small font-monospace">#{item.workflow_id}</td>
                <td>
                  <a
                    href={`/app/workflows/${item.workflow_id}`}
                    onClick={(e) => { e.preventDefault(); navigate(`/app/workflows/${item.workflow_id}`); }}
                  >
                    {item.workflow_name}
                  </a>
                  <div className="text-muted small">{item.type_long_name}</div>
                </td>
                <td className="small">{item.summary}</td>
                <td className="small">{formatFireTime(item.next_fires_utc[0] || null)}</td>
                <td className="small">
                  {item.last_run_id ? (
                    <a
                      href={`/app/runs/${item.last_run_id}`}
                      onClick={(e) => { e.preventDefault(); navigate(`/app/runs/${item.last_run_id}`); }}
                      className="font-monospace"
                    >
                      #{item.last_run_id}
                    </a>
                  ) : (
                    <span className="text-muted">never</span>
                  )}
                  {item.last_run_at && (
                    <div className="text-muted" style={{ fontSize: "0.75em" }}>
                      {new Date(item.last_run_at).toLocaleString()}
                    </div>
                  )}
                </td>
                <td className="small text-muted">{item.user_email}</td>
                <td>
                  {(() => {
                    const b = statusBadge(item);
                    return <span className={`badge bg-${b.variant}`}>{b.label}</span>;
                  })()}
                </td>
                <td>
                  <div className="d-flex gap-1">
                    <Button size="sm" variant="outline-primary" onClick={() => setEditing(item)}>
                      Edit
                    </Button>
                    <Button size="sm" variant="outline-secondary" onClick={() => togglePause(item)}>
                      {item.enabled ? "Pause" : "Resume"}
                    </Button>
                    <Button size="sm" variant="outline-danger" onClick={() => cancelSchedule(item)}>
                      Cancel
                    </Button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </Table>
      )}

      {/* Edit-an-existing-schedule modal */}
      {editing && (
        <EditScheduleModal
          show={true}
          workflowId={editing.workflow_id}
          workflowName={editing.workflow_name}
          currentSchedule={editing.schedule}
          onHide={() => setEditing(null)}
          onSaved={() => { setEditing(null); fetchSchedules(); }}
        />
      )}

      {/* New-schedule flow: workflow picker → modal */}
      <Modal show={showPicker} onHide={() => { setShowPicker(false); setNewScheduleTarget(null); }}>
        <Modal.Header closeButton>
          <Modal.Title>Schedule which workflow?</Modal.Title>
        </Modal.Header>
        <Modal.Body>
          {pickerError && <Alert variant="warning" className="small">{pickerError}</Alert>}
          {pickerWorkflows === null ? (
            <p className="text-muted">Loading…</p>
          ) : pickerWorkflows.length === 0 ? (
            <Alert variant="info" className="small mb-0">
              No workflows are available to schedule. Either you don't own any schedulable workflows, or all of yours already have schedules. Create one on the <a href="/app/workflows">Workflows page</a> first.
            </Alert>
          ) : (
            <Form.Group>
              <Form.Label>Pick one:</Form.Label>
              <div className="d-flex flex-column gap-1">
                {pickerWorkflows.map((w) => (
                  <Form.Check
                    key={w.workflow_id}
                    type="radio"
                    id={`pick-${w.workflow_id}`}
                    name="workflow-picker"
                    label={
                      <>
                        <strong>{w.name}</strong>
                        <span className="text-muted small ms-2">{w.type?.long_name}</span>
                      </>
                    }
                    checked={newScheduleTarget?.workflow_id === w.workflow_id}
                    onChange={() => setNewScheduleTarget(w)}
                  />
                ))}
              </div>
            </Form.Group>
          )}
        </Modal.Body>
        <Modal.Footer>
          <Button variant="secondary" onClick={() => { setShowPicker(false); setNewScheduleTarget(null); }}>
            Cancel
          </Button>
          <Button
            variant="primary"
            onClick={() => { setShowPicker(false); }}
            disabled={!newScheduleTarget}
          >
            Continue
          </Button>
        </Modal.Footer>
      </Modal>

      {newScheduleTarget && (
        <EditScheduleModal
          show={true}
          workflowId={newScheduleTarget.workflow_id}
          workflowName={newScheduleTarget.name}
          currentSchedule={null}
          onHide={() => setNewScheduleTarget(null)}
          onSaved={() => { setNewScheduleTarget(null); fetchSchedules(); }}
        />
      )}
    </Container>
  );
}
