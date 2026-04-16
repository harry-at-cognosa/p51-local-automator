import { useEffect, useState, type FormEvent } from "react";
import { Container, Table, Badge, Button, Modal, Form, Row, Col } from "react-bootstrap";
import axiosClient from "../api/axiosClient";

interface ManagedUser {
  user_id: number;
  group_id: number;
  email: string;
  user_name: string;
  full_name: string;
  is_active: boolean;
  is_superuser: boolean;
  is_groupadmin: boolean;
  is_manager: boolean;
  last_seen: string | null;
}

export default function ManageUsers() {
  const [users, setUsers] = useState<ManagedUser[]>([]);
  const [showCreate, setShowCreate] = useState(false);
  const [form, setForm] = useState({
    user_name: "",
    full_name: "",
    email: "",
    password: "",
    group_id: 2,
    is_manager: false,
    is_groupadmin: false,
  });

  const fetchUsers = () => {
    axiosClient.get("/manage/users").then((res) => setUsers(res.data));
  };

  useEffect(() => { fetchUsers(); }, []);

  const handleCreate = async (e: FormEvent) => {
    e.preventDefault();
    try {
      await axiosClient.post("/manage/users", form);
      setShowCreate(false);
      setForm({ user_name: "", full_name: "", email: "", password: "", group_id: 2, is_manager: false, is_groupadmin: false });
      fetchUsers();
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail || "Failed to create user";
      alert(msg);
    }
  };

  const toggleActive = async (u: ManagedUser) => {
    await axiosClient.put(`/manage/users/${u.user_id}`, { is_active: !u.is_active });
    fetchUsers();
  };

  const roleBadges = (u: ManagedUser) => {
    const badges = [];
    if (u.is_superuser) badges.push(<Badge key="su" bg="danger" className="me-1">superuser</Badge>);
    if (u.is_groupadmin) badges.push(<Badge key="ga" bg="warning" text="dark" className="me-1">groupadmin</Badge>);
    if (u.is_manager) badges.push(<Badge key="mgr" bg="info" className="me-1">manager</Badge>);
    if (badges.length === 0) badges.push(<Badge key="emp" bg="secondary">employee</Badge>);
    return badges;
  };

  return (
    <Container fluid className="p-4">
      <div className="d-flex justify-content-between align-items-center mb-4">
        <h3 className="mb-0">Manage Users</h3>
        <Button variant="primary" onClick={() => setShowCreate(true)}>+ New User</Button>
      </div>

      <Table striped bordered hover>
        <thead>
          <tr>
            <th>Username</th>
            <th>Full Name</th>
            <th>Email</th>
            <th>Group</th>
            <th>Roles</th>
            <th>Active</th>
            <th>Last Seen</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {users.map((u) => (
            <tr key={u.user_id}>
              <td className="fw-bold">{u.user_name}</td>
              <td>{u.full_name}</td>
              <td>{u.email}</td>
              <td>{u.group_id}</td>
              <td>{roleBadges(u)}</td>
              <td>
                <Badge bg={u.is_active ? "success" : "secondary"}>
                  {u.is_active ? "Yes" : "No"}
                </Badge>
              </td>
              <td>{u.last_seen ? new Date(u.last_seen).toLocaleString() : "Never"}</td>
              <td>
                <Button size="sm" variant={u.is_active ? "outline-warning" : "outline-success"} onClick={() => toggleActive(u)}>
                  {u.is_active ? "Disable" : "Enable"}
                </Button>
              </td>
            </tr>
          ))}
        </tbody>
      </Table>

      <Modal show={showCreate} onHide={() => setShowCreate(false)}>
        <Modal.Header closeButton>
          <Modal.Title>Create User</Modal.Title>
        </Modal.Header>
        <Form onSubmit={handleCreate}>
          <Modal.Body>
            <Row className="g-3">
              <Col md={6}>
                <Form.Group>
                  <Form.Label>Username</Form.Label>
                  <Form.Control
                    type="text"
                    value={form.user_name}
                    onChange={(e) => setForm({ ...form, user_name: e.target.value.toLowerCase() })}
                    required
                    placeholder="lowercase, no spaces"
                  />
                </Form.Group>
              </Col>
              <Col md={6}>
                <Form.Group>
                  <Form.Label>Full Name</Form.Label>
                  <Form.Control
                    type="text"
                    value={form.full_name}
                    onChange={(e) => setForm({ ...form, full_name: e.target.value })}
                  />
                </Form.Group>
              </Col>
              <Col md={6}>
                <Form.Group>
                  <Form.Label>Email</Form.Label>
                  <Form.Control
                    type="email"
                    value={form.email}
                    onChange={(e) => setForm({ ...form, email: e.target.value })}
                    required
                  />
                </Form.Group>
              </Col>
              <Col md={6}>
                <Form.Group>
                  <Form.Label>Password</Form.Label>
                  <Form.Control
                    type="password"
                    value={form.password}
                    onChange={(e) => setForm({ ...form, password: e.target.value })}
                    required
                    minLength={4}
                  />
                </Form.Group>
              </Col>
              <Col md={4}>
                <Form.Group>
                  <Form.Label>Group ID</Form.Label>
                  <Form.Control
                    type="number"
                    value={form.group_id}
                    onChange={(e) => setForm({ ...form, group_id: Number(e.target.value) })}
                    required
                  />
                </Form.Group>
              </Col>
              <Col md={4}>
                <Form.Check
                  type="switch"
                  label="Manager"
                  className="mt-4"
                  checked={form.is_manager}
                  onChange={(e) => setForm({ ...form, is_manager: e.target.checked })}
                />
              </Col>
              <Col md={4}>
                <Form.Check
                  type="switch"
                  label="Group Admin"
                  className="mt-4"
                  checked={form.is_groupadmin}
                  onChange={(e) => setForm({ ...form, is_groupadmin: e.target.checked })}
                />
              </Col>
            </Row>
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
