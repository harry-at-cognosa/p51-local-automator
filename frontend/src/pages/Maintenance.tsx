import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Alert,
  Badge,
  Button,
  Col,
  Container,
  Form,
  Row,
  Table,
} from "react-bootstrap";
import axiosClient from "../api/axiosClient";

// Operation types
type Operation = "archive" | "purge";
type Scope = "all" | "group";

interface MaintenanceResult {
  workflows_affected: number;
  runs_affected: number;
  steps_affected: number;
  artifacts_affected: number;
  soft_deleted_workflows_included: number;
  bytes_freed: number | null;
  workflows_dropped: number;
}

interface MaintenanceLogRow {
  log_id: number;
  operation: string;
  user_id: number;
  user_name: string | null;
  scope: string;
  scope_group_id: number | null;
  scope_group_name: string | null;
  cutoff: string;
  workflows_affected: number;
  runs_affected: number;
  steps_affected: number;
  artifacts_affected: number;
  bytes_freed: number | null;
  error_detail: string | null;
  created_at: string;
}

interface Group {
  group_id: number;
  group_name: string;
}

const PURGE_CONFIRMATION_LITERAL = "PURGE";

function isoYesterday(): string {
  const d = new Date();
  d.setDate(d.getDate() - 1);
  return d.toISOString().slice(0, 10);
}

function formatBytes(b: number | null | undefined): string {
  if (b == null) return "—";
  if (b === 0) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let v = b;
  let i = 0;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i++;
  }
  return `${v.toFixed(v >= 10 || i === 0 ? 0 : 1)} ${units[i]}`;
}

export default function Maintenance() {
  const [operation, setOperation] = useState<Operation>("archive");
  const [scope, setScope] = useState<Scope>("all");
  const [groupId, setGroupId] = useState<number | null>(null);
  const [cutoff, setCutoff] = useState<string>(isoYesterday());
  const [confirmation, setConfirmation] = useState<string>("");

  const [groups, setGroups] = useState<Group[]>([]);
  const [preview, setPreview] = useState<MaintenanceResult | null>(null);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [committing, setCommitting] = useState(false);
  const [previewing, setPreviewing] = useState(false);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [history, setHistory] = useState<MaintenanceLogRow[]>([]);

  // Load groups for the scope=group dropdown and the history.
  useEffect(() => {
    axiosClient
      .get<Group[]>("/manage/groups")
      .then((res) => setGroups(res.data))
      .catch(() => setGroups([]));
    refreshHistory();
  }, []);

  const refreshHistory = useCallback(() => {
    axiosClient
      .get<MaintenanceLogRow[]>("/admin/maintenance/log")
      .then((res) => setHistory(res.data))
      .catch(() => setHistory([]));
  }, []);

  // Any change to inputs invalidates the preview.
  useEffect(() => {
    setPreview(null);
    setSuccessMsg(null);
    setErrorMsg(null);
    setConfirmation("");
  }, [operation, scope, groupId, cutoff]);

  const buildPayload = (dryRun: boolean) => ({
    scope,
    group_id: scope === "group" ? groupId : null,
    cutoff,
    dry_run: dryRun,
    ...(operation === "purge" && !dryRun
      ? { confirmation: confirmation }
      : {}),
  });

  const runPreview = async () => {
    setPreviewing(true);
    setPreviewError(null);
    setPreview(null);
    setSuccessMsg(null);
    setErrorMsg(null);
    try {
      const res = await axiosClient.post<MaintenanceResult>(
        `/admin/maintenance/${operation}`,
        buildPayload(true),
      );
      setPreview(res.data);
    } catch (err) {
      const detail =
        (err as { response?: { data?: { detail?: string } } }).response?.data
          ?.detail || "Preview failed.";
      setPreviewError(detail);
    } finally {
      setPreviewing(false);
    }
  };

  const commitNow = async () => {
    setCommitting(true);
    setSuccessMsg(null);
    setErrorMsg(null);
    try {
      const res = await axiosClient.post<MaintenanceResult>(
        `/admin/maintenance/${operation}`,
        buildPayload(false),
      );
      const r = res.data;
      const suffix =
        operation === "purge"
          ? ` (${formatBytes(r.bytes_freed)} freed${r.workflows_dropped ? `, ${r.workflows_dropped} workflows dropped` : ""})`
          : "";
      setSuccessMsg(
        `${operation === "archive" ? "Archived" : "Purged"} ${r.runs_affected} runs across ${r.workflows_affected} workflows${suffix}.`,
      );
      setPreview(null);
      setConfirmation("");
      refreshHistory();
    } catch (err) {
      const detail =
        (err as { response?: { data?: { detail?: string } } }).response?.data
          ?.detail || "Commit failed.";
      setErrorMsg(detail);
    } finally {
      setCommitting(false);
    }
  };

  const canCommit = useMemo(() => {
    if (!preview || committing) return false;
    if (scope === "group" && groupId == null) return false;
    if (operation === "purge" && confirmation !== PURGE_CONFIRMATION_LITERAL)
      return false;
    return true;
  }, [preview, committing, scope, groupId, operation, confirmation]);

  return (
    <Container fluid className="p-4">
      <div className="mb-4">
        <h3 className="mb-1">Maintenance</h3>
        <p className="text-muted mb-0" style={{ fontSize: "0.9rem" }}>
          Archive or purge old workflow runs. Archive is reversible (hides
          runs from non-superuser views). Purge is irreversible (drops DB
          rows and on-disk files). All sweeps automatically include runs
          from soft-deleted workflows, regardless of date.
        </p>
      </div>

      <Row className="g-3 mb-4">
        <Col md={3}>
          <Form.Group>
            <Form.Label>Operation</Form.Label>
            <div>
              <Form.Check
                inline
                type="radio"
                name="op"
                label="Archive"
                checked={operation === "archive"}
                onChange={() => setOperation("archive")}
              />
              <Form.Check
                inline
                type="radio"
                name="op"
                label="Purge"
                checked={operation === "purge"}
                onChange={() => setOperation("purge")}
              />
            </div>
          </Form.Group>
        </Col>

        <Col md={3}>
          <Form.Group>
            <Form.Label>Scope</Form.Label>
            <div>
              <Form.Check
                inline
                type="radio"
                name="scope"
                label="All groups"
                checked={scope === "all"}
                onChange={() => {
                  setScope("all");
                  setGroupId(null);
                }}
              />
              <Form.Check
                inline
                type="radio"
                name="scope"
                label="One group"
                checked={scope === "group"}
                onChange={() => setScope("group")}
              />
            </div>
          </Form.Group>
        </Col>

        <Col md={3}>
          <Form.Group>
            <Form.Label>Group</Form.Label>
            <Form.Select
              value={groupId ?? ""}
              onChange={(e) =>
                setGroupId(e.target.value ? Number(e.target.value) : null)
              }
              disabled={scope !== "group"}
            >
              <option value="">— select a group —</option>
              {groups.map((g) => (
                <option key={g.group_id} value={g.group_id}>
                  {g.group_id} — {g.group_name}
                </option>
              ))}
            </Form.Select>
          </Form.Group>
        </Col>

        <Col md={3}>
          <Form.Group>
            <Form.Label>Cutoff date</Form.Label>
            <Form.Control
              type="date"
              value={cutoff}
              onChange={(e) => setCutoff(e.target.value)}
            />
            <Form.Text className="text-muted">
              Runs with started_at before this date are eligible.
            </Form.Text>
          </Form.Group>
        </Col>
      </Row>

      <div className="mb-3">
        <Button
          variant="outline-primary"
          onClick={runPreview}
          disabled={previewing || (scope === "group" && groupId == null)}
        >
          {previewing ? "Previewing…" : "Preview"}
        </Button>
      </div>

      {previewError && (
        <Alert variant="danger" className="mb-3">
          {previewError}
        </Alert>
      )}

      {preview && (
        <div className="border rounded p-3 mb-3 bg-light">
          <div className="mb-2">
            Would {operation} {preview.runs_affected} runs across{" "}
            {preview.workflows_affected} workflows
            {preview.soft_deleted_workflows_included > 0 && (
              <>
                {" "}
                (including {preview.soft_deleted_workflows_included}{" "}
                soft-deleted workflows, all their runs auto-included)
              </>
            )}
            .
          </div>
          <div className="text-muted small">
            Steps: {preview.steps_affected} &nbsp;·&nbsp; Artifacts:{" "}
            {preview.artifacts_affected}
            {operation === "purge" && (
              <>
                {" "}
                &nbsp;·&nbsp; Bytes to free: {formatBytes(preview.bytes_freed)}{" "}
                &nbsp;·&nbsp; Workflows to drop:{" "}
                {preview.workflows_dropped}
              </>
            )}
          </div>
        </div>
      )}

      {preview && operation === "purge" && (
        <Form.Group className="mb-3" style={{ maxWidth: 360 }}>
          <Form.Label>
            Type <code>{PURGE_CONFIRMATION_LITERAL}</code> to confirm
          </Form.Label>
          <Form.Control
            type="text"
            value={confirmation}
            onChange={(e) => setConfirmation(e.target.value)}
            placeholder={PURGE_CONFIRMATION_LITERAL}
          />
        </Form.Group>
      )}

      {preview && (
        <div className="mb-4">
          <Button
            variant={operation === "purge" ? "danger" : "primary"}
            onClick={commitNow}
            disabled={!canCommit}
          >
            {committing
              ? "Committing…"
              : operation === "purge"
                ? "Commit Purge"
                : "Commit Archive"}
          </Button>
        </div>
      )}

      {successMsg && (
        <Alert variant="success" className="mb-3">
          {successMsg}
        </Alert>
      )}
      {errorMsg && (
        <Alert variant="danger" className="mb-3">
          {errorMsg}
        </Alert>
      )}

      <h5 className="mt-5 mb-3">Maintenance history</h5>
      {history.length === 0 ? (
        <p className="text-muted small">No maintenance actions yet.</p>
      ) : (
        <Table striped bordered hover size="sm">
          <thead>
            <tr>
              <th>When</th>
              <th>Op</th>
              <th>User</th>
              <th>Scope</th>
              <th>Cutoff</th>
              <th className="text-end">Workflows</th>
              <th className="text-end">Runs</th>
              <th className="text-end">Steps</th>
              <th className="text-end">Artifacts</th>
              <th className="text-end">Bytes freed</th>
              <th>Error</th>
            </tr>
          </thead>
          <tbody>
            {history.map((r) => (
              <tr key={r.log_id}>
                <td>{new Date(r.created_at).toLocaleString()}</td>
                <td>
                  <Badge bg={r.operation === "purge" ? "danger" : "secondary"}>
                    {r.operation}
                  </Badge>
                </td>
                <td>{r.user_name || r.user_id}</td>
                <td>
                  {r.scope === "all"
                    ? "all"
                    : `group ${r.scope_group_id}${r.scope_group_name ? " — " + r.scope_group_name : ""}`}
                </td>
                <td>{new Date(r.cutoff).toISOString().slice(0, 10)}</td>
                <td className="text-end">{r.workflows_affected}</td>
                <td className="text-end">{r.runs_affected}</td>
                <td className="text-end">{r.steps_affected}</td>
                <td className="text-end">{r.artifacts_affected}</td>
                <td className="text-end">{formatBytes(r.bytes_freed)}</td>
                <td className="text-danger small">{r.error_detail || ""}</td>
              </tr>
            ))}
          </tbody>
        </Table>
      )}
    </Container>
  );
}
