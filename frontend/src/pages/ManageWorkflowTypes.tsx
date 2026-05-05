import { useEffect, useState } from "react";
import { Container, Table, Badge, Button, Modal, Form, Alert } from "react-bootstrap";
import axiosClient from "../api/axiosClient";

interface WorkflowCategory {
  category_id: number;
  category_key: string;
  short_name: string;
  long_name: string;
}

interface WorkflowType {
  type_id: number;
  type_name: string;
  type_desc: string;
  short_name: string;
  long_name: string;
  category: WorkflowCategory;
  default_config: Record<string, unknown>;
  required_services: unknown;
  enabled: boolean;
}

interface EditDraft {
  short_name: string;
  long_name: string;
  type_desc: string;
  default_config_text: string;
  required_services_text: string;
}

const formatJson = (v: unknown): string => {
  try {
    return JSON.stringify(v, null, 2);
  } catch {
    return String(v);
  }
};

export default function ManageWorkflowTypes() {
  const [types, setTypes] = useState<WorkflowType[]>([]);
  const [editing, setEditing] = useState<WorkflowType | null>(null);
  const [draft, setDraft] = useState<EditDraft>({
    short_name: "",
    long_name: "",
    type_desc: "",
    default_config_text: "{}",
    required_services_text: "[]",
  });
  const [parseError, setParseError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const fetchTypes = () => {
    axiosClient.get("/admin/workflow-types").then((res) => setTypes(res.data));
  };

  useEffect(() => { fetchTypes(); }, []);

  const startEdit = (t: WorkflowType) => {
    setEditing(t);
    setParseError(null);
    setDraft({
      short_name: t.short_name,
      long_name: t.long_name,
      type_desc: t.type_desc || "",
      default_config_text: formatJson(t.default_config),
      required_services_text: formatJson(t.required_services),
    });
  };

  const saveEdit = async () => {
    if (!editing) return;
    let default_config: Record<string, unknown>;
    let required_services: unknown;
    try {
      default_config = JSON.parse(draft.default_config_text);
      if (default_config === null || typeof default_config !== "object" || Array.isArray(default_config)) {
        throw new Error("default_config must be a JSON object");
      }
    } catch (e) {
      setParseError(`default_config: ${(e as Error).message}`);
      return;
    }
    try {
      required_services = JSON.parse(draft.required_services_text);
    } catch (e) {
      setParseError(`required_services: ${(e as Error).message}`);
      return;
    }
    setParseError(null);
    setSaving(true);
    try {
      await axiosClient.patch(`/admin/workflow-types/${editing.type_id}`, {
        short_name: draft.short_name,
        long_name: draft.long_name,
        type_desc: draft.type_desc,
        default_config,
        required_services,
      });
      setEditing(null);
      fetchTypes();
    } catch {
      alert("Failed to save type.");
    } finally {
      setSaving(false);
    }
  };

  const toggleEnabled = async (t: WorkflowType) => {
    await axiosClient.patch(`/admin/workflow-types/${t.type_id}`, { enabled: !t.enabled });
    fetchTypes();
  };

  return (
    <Container fluid className="p-4">
      <div className="mb-4">
        <h3 className="mb-1">Workflow Types</h3>
        <p className="text-muted mb-0" style={{ fontSize: "0.9rem" }}>
          The catalog of workflow types users can clone into their own workflows. New types ship
          through database migrations and code changes; here you can rename, edit defaults, and
          disable existing ones.
        </p>
      </div>

      <Table striped bordered hover>
        <thead>
          <tr>
            <th style={{ width: 60 }}>ID</th>
            <th style={{ width: 250 }}>Type Name</th>
            <th style={{ width: 110 }}>Category</th>
            <th>Short Name</th>
            <th>Long Name</th>
            <th style={{ width: 110 }}>Enabled</th>
            <th style={{ width: 180 }}></th>
          </tr>
        </thead>
        <tbody>
          {types.map((t) => (
            <tr key={t.type_id}>
              <td>{t.type_id}</td>
              <td><code>{t.type_name}</code></td>
              <td>{t.category.short_name}</td>
              <td>{t.short_name}</td>
              <td>{t.long_name}</td>
              <td>
                <Badge bg={t.enabled ? "success" : "secondary"}>
                  {t.enabled ? "Yes" : "No"}
                </Badge>
              </td>
              <td>
                <div className="d-flex gap-2">
                  <Button size="sm" variant="outline-primary" onClick={() => startEdit(t)}>
                    Edit
                  </Button>
                  <Button
                    size="sm"
                    variant={t.enabled ? "outline-warning" : "outline-success"}
                    onClick={() => toggleEnabled(t)}
                  >
                    {t.enabled ? "Disable" : "Enable"}
                  </Button>
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </Table>

      <Modal show={editing !== null} onHide={() => setEditing(null)} size="lg">
        <Modal.Header closeButton>
          <Modal.Title>Edit Workflow Type</Modal.Title>
        </Modal.Header>
        <Modal.Body>
          {editing && (
            <>
              <Form.Group className="mb-3">
                <Form.Label className="text-muted small">ID (read-only)</Form.Label>
                <Form.Control type="text" value={editing.type_id} disabled readOnly />
              </Form.Group>
              <Form.Group className="mb-3">
                <Form.Label className="text-muted small">Type Name (read-only)</Form.Label>
                <Form.Control type="text" value={editing.type_name} disabled readOnly />
              </Form.Group>
              <Form.Group className="mb-3">
                <Form.Label className="text-muted small">Category (read-only)</Form.Label>
                <Form.Control type="text" value={editing.category.short_name} disabled readOnly />
              </Form.Group>
              <Form.Group className="mb-3">
                <Form.Label>Short Name</Form.Label>
                <Form.Control
                  type="text"
                  value={draft.short_name}
                  onChange={(e) => setDraft({ ...draft, short_name: e.target.value })}
                />
              </Form.Group>
              <Form.Group className="mb-3">
                <Form.Label>Long Name</Form.Label>
                <Form.Control
                  type="text"
                  value={draft.long_name}
                  onChange={(e) => setDraft({ ...draft, long_name: e.target.value })}
                />
              </Form.Group>
              <Form.Group className="mb-3">
                <Form.Label>Description</Form.Label>
                <Form.Control
                  as="textarea"
                  rows={2}
                  value={draft.type_desc}
                  onChange={(e) => setDraft({ ...draft, type_desc: e.target.value })}
                />
              </Form.Group>
              <Form.Group className="mb-3">
                <Form.Label>Default Config (JSON object)</Form.Label>
                <Form.Control
                  as="textarea"
                  rows={8}
                  style={{ fontFamily: "monospace", fontSize: "0.85em" }}
                  value={draft.default_config_text}
                  onChange={(e) => setDraft({ ...draft, default_config_text: e.target.value })}
                />
                <Form.Text className="text-muted">
                  Template config new user workflows of this type start with.
                </Form.Text>
              </Form.Group>
              <Form.Group className="mb-3">
                <Form.Label>Required Services (JSON)</Form.Label>
                <Form.Control
                  as="textarea"
                  rows={3}
                  style={{ fontFamily: "monospace", fontSize: "0.85em" }}
                  value={draft.required_services_text}
                  onChange={(e) => setDraft({ ...draft, required_services_text: e.target.value })}
                />
                <Form.Text className="text-muted">
                  Service tags this type depends on (e.g. <code>["apple_mail_mcp"]</code>).
                </Form.Text>
              </Form.Group>
              {parseError && (
                <Alert variant="danger" className="mb-0">
                  Could not parse: {parseError}
                </Alert>
              )}
            </>
          )}
        </Modal.Body>
        <Modal.Footer>
          <Button variant="secondary" onClick={() => setEditing(null)} disabled={saving}>
            Cancel
          </Button>
          <Button variant="primary" onClick={saveEdit} disabled={saving}>
            {saving ? "Saving…" : "Save"}
          </Button>
        </Modal.Footer>
      </Modal>
    </Container>
  );
}
