import { useEffect, useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { Container, Table, Badge, Button, Modal, Form, Row, Col } from "react-bootstrap";
import axiosClient from "../api/axiosClient";
import WorkflowConfigForm from "../components/WorkflowConfigForm";

interface WorkflowType {
  type_id: number;
  type_name: string;
  type_desc: string;
  type_category: string;
  default_config: Record<string, unknown>;
  enabled: boolean;
}

interface UserWorkflow {
  workflow_id: number;
  type_id: number;
  name: string;
  config: Record<string, unknown>;
  enabled: boolean;
  last_run_at: string | null;
  created_at: string;
}

export default function Workflows() {
  const [types, setTypes] = useState<WorkflowType[]>([]);
  const [workflows, setWorkflows] = useState<UserWorkflow[]>([]);
  const [showCreate, setShowCreate] = useState(false);
  const [selectedTypeId, setSelectedTypeId] = useState<number>(0);
  const [newName, setNewName] = useState("");
  const [newConfig, setNewConfig] = useState<Record<string, unknown>>({});
  const navigate = useNavigate();

  const fetchData = () => {
    axiosClient.get("/workflow-types").then((res) => setTypes(res.data));
    axiosClient.get("/workflows").then((res) => setWorkflows(res.data));
  };

  useEffect(() => { fetchData(); }, []);

  const categoryBadge = (cat: string) => {
    const colors: Record<string, string> = {
      email: "primary",
      data: "success",
      calendar: "info",
    };
    return <Badge bg={colors[cat] || "secondary"}>{cat}</Badge>;
  };

  const handleCreate = async (e: FormEvent) => {
    e.preventDefault();
    const wfType = types.find((t) => t.type_id === selectedTypeId);
    if (!wfType) return;

    await axiosClient.post("/workflows", {
      type_id: selectedTypeId,
      name: newName || wfType.type_name,
      config: newConfig,
    });
    setShowCreate(false);
    setNewName("");
    setSelectedTypeId(0);
    setNewConfig({});
    fetchData();
  };

  return (
    <Container fluid className="p-4">
      <div className="d-flex justify-content-between align-items-center mb-4">
        <h3 className="mb-0">My Workflows</h3>
        <Button variant="primary" onClick={() => setShowCreate(true)}>
          + New Workflow
        </Button>
      </div>

      {workflows.length === 0 ? (
        <p className="text-muted">No workflows configured yet. Click "+ New Workflow" to get started.</p>
      ) : (
        <Table striped bordered hover>
          <thead>
            <tr>
              <th>Name</th>
              <th>Type</th>
              <th>Enabled</th>
              <th>Last Run</th>
              <th>Created</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {workflows.map((w) => (
              <tr key={w.workflow_id}>
                <td className="fw-bold">{w.name}</td>
                <td>{categoryBadge(types.find((t) => t.type_id === w.type_id)?.type_category || "")} {types.find((t) => t.type_id === w.type_id)?.type_name || w.type_id}</td>
                <td>
                  <Badge bg={w.enabled ? "success" : "secondary"}>
                    {w.enabled ? "Yes" : "No"}
                  </Badge>
                </td>
                <td>{w.last_run_at ? new Date(w.last_run_at).toLocaleString() : "Never"}</td>
                <td>{new Date(w.created_at).toLocaleDateString()}</td>
                <td>
                  <Button size="sm" variant="outline-primary" onClick={() => navigate(`/app/workflows/${w.workflow_id}`)}>
                    Open
                  </Button>
                </td>
              </tr>
            ))}
          </tbody>
        </Table>
      )}

      <h4 className="mt-5 mb-3">Available Workflow Types</h4>
      <Row className="g-3">
        {types.map((t) => (
          <Col md={6} lg={3} key={t.type_id}>
            <div className="border rounded p-3 h-100">
              <div className="mb-2">{categoryBadge(t.type_category)}</div>
              <h6>{t.type_name}</h6>
              <p className="text-muted small mb-0">{t.type_desc}</p>
            </div>
          </Col>
        ))}
      </Row>

      <Modal show={showCreate} onHide={() => setShowCreate(false)} size="lg">
        <Modal.Header closeButton>
          <Modal.Title>Create Workflow</Modal.Title>
        </Modal.Header>
        <Form onSubmit={handleCreate}>
          <Modal.Body>
            <Form.Group className="mb-3">
              <Form.Label>Workflow Type</Form.Label>
              <Form.Select
                value={selectedTypeId}
                onChange={(e) => {
                  const id = Number(e.target.value);
                  setSelectedTypeId(id);
                  const wfType = types.find((t) => t.type_id === id);
                  setNewConfig(wfType ? { ...wfType.default_config } : {});
                }}
                required
              >
                <option value={0}>Select a type...</option>
                {types.map((t) => (
                  <option key={t.type_id} value={t.type_id}>{t.type_name}</option>
                ))}
              </Form.Select>
            </Form.Group>
            <Form.Group className="mb-3">
              <Form.Label>Name</Form.Label>
              <Form.Control
                type="text"
                placeholder="Give it a name..."
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
              />
              <Form.Text className="text-muted">
                Leave blank to use the type name as default.
              </Form.Text>
            </Form.Group>
            {selectedTypeId > 0 && (
              <>
                <hr />
                <h6 className="mb-3">Configuration</h6>
                <WorkflowConfigForm typeId={selectedTypeId} config={newConfig} onChange={setNewConfig} />
              </>
            )}
          </Modal.Body>
          <Modal.Footer>
            <Button variant="secondary" onClick={() => setShowCreate(false)}>Cancel</Button>
            <Button variant="primary" type="submit" disabled={!selectedTypeId}>Create</Button>
          </Modal.Footer>
        </Form>
      </Modal>
    </Container>
  );
}
