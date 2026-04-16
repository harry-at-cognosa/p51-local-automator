import { useEffect, useState, type FormEvent } from "react";
import { Container, Table, Button, Modal, Form, Row, Col } from "react-bootstrap";
import axiosClient from "../api/axiosClient";

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
                ) : (
                  <span>{s.value}</span>
                )}
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
