import { useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { Container, Card, Badge, Table, Button, Spinner, Alert } from "react-bootstrap";
import axiosClient from "../api/axiosClient";

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
}

interface WorkflowStep {
  step_id: number;
  run_id: number;
  step_number: number;
  step_name: string;
  status: string;
  started_at: string | null;
  completed_at: string | null;
  output_summary: string | null;
  llm_tokens_used: number;
  error_detail: string | null;
}

interface WorkflowArtifact {
  artifact_id: number;
  run_id: number;
  step_id: number | null;
  file_path: string;
  file_type: string;
  file_size: number;
  description: string;
  created_at: string;
}

export default function RunDetail() {
  const { runId } = useParams();
  const navigate = useNavigate();
  const [run, setRun] = useState<WorkflowRun | null>(null);
  const [steps, setSteps] = useState<WorkflowStep[]>([]);
  const [artifacts, setArtifacts] = useState<WorkflowArtifact[]>([]);

  const [error, setError] = useState("");

  useEffect(() => {
    axiosClient.get(`/runs/${runId}`).then((res) => setRun(res.data)).catch((e) => setError(`Failed to load run: ${e.message}`));
    axiosClient.get(`/runs/${runId}/steps`).then((res) => setSteps(res.data)).catch(() => {});
    axiosClient.get(`/runs/${runId}/artifacts`).then((res) => setArtifacts(res.data)).catch(() => {});
  }, [runId]);

  const statusBadge = (status: string) => {
    const colors: Record<string, string> = {
      completed: "success",
      running: "primary",
      failed: "danger",
      pending: "secondary",
    };
    return <Badge bg={colors[status] || "secondary"}>{status}</Badge>;
  };

  const formatSize = (bytes: number) => {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  };

  const fileIcon = (type: string) => {
    const icons: Record<string, string> = {
      json: "{ }",
      xlsx: "XLS",
      csv: "CSV",
      png: "IMG",
      md: "MD",
    };
    return icons[type] || type.toUpperCase();
  };

  if (error) return <Container className="p-4"><Alert variant="danger">{error}</Alert></Container>;
  if (!run) return <Container className="p-4"><Spinner animation="border" /></Container>;

  const duration = run.completed_at
    ? Math.round((new Date(run.completed_at).getTime() - new Date(run.started_at).getTime()) / 1000)
    : null;

  const totalTokens = steps.reduce((sum, s) => sum + s.llm_tokens_used, 0);

  return (
    <Container fluid className="p-4">
      <Button variant="outline-secondary" size="sm" className="mb-3" onClick={() => navigate(`/app/workflows/${run.workflow_id}`)}>
        &larr; Back to Workflow
      </Button>

      <div className="d-flex justify-content-between align-items-start mb-4">
        <div>
          <h3>Run #{run.run_id} {statusBadge(run.status)}</h3>
          <p className="text-muted mb-0">
            {new Date(run.started_at).toLocaleString()}
            {duration !== null && <> &middot; {duration}s</>}
            {totalTokens > 0 && <> &middot; {totalTokens.toLocaleString()} tokens</>}
            &middot; Trigger: {run.trigger}
          </p>
        </div>
      </div>

      {run.error_detail && (
        <Alert variant="danger">{run.error_detail}</Alert>
      )}

      <Card className="mb-4">
        <Card.Header>Steps ({run.current_step}/{run.total_steps})</Card.Header>
        <Card.Body className="p-0">
          <Table className="mb-0">
            <thead>
              <tr>
                <th style={{width: 50}}>#</th>
                <th>Step</th>
                <th>Status</th>
                <th>Duration</th>
                <th>Tokens</th>
                <th>Summary</th>
              </tr>
            </thead>
            <tbody>
              {steps.map((s) => {
                const stepDuration = s.started_at && s.completed_at
                  ? Math.round((new Date(s.completed_at).getTime() - new Date(s.started_at).getTime()) / 1000)
                  : null;
                return (
                  <tr key={s.step_id}>
                    <td>{s.step_number}</td>
                    <td className="fw-bold">{s.step_name}</td>
                    <td>{statusBadge(s.status)}</td>
                    <td>{stepDuration !== null ? `${stepDuration}s` : "-"}</td>
                    <td>{s.llm_tokens_used > 0 ? s.llm_tokens_used.toLocaleString() : "-"}</td>
                    <td>
                      <span className="text-muted small">{s.output_summary || s.error_detail || ""}</span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </Table>
        </Card.Body>
      </Card>

      {artifacts.length > 0 && (
        <Card>
          <Card.Header>Artifacts ({artifacts.length})</Card.Header>
          <Card.Body className="p-0">
            <Table className="mb-0">
              <thead>
                <tr>
                  <th style={{width: 60}}>Type</th>
                  <th>Description</th>
                  <th>Size</th>
                  <th>File</th>
                  <th style={{width: 90}}></th>
                </tr>
              </thead>
              <tbody>
                {artifacts.map((a) => (
                  <tr key={a.artifact_id}>
                    <td>
                      <Badge bg="light" text="dark" className="font-monospace">{fileIcon(a.file_type)}</Badge>
                    </td>
                    <td>{a.description}</td>
                    <td>{formatSize(a.file_size)}</td>
                    <td className="text-muted small font-monospace">{a.file_path.split("/").pop()}</td>
                    <td>
                      <Button
                        size="sm"
                        variant="outline-primary"
                        onClick={async () => {
                          try {
                            const res = await axiosClient.get(`/artifacts/${a.artifact_id}/download`, {
                              responseType: "blob",
                            });
                            const blob = new Blob([res.data]);
                            const url = URL.createObjectURL(blob);
                            const link = document.createElement("a");
                            link.href = url;
                            link.download = a.file_path.split("/").pop() || "download";
                            link.click();
                            URL.revokeObjectURL(url);
                          } catch (err) {
                            console.error("Download failed", err);
                          }
                        }}
                      >
                        Download
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </Table>
          </Card.Body>
        </Card>
      )}
    </Container>
  );
}
