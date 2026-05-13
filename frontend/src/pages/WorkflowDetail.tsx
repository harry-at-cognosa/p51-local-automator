import { useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import {
  Container, Card, Button, Badge, Table, Alert, Spinner,
  Modal, Form,
} from "react-bootstrap";
import axiosClient from "../api/axiosClient";
import WorkflowConfigForm from "../components/WorkflowConfigForm";
import StatusBadge from "../components/StatusBadge";
import EditScheduleModal from "../components/EditScheduleModal";
import { useAuthStore } from "../stores/useAuthStore";

interface WorkflowCategoryNested {
  category_id: number;
  short_name: string;
  long_name: string;
}

interface WorkflowTypeNested {
  type_id: number;
  type_name?: string;
  short_name: string;
  long_name: string;
  category: WorkflowCategoryNested;
  config_schema?: unknown[] | null;
  schedulable?: boolean;
}

interface UserWorkflow {
  workflow_id: number;
  user_id: number;
  group_id: number;
  type_id: number;
  name: string;
  config: Record<string, unknown>;
  schedule: Record<string, unknown> | null;
  enabled: boolean;
  last_run_at: string | null;
  created_at: string;
  type: WorkflowTypeNested | null;
}

interface WorkflowRun {
  run_id: number;
  workflow_id: number;
  status: string;
  current_step: number;
  total_steps: number;
  trigger: string;
  started_at: string;
  completed_at: string | null;
  error_detail: string | null;
  artifact_count: number;
  archived: boolean;
}

const DAY_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

function scheduleSummary(
  schedule: Record<string, unknown> | null,
  enabled: boolean,
): string {
  if (!schedule) return "Not scheduled — runs only via Run Now or API.";
  const kind = schedule.kind as string | undefined;
  const tz = (schedule.tz as string | undefined) || "UTC";
  const status = enabled ? "" : " (paused)";

  if (kind === "one_time") {
    const at = schedule.at_local as string | undefined;
    return `One-time: ${at} ${tz}. Auto-disables after firing.${status}`;
  }

  // recurring (or legacy {hour, minute})
  const hour = (schedule.hour as number | undefined) ?? 0;
  const minute = (schedule.minute as number | undefined) ?? 0;
  const days = (schedule.days_of_week as number[] | undefined) ?? [0, 1, 2, 3, 4, 5, 6];
  const interval = (schedule.week_interval as number | undefined) ?? 1;
  const startsOn = schedule.starts_on as string | undefined;
  const endsOn = schedule.ends_on as string | undefined;

  let dayPart: string;
  if (JSON.stringify(days) === JSON.stringify([0, 1, 2, 3, 4])) dayPart = "Workdays";
  else if (JSON.stringify(days) === JSON.stringify([0, 1, 2, 3, 4, 5, 6])) dayPart = "Every day";
  else dayPart = days.map((d) => DAY_LABELS[d]).join(", ");

  const every = interval > 1 ? `Every ${interval} weeks on ` : "";
  const hh = String(hour).padStart(2, "0");
  const mm = String(minute).padStart(2, "0");
  const range = startsOn && endsOn ? ` From ${startsOn} until ${endsOn}.` : "";
  return `${every}${dayPart} at ${hh}:${mm} ${tz}.${range}${status}`;
}

export default function WorkflowDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { is_superuser } = useAuthStore();
  const [workflow, setWorkflow] = useState<UserWorkflow | null>(null);
  const [runs, setRuns] = useState<WorkflowRun[]>([]);
  const [showArchived, setShowArchived] = useState(false);
  const [running, setRunning] = useState(false);
  const [runMessage, setRunMessage] = useState("");
  const [showConfig, setShowConfig] = useState(false);
  const [editConfig, setEditConfig] = useState<Record<string, unknown>>({});
  const [editName, setEditName] = useState("");
  const [editingName, setEditingName] = useState(false);
  const [nameValue, setNameValue] = useState("");
  const [pendingCount, setPendingCount] = useState<number | null>(null);
  const [showSchedule, setShowSchedule] = useState(false);

  const fetchData = () => {
    axiosClient.get(`/workflows/${id}`).then((res) => {
      setWorkflow(res.data);
      // Only type-6 (Approve Before Send) workflows have a pending queue.
      // Fetch count to drive the Pending-replies button's appearance.
      if (res.data?.type_id === 6) {
        axiosClient
          .get(`/workflows/${id}/pending-replies`)
          .then((r) => setPendingCount(Array.isArray(r.data) ? r.data.length : 0))
          .catch(() => setPendingCount(0));
      } else {
        setPendingCount(null);
      }
    });
    const runsUrl =
      showArchived && is_superuser
        ? `/workflows/${id}/runs?include_archived=true`
        : `/workflows/${id}/runs`;
    axiosClient.get(runsUrl).then((res) => setRuns(res.data));
  };

  useEffect(() => { fetchData(); }, [id, showArchived]);

  const triggerRun = async () => {
    setRunning(true);
    setRunMessage("");
    try {
      const res = await axiosClient.post(`/workflows/${id}/run`);
      setRunMessage(res.data.detail);
      // Poll for completion
      const poll = setInterval(async () => {
        const pollUrl =
          showArchived && is_superuser
            ? `/workflows/${id}/runs?include_archived=true`
            : `/workflows/${id}/runs`;
        const runsRes = await axiosClient.get(pollUrl);
        setRuns(runsRes.data);
        const latest = runsRes.data[0];
        if (latest && (latest.status === "completed" || latest.status === "failed")) {
          clearInterval(poll);
          setRunning(false);
          // Refresh workflow to get updated last_run_at
          axiosClient.get(`/workflows/${id}`).then((res) => setWorkflow(res.data));
        }
      }, 3000);
    } catch (err: unknown) {
      // F5: a 409 means another active run already exists for this
      // workflow_id. Surface the backend's detail message verbatim — it
      // includes the existing run_id so the user can navigate to it.
      const e = err as { response?: { status?: number; data?: { detail?: string } } };
      if (e.response?.status === 409 && e.response.data?.detail) {
        setRunMessage(e.response.data.detail);
      } else {
        setRunMessage("Failed to trigger run");
      }
      setRunning(false);
    }
  };

  const isEditNameValid = editName.trim().length >= 1 && editName.trim().length <= 200;

  const saveConfig = async () => {
    if (!isEditNameValid) return;
    try {
      await axiosClient.put(`/workflows/${id}`, { name: editName.trim(), config: editConfig });
      setShowConfig(false);
      fetchData();
    } catch {
      alert("Failed to save workflow.");
    }
  };

  const deleteWorkflow = async () => {
    if (!confirm("Delete this workflow?")) return;
    await axiosClient.delete(`/workflows/${id}`);
    navigate("/app/workflows");
  };

  if (!workflow) return <Container className="p-4"><Spinner animation="border" /></Container>;

  return (
    <Container fluid className="p-4">
      <div className="d-flex justify-content-between align-items-start mb-4">
        <div>
          <div className="text-muted small mb-1" style={{ fontSize: "0.85rem" }}>
            {workflow.type ? (
              <>
                <strong>Category:</strong> {workflow.type.category.short_name}
                {" "}&middot;{" "}
                <strong>Type:</strong> {workflow.type.short_name}
                {" "}&middot;{" "}
              </>
            ) : null}
            <strong>Created</strong> {new Date(workflow.created_at).toLocaleDateString()}
            {workflow.last_run_at && (
              <> &middot; <strong>Last run</strong> {new Date(workflow.last_run_at).toLocaleString()}</>
            )}
          </div>
          {editingName ? (
            <div className="d-flex gap-2 align-items-center">
              <span className="text-muted small">User Workflow Name:</span>
              <Form.Control
                value={nameValue}
                onChange={(e) => setNameValue(e.target.value)}
                autoFocus
                style={{ fontSize: "1rem", width: 400 }}
                onKeyDown={async (e) => {
                  if (e.key === "Enter") {
                    await axiosClient.put(`/workflows/${id}`, { name: nameValue });
                    setEditingName(false);
                    fetchData();
                  }
                  if (e.key === "Escape") setEditingName(false);
                }}
              />
              <Button size="sm" variant="success" onClick={async () => {
                await axiosClient.put(`/workflows/${id}`, { name: nameValue });
                setEditingName(false);
                fetchData();
              }}>Save</Button>
              <Button size="sm" variant="secondary" onClick={() => setEditingName(false)}>Cancel</Button>
            </div>
          ) : (
            <div
              style={{ cursor: "pointer" }}
              onClick={() => { setNameValue(workflow.name); setEditingName(true); }}
            >
              <span className="text-muted small me-2">User Workflow Name:</span>
              <span style={{ fontSize: "1.1rem", fontWeight: 500 }}>{workflow.name}</span>
              <span className="text-muted ms-2" style={{ fontSize: "0.8rem" }}>click to edit</span>
            </div>
          )}
        </div>
        <div className="d-flex gap-2">
          {workflow.type_id === 6 && (
            <Button
              variant={pendingCount && pendingCount > 0 ? "warning" : "outline-secondary"}
              disabled={pendingCount === 0}
              onClick={() => navigate(`/app/workflows/${id}/pending-replies`)}
              title={
                pendingCount === null
                  ? "Loading…"
                  : pendingCount === 0
                    ? "No pending replies — run the workflow to queue new candidates"
                    : `${pendingCount} pending reply/replies awaiting your approval`
              }
            >
              Pending replies
              {pendingCount !== null && pendingCount > 0 && (
                <Badge bg="dark" className="ms-2">{pendingCount}</Badge>
              )}
            </Button>
          )}
          <Button
            variant="success"
            onClick={triggerRun}
            disabled={running}
          >
            {running ? <><Spinner size="sm" animation="border" className="me-1" /> Running...</> : "Run Now"}
          </Button>
          <Button
            variant="outline-secondary"
            onClick={() => {
              setEditConfig({ ...workflow.config });
              setEditName(workflow.name);
              setShowConfig(true);
            }}
          >
            Edit Config
          </Button>
          <Button variant="outline-danger" onClick={deleteWorkflow}>Delete</Button>
        </div>
      </div>

      {runMessage && <Alert variant="info" dismissible onClose={() => setRunMessage("")}>{runMessage}</Alert>}

      <Card>
        <Card.Header>Configuration</Card.Header>
        <Card.Body>
          <pre
            className="mb-0"
            style={{ fontSize: "0.85em", whiteSpace: "pre-wrap", wordBreak: "break-word" }}
          >
            {JSON.stringify(workflow.config, null, 2)}
          </pre>
        </Card.Body>
      </Card>

      <Card className="mt-3">
        <Card.Header>Pipeline Steps</Card.Header>
        <Card.Body className="py-2">
          {(() => {
            const stepsByType: Record<number, string[]> = {
              1: ["Fetch emails via MCP", "Categorize with AI", "Generate Excel report"],
              2: ["Analyze data (profile, filter, chart, quality)"],
              3: ["Fetch calendar events via MCP", "Analyze with AI (conflicts, importance)"],
              4: ["Execute SQL query", "Analyze results with AI"],
            };
            const steps = stepsByType[workflow.type_id] || ["Run workflow"];
            return (
              <ol className="mb-0 ps-3" style={{ fontSize: "0.85em" }}>
                {steps.map((s, i) => <li key={i} className="text-muted">{s}</li>)}
              </ol>
            );
          })()}
        </Card.Body>
      </Card>

      {workflow.type?.schedulable !== false && (
        <Card className="mt-3">
          <Card.Header className="d-flex justify-content-between align-items-center">
            <span>Schedule</span>
            <Button size="sm" variant="outline-primary" onClick={() => setShowSchedule(true)}>
              {workflow.schedule ? "Edit" : "Add schedule"}
            </Button>
          </Card.Header>
          <Card.Body className="small">
            {scheduleSummary(workflow.schedule, workflow.enabled)}
          </Card.Body>
        </Card>
      )}

      {showSchedule && (
        <EditScheduleModal
          show={true}
          workflowId={workflow.workflow_id}
          workflowName={workflow.name}
          currentSchedule={workflow.schedule}
          onHide={() => setShowSchedule(false)}
          onSaved={() => { setShowSchedule(false); fetchData(); }}
        />
      )}

      <Card className="mt-3">
        <Card.Header className="d-flex justify-content-between align-items-center">
          <span>Run History</span>
          {is_superuser && (
            <Form.Check
              type="switch"
              id="show-archived-runs"
              label="Show archived"
              checked={showArchived}
              onChange={(e) => setShowArchived(e.target.checked)}
              className="small text-muted"
            />
          )}
        </Card.Header>
        <Card.Body className="p-0">
          {runs.length === 0 ? (
            <p className="text-muted p-3 mb-0">No runs yet. Click "Run Now" to start.</p>
          ) : (
            <Table hover className="mb-0">
              <thead>
                <tr>
                  <th>Run</th>
                  <th>Status</th>
                  <th>Steps</th>
                  <th>Trigger</th>
                  <th>Started</th>
                  <th>Duration</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {runs.map((r) => {
                  const duration = r.completed_at
                    ? Math.round((new Date(r.completed_at).getTime() - new Date(r.started_at).getTime()) / 1000)
                    : null;
                  return (
                    <tr
                      key={r.run_id}
                      style={r.archived ? { opacity: 0.55, fontStyle: "italic" } : undefined}
                    >
                      <td>
                        #{r.run_id}
                        {r.archived && (
                          <Badge bg="secondary" className="ms-2" pill style={{ fontSize: "0.65rem" }}>
                            archived
                          </Badge>
                        )}
                      </td>
                      <td><StatusBadge status={r.status} /></td>
                      <td>{r.current_step}/{r.total_steps}</td>
                      <td><Badge bg="light" text="dark">{r.trigger}</Badge></td>
                      <td>{new Date(r.started_at).toLocaleString()}</td>
                      <td>{duration !== null ? `${duration}s` : <Spinner size="sm" animation="border" />}</td>
                      <td>
                        <Button
                          size="sm"
                          variant="outline-primary"
                          title={r.artifact_count === 0 ? "Step + status info; no file artifacts produced" : `${r.artifact_count} artifact(s)`}
                          onClick={() => navigate(`/app/runs/${r.run_id}`)}
                        >
                          Details
                        </Button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </Table>
          )}
        </Card.Body>
      </Card>

      <Modal show={showConfig} onHide={() => setShowConfig(false)} size="lg">
        <Modal.Header closeButton>
          <Modal.Title>Edit Configuration</Modal.Title>
        </Modal.Header>
        <Modal.Body>
          <Form.Group className="mb-3">
            <Form.Label>Name</Form.Label>
            <Form.Control
              type="text"
              value={editName}
              maxLength={200}
              isInvalid={!isEditNameValid}
              onChange={(e) => setEditName(e.target.value)}
            />
            <Form.Control.Feedback type="invalid">
              Name is required (up to 200 characters).
            </Form.Control.Feedback>
          </Form.Group>
          <hr />
          <h6 className="mb-3">Configuration</h6>
          <WorkflowConfigForm
            typeId={workflow.type_id}
            config={editConfig}
            onChange={setEditConfig}
            configSchema={
              (workflow.type?.config_schema as
                | import("../components/SchemaConfigForm").FieldDescriptor[]
                | undefined) ?? null
            }
          />
        </Modal.Body>
        <Modal.Footer>
          <Button variant="secondary" onClick={() => setShowConfig(false)}>Cancel</Button>
          <Button variant="primary" onClick={saveConfig} disabled={!isEditNameValid}>Save</Button>
        </Modal.Footer>
      </Modal>
    </Container>
  );
}
