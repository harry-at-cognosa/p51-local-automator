import { useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import {
  Container, Row, Col, Card, Button, Badge, Table, Alert, Spinner,
  Form, Modal,
} from "react-bootstrap";
import axiosClient from "../api/axiosClient";

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
}

export default function WorkflowDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [workflow, setWorkflow] = useState<UserWorkflow | null>(null);
  const [runs, setRuns] = useState<WorkflowRun[]>([]);
  const [running, setRunning] = useState(false);
  const [runMessage, setRunMessage] = useState("");
  const [showConfig, setShowConfig] = useState(false);
  const [configJson, setConfigJson] = useState("");

  const fetchData = () => {
    axiosClient.get(`/workflows/${id}`).then((res) => setWorkflow(res.data));
    axiosClient.get(`/workflows/${id}/runs`).then((res) => setRuns(res.data));
  };

  useEffect(() => { fetchData(); }, [id]);

  const triggerRun = async () => {
    setRunning(true);
    setRunMessage("");
    try {
      const res = await axiosClient.post(`/workflows/${id}/run`);
      setRunMessage(res.data.detail);
      // Poll for completion
      const poll = setInterval(async () => {
        const runsRes = await axiosClient.get(`/workflows/${id}/runs`);
        setRuns(runsRes.data);
        const latest = runsRes.data[0];
        if (latest && (latest.status === "completed" || latest.status === "failed")) {
          clearInterval(poll);
          setRunning(false);
          // Refresh workflow to get updated last_run_at
          axiosClient.get(`/workflows/${id}`).then((res) => setWorkflow(res.data));
        }
      }, 3000);
    } catch {
      setRunMessage("Failed to trigger run");
      setRunning(false);
    }
  };

  const saveConfig = async () => {
    try {
      const parsed = JSON.parse(configJson);
      await axiosClient.put(`/workflows/${id}`, { config: parsed });
      setShowConfig(false);
      fetchData();
    } catch {
      alert("Invalid JSON");
    }
  };

  const deleteWorkflow = async () => {
    if (!confirm("Delete this workflow?")) return;
    await axiosClient.delete(`/workflows/${id}`);
    navigate("/app/workflows");
  };

  const statusBadge = (status: string) => {
    const colors: Record<string, string> = {
      completed: "success",
      running: "primary",
      failed: "danger",
      pending: "secondary",
    };
    return <Badge bg={colors[status] || "secondary"}>{status}</Badge>;
  };

  if (!workflow) return <Container className="p-4"><Spinner animation="border" /></Container>;

  return (
    <Container fluid className="p-4">
      <div className="d-flex justify-content-between align-items-start mb-4">
        <div>
          <h3>{workflow.name}</h3>
          <p className="text-muted mb-0">
            Created {new Date(workflow.created_at).toLocaleDateString()}
            {workflow.last_run_at && <> &middot; Last run {new Date(workflow.last_run_at).toLocaleString()}</>}
          </p>
        </div>
        <div className="d-flex gap-2">
          <Button
            variant="success"
            onClick={triggerRun}
            disabled={running}
          >
            {running ? <><Spinner size="sm" animation="border" className="me-1" /> Running...</> : "Run Now"}
          </Button>
          <Button variant="outline-secondary" onClick={() => { setConfigJson(JSON.stringify(workflow.config, null, 2)); setShowConfig(true); }}>
            Edit Config
          </Button>
          <Button variant="outline-danger" onClick={deleteWorkflow}>Delete</Button>
        </div>
      </div>

      {runMessage && <Alert variant="info" dismissible onClose={() => setRunMessage("")}>{runMessage}</Alert>}

      <Row className="g-4">
        <Col md={4}>
          <Card>
            <Card.Header>Configuration</Card.Header>
            <Card.Body>
              <pre className="mb-0" style={{ fontSize: "0.85em", maxHeight: 300, overflow: "auto" }}>
                {JSON.stringify(workflow.config, null, 2)}
              </pre>
            </Card.Body>
          </Card>

          {workflow.schedule && (
            <Card className="mt-3">
              <Card.Header>Schedule</Card.Header>
              <Card.Body>
                <pre className="mb-0" style={{ fontSize: "0.85em" }}>
                  {JSON.stringify(workflow.schedule, null, 2)}
                </pre>
              </Card.Body>
            </Card>
          )}
        </Col>

        <Col md={8}>
          <Card>
            <Card.Header>Run History</Card.Header>
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
                        <tr key={r.run_id}>
                          <td>#{r.run_id}</td>
                          <td>{statusBadge(r.status)}</td>
                          <td>{r.current_step}/{r.total_steps}</td>
                          <td><Badge bg="light" text="dark">{r.trigger}</Badge></td>
                          <td>{new Date(r.started_at).toLocaleString()}</td>
                          <td>{duration !== null ? `${duration}s` : <Spinner size="sm" animation="border" />}</td>
                          <td>
                            <Button
                              size="sm"
                              variant="outline-primary"
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
        </Col>
      </Row>

      <Modal show={showConfig} onHide={() => setShowConfig(false)} size="lg">
        <Modal.Header closeButton>
          <Modal.Title>Edit Configuration</Modal.Title>
        </Modal.Header>
        <Modal.Body>
          <Form.Control
            as="textarea"
            rows={15}
            value={configJson}
            onChange={(e) => setConfigJson(e.target.value)}
            style={{ fontFamily: "monospace", fontSize: "0.9em" }}
          />
        </Modal.Body>
        <Modal.Footer>
          <Button variant="secondary" onClick={() => setShowConfig(false)}>Cancel</Button>
          <Button variant="primary" onClick={saveConfig}>Save</Button>
        </Modal.Footer>
      </Modal>
    </Container>
  );
}
