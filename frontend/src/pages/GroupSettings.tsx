import { useEffect, useState, type FormEvent } from "react";
import { Container, Table, Button, Modal, Form, Row, Col } from "react-bootstrap";
import axiosClient from "../api/axiosClient";
import { useAuthStore } from "../stores/useAuthStore";

interface GroupSetting {
  name: string;
  value: string;
}

interface GroupSummary {
  group_id: number;
  group_name: string;
  is_active: boolean;
}

export default function GroupSettings() {
  const [settings, setSettings] = useState<GroupSetting[]>([]);
  const [editingName, setEditingName] = useState<string | null>(null);
  const [editValue, setEditValue] = useState("");
  const [showAdd, setShowAdd] = useState(false);
  const [newName, setNewName] = useState("");
  const [newValue, setNewValue] = useState("");
  const [expandedRows, setExpandedRows] = useState<Set<string>>(new Set());
  const { group_id, group_name, is_superuser } = useAuthStore();

  // For superusers: list of all groups + currently-selected target.
  // For non-superusers: locked to their own group.
  const [groups, setGroups] = useState<GroupSummary[]>([]);
  const [targetGroupId, setTargetGroupId] = useState<number>(group_id ?? 0);
  const targetGroupName = is_superuser
    ? groups.find((g) => g.group_id === targetGroupId)?.group_name ?? group_name
    : group_name;

  const isOtherGroup = is_superuser && targetGroupId !== group_id;
  const groupQuery = isOtherGroup ? `?group_id=${targetGroupId}` : "";

  const fetchSettings = () => {
    axiosClient.get(`/group-settings${groupQuery}`).then((res) => setSettings(res.data));
  };

  useEffect(() => {
    if (is_superuser) {
      axiosClient.get("/manage/groups").then((res) => setGroups(res.data));
    }
  }, [is_superuser]);

  useEffect(() => { fetchSettings(); }, [targetGroupId]);

  const startEdit = (s: GroupSetting) => {
    setEditingName(s.name);
    setEditValue(s.value);
  };

  const saveEdit = async () => {
    if (!editingName) return;
    await axiosClient.put(`/group-settings/${editingName}${groupQuery}`, { value: editValue });
    setEditingName(null);
    fetchSettings();
  };

  const handleAdd = async (e: FormEvent) => {
    e.preventDefault();
    await axiosClient.put(`/group-settings/${newName}${groupQuery}`, { value: newValue });
    setShowAdd(false);
    setNewName("");
    setNewValue("");
    fetchSettings();
  };

  const handleDelete = async (name: string) => {
    if (!confirm(`Delete group setting "${name}"?`)) return;
    await axiosClient.delete(`/group-settings/${name}${groupQuery}`);
    fetchSettings();
  };

  const toggleExpand = (name: string) => {
    setExpandedRows((prev) => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name); else next.add(name);
      return next;
    });
  };

  const renderValue = (s: GroupSetting) => {
    const isLong = s.value.length > 80;
    const expanded = expandedRows.has(s.name);
    return (
      <div className="position-relative">
        <div style={{
          maxHeight: expanded ? "none" : "2.8em",
          overflow: expanded ? "auto" : "hidden",
          lineHeight: "1.4em",
        }}>
          {s.value}
        </div>
        {isLong && (
          <button
            onClick={() => toggleExpand(s.name)}
            className="btn btn-link btn-sm p-0 text-muted position-absolute"
            style={{ bottom: 0, right: 0, fontSize: "0.7em", lineHeight: 1 }}
          >
            {expanded ? "less" : "more..."}
          </button>
        )}
      </div>
    );
  };

  return (
    <Container fluid className="p-4">
      <div className="d-flex justify-content-between align-items-center mb-4">
        <div>
          <h3 className="mb-0">Group Settings</h3>
          <small className="text-muted">
            Settings for: <strong>{targetGroupName}</strong>
            {isOtherGroup && (
              <span className="text-warning ms-2">(superuser — editing another group)</span>
            )}
          </small>
        </div>
        <div className="d-flex gap-2 align-items-center">
          {is_superuser && groups.length > 0 && (
            <Form.Select
              value={targetGroupId}
              onChange={(e) => setTargetGroupId(Number(e.target.value))}
              style={{ width: "auto" }}
              size="sm"
            >
              {groups.map((g) => (
                <option key={g.group_id} value={g.group_id}>
                  #{g.group_id} {g.group_name}
                  {g.group_id === group_id ? " (your group)" : ""}
                </option>
              ))}
            </Form.Select>
          )}
          <Button variant="primary" onClick={() => setShowAdd(true)}>+ Add Setting</Button>
        </div>
      </div>

      {settings.length === 0 ? (
        <p className="text-muted">No group settings configured yet.</p>
      ) : (
        <Table striped bordered hover>
          <thead>
            <tr>
              <th style={{width: 250}}>Name</th>
              <th>Value</th>
              <th style={{width: 180}}></th>
            </tr>
          </thead>
          <tbody>
            {settings.map((s) => (
              <tr key={s.name}>
                <td className="fw-bold font-monospace">{s.name}</td>
                <td>
                  {editingName === s.name ? (
                    <div className="d-flex gap-2">
                      <Form.Control
                        size="sm"
                        value={editValue}
                        onChange={(e) => setEditValue(e.target.value)}
                        autoFocus
                        onKeyDown={(e) => { if (e.key === "Enter") saveEdit(); if (e.key === "Escape") setEditingName(null); }}
                      />
                      <Button size="sm" variant="success" onClick={saveEdit}>Save</Button>
                      <Button size="sm" variant="secondary" onClick={() => setEditingName(null)}>Cancel</Button>
                    </div>
                  ) : renderValue(s)}
                </td>
                <td>
                  {editingName !== s.name && (
                    <div className="d-flex gap-1">
                      <Button size="sm" variant="outline-primary" onClick={() => startEdit(s)}>Edit</Button>
                      <Button size="sm" variant="outline-danger" onClick={() => handleDelete(s.name)}>Delete</Button>
                    </div>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </Table>
      )}

      <Modal show={showAdd} onHide={() => setShowAdd(false)}>
        <Modal.Header closeButton>
          <Modal.Title>Add Group Setting</Modal.Title>
        </Modal.Header>
        <Form onSubmit={handleAdd}>
          <Modal.Body>
            <Row className="g-3">
              <Col md={6}>
                <Form.Group>
                  <Form.Label>Name</Form.Label>
                  <Form.Control
                    type="text"
                    value={newName}
                    onChange={(e) => setNewName(e.target.value)}
                    required
                    placeholder="setting_name"
                  />
                </Form.Group>
              </Col>
              <Col md={6}>
                <Form.Group>
                  <Form.Label>Value</Form.Label>
                  <Form.Control
                    type="text"
                    value={newValue}
                    onChange={(e) => setNewValue(e.target.value)}
                    required
                  />
                </Form.Group>
              </Col>
            </Row>
          </Modal.Body>
          <Modal.Footer>
            <Button variant="secondary" onClick={() => setShowAdd(false)}>Cancel</Button>
            <Button variant="primary" type="submit">Add</Button>
          </Modal.Footer>
        </Form>
      </Modal>
    </Container>
  );
}
