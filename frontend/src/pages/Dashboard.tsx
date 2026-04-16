import { useEffect, useState } from "react";
import { Container, Row, Col, Card } from "react-bootstrap";
import axiosClient from "../api/axiosClient";
import { useSettingsStore } from "../stores/useSettingsStore";

interface DashboardStats {
  total_workflows: number;
  total_runs: number;
  runs_today: number;
  scheduler_running: boolean;
}

export default function Dashboard() {
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const { app_title } = useSettingsStore();

  useEffect(() => {
    axiosClient.get("/dashboard/stats").then((res) => setStats(res.data));
  }, []);

  return (
    <Container fluid className="p-4">
      <h3 className="mb-4">{app_title}</h3>
      {stats && (
        <Row className="g-3">
          <Col md={3}>
            <Card className="text-center">
              <Card.Body>
                <Card.Title className="display-6">{stats.total_workflows}</Card.Title>
                <Card.Text className="text-muted">Workflows</Card.Text>
              </Card.Body>
            </Card>
          </Col>
          <Col md={3}>
            <Card className="text-center">
              <Card.Body>
                <Card.Title className="display-6">{stats.total_runs}</Card.Title>
                <Card.Text className="text-muted">Total Runs</Card.Text>
              </Card.Body>
            </Card>
          </Col>
          <Col md={3}>
            <Card className="text-center">
              <Card.Body>
                <Card.Title className="display-6">{stats.runs_today}</Card.Title>
                <Card.Text className="text-muted">Runs Today</Card.Text>
              </Card.Body>
            </Card>
          </Col>
          <Col md={3}>
            <Card className="text-center">
              <Card.Body>
                <Card.Title className="display-6">
                  {stats.scheduler_running ? "On" : "Off"}
                </Card.Title>
                <Card.Text className="text-muted">Scheduler</Card.Text>
              </Card.Body>
            </Card>
          </Col>
        </Row>
      )}
    </Container>
  );
}
