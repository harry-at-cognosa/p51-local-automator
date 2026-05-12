import { useEffect, useState, type FormEvent } from "react";
import { Container, Table, Button, Modal, Form, Row, Col } from "react-bootstrap";
import axiosClient from "../api/axiosClient";
import { useSettingsStore } from "../stores/useSettingsStore";
import getColor from "../api/getColor";

const COLOR_NAMES = [
  "slate","gray","zinc","stone","red","orange","amber","yellow","lime","green",
  "emerald","teal","cyan","sky","blue","indigo","violet","purple","fuchsia","pink","rose",
];

interface Setting {
  name: string;
  value: string;
}

export default function Settings() {
  const [settings, setSettings] = useState<Setting[]>([]);
  const [editingName, setEditingName] = useState<string | null>(null);
  const [editValue, setEditValue] = useState("");
  const [showAdd, setShowAdd] = useState(false);
  const [newName, setNewName] = useState("");
  const [newValue, setNewValue] = useState("");
  const { fetchSettings: refreshTheme } = useSettingsStore();

  const fetchSettings = () => {
    axiosClient.get("/settings").then((res) => setSettings(res.data));
  };

  useEffect(() => { fetchSettings(); }, []);

  const startEdit = (s: Setting) => {
    setEditingName(s.name);
    setEditValue(s.value);
  };

  const saveEdit = async () => {
    if (!editingName) return;
    await axiosClient.put(`/settings/${editingName}`, { value: editValue });
    setEditingName(null);
    fetchSettings();
    if (["navbar_color", "trim_color", "app_title", "instance_label"].includes(editingName)) {
      refreshTheme();
    }
  };

  const handleAdd = async (e: FormEvent) => {
    e.preventDefault();
    await axiosClient.put(`/settings/${newName}`, { value: newValue });
    setShowAdd(false);
    setNewName("");
    setNewValue("");
    fetchSettings();
  };

  const handleDelete = async (name: string) => {
    if (!confirm(`Delete setting "${name}"?`)) return;
    await axiosClient.delete(`/settings/${name}`);
    fetchSettings();
  };

  const renderEditControl = (name: string) => {
    if (name === "navbar_color" || name === "trim_color") {
      // Both colors use the same picker shape; trim_color previews only
      // at shade 500 (the shade it renders at), navbar_color shows the
      // 300/500/700 band so users can see the full theme arc.
      const previewShades = name === "trim_color" ? [500] : [300, 500, 700];
      return (
        <div className="d-flex gap-2 align-items-center">
          <Form.Select
            size="sm"
            value={editValue}
            onChange={(e) => setEditValue(e.target.value)}
            style={{ width: 160 }}
          >
            {COLOR_NAMES.map((c) => (
              <option key={c} value={c}>{c}</option>
            ))}
          </Form.Select>
          <div className="d-flex gap-1">
            {previewShades.map((shade) => (
              <span
                key={shade}
                className="d-inline-block rounded"
                style={{
                  width: name === "trim_color" ? 32 : 20,
                  height: name === "trim_color" ? 32 : 20,
                  backgroundColor: getColor(editValue, shade),
                }}
              />
            ))}
          </div>
          <Button size="sm" variant="success" onClick={saveEdit}>Save</Button>
          <Button size="sm" variant="secondary" onClick={() => setEditingName(null)}>Cancel</Button>
        </div>
      );
    }
    return (
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
    );
  };

  const [expandedRows, setExpandedRows] = useState<Set<string>>(new Set());

  const toggleExpand = (name: string) => {
    setExpandedRows((prev) => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name); else next.add(name);
      return next;
    });
  };

  const renderValue = (s: Setting) => {
    if (s.name === "navbar_color" || s.name === "trim_color") {
      return (
        <span className="d-flex align-items-center gap-2">
          {s.value}
          <span
            className="d-inline-block rounded"
            style={{ width: 16, height: 16, backgroundColor: getColor(s.value, 500) }}
          />
        </span>
      );
    }

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
        <h3 className="mb-0">Global Settings</h3>
        <Button variant="primary" onClick={() => setShowAdd(true)}>+ Add Setting</Button>
      </div>

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
                {editingName === s.name ? renderEditControl(s.name) : renderValue(s)}
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

      <Modal show={showAdd} onHide={() => setShowAdd(false)}>
        <Modal.Header closeButton>
          <Modal.Title>Add Setting</Modal.Title>
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
