import { useEffect, useState } from "react";
import { Container, Table, Badge, Button, Modal, Form } from "react-bootstrap";
import axiosClient from "../api/axiosClient";

interface WorkflowCategory {
  category_id: number;
  category_key: string;
  short_name: string;
  long_name: string;
  sort_order: number;
  enabled: boolean;
}

interface EditDraft {
  short_name: string;
  long_name: string;
  sort_order: number;
}

export default function ManageWorkflowCategories() {
  const [categories, setCategories] = useState<WorkflowCategory[]>([]);
  const [editing, setEditing] = useState<WorkflowCategory | null>(null);
  const [draft, setDraft] = useState<EditDraft>({ short_name: "", long_name: "", sort_order: 0 });
  const [saving, setSaving] = useState(false);

  const fetchCategories = () => {
    axiosClient.get("/admin/workflow-categories").then((res) => setCategories(res.data));
  };

  useEffect(() => { fetchCategories(); }, []);

  const startEdit = (c: WorkflowCategory) => {
    setEditing(c);
    setDraft({ short_name: c.short_name, long_name: c.long_name, sort_order: c.sort_order });
  };

  const saveEdit = async () => {
    if (!editing) return;
    setSaving(true);
    try {
      await axiosClient.patch(`/admin/workflow-categories/${editing.category_id}`, draft);
      setEditing(null);
      fetchCategories();
    } catch {
      alert("Failed to save category.");
    } finally {
      setSaving(false);
    }
  };

  const toggleEnabled = async (c: WorkflowCategory) => {
    await axiosClient.patch(`/admin/workflow-categories/${c.category_id}`, { enabled: !c.enabled });
    fetchCategories();
  };

  return (
    <Container fluid className="p-4">
      <div className="mb-4">
        <h3 className="mb-1">Workflow Categories</h3>
        <p className="text-muted mb-0" style={{ fontSize: "0.9rem" }}>
          Top-level groupings for workflow types. New categories ship through database migrations
          rather than this UI; here you can rename, reorder, and disable existing ones.
        </p>
      </div>

      <Table striped bordered hover>
        <thead>
          <tr>
            <th style={{ width: 60 }}>ID</th>
            <th style={{ width: 140 }}>Key</th>
            <th style={{ width: 100 }}>Sort Order</th>
            <th>Short Name</th>
            <th>Long Name</th>
            <th style={{ width: 110 }}>Enabled</th>
            <th style={{ width: 180 }}></th>
          </tr>
        </thead>
        <tbody>
          {categories.map((c) => (
            <tr key={c.category_id}>
              <td>{c.category_id}</td>
              <td><code>{c.category_key}</code></td>
              <td>{c.sort_order}</td>
              <td>{c.short_name}</td>
              <td>{c.long_name}</td>
              <td>
                <Badge bg={c.enabled ? "success" : "secondary"}>
                  {c.enabled ? "Yes" : "No"}
                </Badge>
              </td>
              <td>
                <div className="d-flex gap-2">
                  <Button size="sm" variant="outline-primary" onClick={() => startEdit(c)}>
                    Edit
                  </Button>
                  <Button
                    size="sm"
                    variant={c.enabled ? "outline-warning" : "outline-success"}
                    onClick={() => toggleEnabled(c)}
                  >
                    {c.enabled ? "Disable" : "Enable"}
                  </Button>
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </Table>

      <Modal show={editing !== null} onHide={() => setEditing(null)}>
        <Modal.Header closeButton>
          <Modal.Title>Edit Category</Modal.Title>
        </Modal.Header>
        <Modal.Body>
          {editing && (
            <>
              <Form.Group className="mb-3">
                <Form.Label className="text-muted small">ID (read-only)</Form.Label>
                <Form.Control type="text" value={editing.category_id} disabled readOnly />
              </Form.Group>
              <Form.Group className="mb-3">
                <Form.Label className="text-muted small">Key (read-only)</Form.Label>
                <Form.Control type="text" value={editing.category_key} disabled readOnly />
              </Form.Group>
              <Form.Group className="mb-3">
                <Form.Label>Sort Order</Form.Label>
                <Form.Control
                  type="number"
                  value={draft.sort_order}
                  onChange={(e) => setDraft({ ...draft, sort_order: Number(e.target.value) })}
                />
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
