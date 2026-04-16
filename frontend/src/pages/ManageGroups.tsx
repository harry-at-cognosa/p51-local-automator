import { useEffect, useState, type FormEvent } from "react";
import { Container, Table, Badge, Button, Modal, Form } from "react-bootstrap";
import axiosClient from "../api/axiosClient";

interface Group {
  group_id: number;
  group_name: string;
  is_active: boolean;
}

export default function ManageGroups() {
  const [groups, setGroups] = useState<Group[]>([]);
  const [showCreate, setShowCreate] = useState(false);
  const [newName, setNewName] = useState("");
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editName, setEditName] = useState("");

  const fetchGroups = () => {
    axiosClient.get("/manage/groups").then((res) => setGroups(res.data));
  };

  useEffect(() => { fetchGroups(); }, []);

  const handleCreate = async (e: FormEvent) => {
    e.preventDefault();
    await axiosClient.post("/manage/groups", { group_name: newName });
    setShowCreate(false);
    setNewName("");
    fetchGroups();
  };

  const toggleActive = async (g: Group) => {
    await axiosClient.put(`/manage/groups/${g.group_id}`, { is_active: !g.is_active });
    fetchGroups();
  };

  const startEdit = (g: Group) => {
    setEditingId(g.group_id);
    setEditName(g.group_name);
  };

  const saveEdit = async () => {
    if (editingId === null) return;
    await axiosClient.put(`/manage/groups/${editingId}`, { group_name: editName });
    setEditingId(null);
    fetchGroups();
  };

  return (
    <Container fluid className="p-4">
      <div className="d-flex justify-content-between align-items-center mb-4">
        <h3 className="mb-0">Manage Groups</h3>
        <Button variant="primary" onClick={() => setShowCreate(true)}>+ New Group</Button>
      </div>

      <Table striped bordered hover>
        <thead>
          <tr>
            <th style={{width: 60}}>ID</th>
            <th>Name</th>
            <th style={{width: 100}}>Active</th>
            <th style={{width: 180}}></th>
          </tr>
        </thead>
        <tbody>
          {groups.map((g) => (
            <tr key={g.group_id}>
              <td>{g.group_id}</td>
              <td>
                {editingId === g.group_id ? (
                  <div className="d-flex gap-2">
                    <Form.Control
                      size="sm"
                      value={editName}
                      onChange={(e) => setEditName(e.target.value)}
                      autoFocus
                      onKeyDown={(e) => { if (e.key === "Enter") saveEdit(); if (e.key === "Escape") setEditingId(null); }}
                    />
                    <Button size="sm" variant="success" onClick={saveEdit}>Save</Button>
                    <Button size="sm" variant="secondary" onClick={() => setEditingId(null)}>Cancel</Button>
                  </div>
                ) : (
                  <span className="fw-bold">{g.group_name}</span>
                )}
              </td>
              <td>
                <Badge bg={g.is_active ? "success" : "secondary"}>
                  {g.is_active ? "Yes" : "No"}
                </Badge>
              </td>
              <td>
                <div className="d-flex gap-2">
                  {editingId !== g.group_id && (
                    <Button size="sm" variant="outline-primary" onClick={() => startEdit(g)}>
                      Edit
                    </Button>
                  )}
                  <Button
                    size="sm"
                    variant={g.is_active ? "outline-warning" : "outline-success"}
                    onClick={() => toggleActive(g)}
                    disabled={g.group_id === 1}
                  >
                    {g.is_active ? "Disable" : "Enable"}
                  </Button>
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </Table>

      <Modal show={showCreate} onHide={() => setShowCreate(false)}>
        <Modal.Header closeButton>
          <Modal.Title>Create Group</Modal.Title>
        </Modal.Header>
        <Form onSubmit={handleCreate}>
          <Modal.Body>
            <Form.Group>
              <Form.Label>Group Name</Form.Label>
              <Form.Control
                type="text"
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
                required
                placeholder="e.g. Acme Corp"
              />
            </Form.Group>
          </Modal.Body>
          <Modal.Footer>
            <Button variant="secondary" onClick={() => setShowCreate(false)}>Cancel</Button>
            <Button variant="primary" type="submit">Create</Button>
          </Modal.Footer>
        </Form>
      </Modal>
    </Container>
  );
}
