import { useEffect, useState } from "react";
import { Container, Table, Badge } from "react-bootstrap";
import axiosClient from "../api/axiosClient";

interface WorkflowType {
  type_id: number;
  type_name: string;
  type_desc: string;
  type_category: string;
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

  useEffect(() => {
    axiosClient.get("/workflow-types").then((res) => setTypes(res.data));
    axiosClient.get("/workflows").then((res) => setWorkflows(res.data));
  }, []);

  const categoryBadge = (cat: string) => {
    const colors: Record<string, string> = {
      email: "primary",
      data: "success",
      calendar: "info",
    };
    return <Badge bg={colors[cat] || "secondary"}>{cat}</Badge>;
  };

  return (
    <Container fluid className="p-4">
      <h3 className="mb-4">Workflow Types</h3>
      <Table striped bordered hover size="sm">
        <thead>
          <tr>
            <th>Name</th>
            <th>Category</th>
            <th>Description</th>
          </tr>
        </thead>
        <tbody>
          {types.map((t) => (
            <tr key={t.type_id}>
              <td className="fw-bold">{t.type_name}</td>
              <td>{categoryBadge(t.type_category)}</td>
              <td>{t.type_desc}</td>
            </tr>
          ))}
        </tbody>
      </Table>

      <h3 className="mt-5 mb-4">My Workflows</h3>
      {workflows.length === 0 ? (
        <p className="text-muted">No workflows configured yet.</p>
      ) : (
        <Table striped bordered hover size="sm">
          <thead>
            <tr>
              <th>Name</th>
              <th>Type</th>
              <th>Enabled</th>
              <th>Last Run</th>
              <th>Created</th>
            </tr>
          </thead>
          <tbody>
            {workflows.map((w) => (
              <tr key={w.workflow_id}>
                <td>{w.name}</td>
                <td>{types.find((t) => t.type_id === w.type_id)?.type_name || w.type_id}</td>
                <td>
                  <Badge bg={w.enabled ? "success" : "secondary"}>
                    {w.enabled ? "Yes" : "No"}
                  </Badge>
                </td>
                <td>{w.last_run_at ? new Date(w.last_run_at).toLocaleString() : "Never"}</td>
                <td>{new Date(w.created_at).toLocaleDateString()}</td>
              </tr>
            ))}
          </tbody>
        </Table>
      )}
    </Container>
  );
}
