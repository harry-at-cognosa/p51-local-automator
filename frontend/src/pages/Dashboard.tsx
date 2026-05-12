/**
 * Dashboard page (Phase D-track).
 *
 * Four trimmed sections, top to bottom:
 *   1. Header strip — flower logo | title + version pill | CogWrite logo
 *   2. Stats row (Workflows / Total Runs / Runs Today / Scheduler)
 *   3. Most Recent Workflow Runs (3 rows, role-scoped via /dashboard/recent-runs)
 *   4. Available Workflow Types (shared cards grid)
 *
 * Trim color comes from getTrimColor() in the settings store, falling back to
 * navbar_color shade 500 if `trim_color` setting isn't configured.
 */
import { useEffect, useState } from "react";
import { useNavigate, Link } from "react-router-dom";
import { Container, Row, Col, Card, Table, Alert } from "react-bootstrap";
import axiosClient from "../api/axiosClient";
import { useSettingsStore, getTrimColor } from "../stores/useSettingsStore";
import { useAuthStore } from "../stores/useAuthStore";
import WorkflowTypeCardsGrid from "../components/WorkflowTypeCardsGrid";
import StatusBadge from "../components/StatusBadge";

interface DashboardStats {
  total_workflows: number;
  total_runs: number;
  runs_today: number;
  scheduler_running: boolean;
}

interface RecentRun {
  run_id: number;
  workflow_id: number;
  workflow_name: string;
  category_id: number;
  category_short_name: string;
  type_id: number;
  type_long_name: string;
  status: string;
  started_at: string;
}

interface HealthResponse {
  file_system_root: {
    ok: boolean;
    reason: string;
    path: string;
  };
}

export default function Dashboard() {
  const navigate = useNavigate();
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [recentRuns, setRecentRuns] = useState<RecentRun[] | null>(null);
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const settings = useSettingsStore();
  const { app_title, sw_version, db_version } = settings;
  const { is_groupadmin, is_superuser } = useAuthStore();
  const trimColor = getTrimColor(settings);
  const showHealthBanner = is_groupadmin || is_superuser;

  useEffect(() => {
    axiosClient.get<DashboardStats>("/dashboard/stats").then((res) => setStats(res.data));
    axiosClient
      .get<RecentRun[]>("/dashboard/recent-runs", { params: { limit: 3 } })
      .then((res) => setRecentRuns(res.data));
    if (showHealthBanner) {
      axiosClient.get<HealthResponse>("/system/health").then((res) => setHealth(res.data));
    }
  }, [showHealthBanner]);

  // Shared style for trimmed sections.
  const trimStyle: React.CSSProperties = {
    border: `2px solid ${trimColor}`,
    borderRadius: 8,
    padding: "1rem 1.25rem",
  };

  const versionString = [sw_version, db_version].filter(Boolean).join(" | ");

  const fsRoot = health?.file_system_root;
  const settingsLink = is_superuser ? "/app/settings" : "/app/group-settings";

  return (
    <Container fluid className="p-4">
      {showHealthBanner && fsRoot && !fsRoot.ok && (
        <Alert variant="warning" className="mb-3">
          <Alert.Heading className="h6 mb-1">file_system_root is misconfigured</Alert.Heading>
          <div className="small mb-1">{fsRoot.reason}</div>
          <div className="small">
            Workflow runs will fail until this is fixed. <Link to={settingsLink}>Fix in Settings →</Link>
          </div>
        </Alert>
      )}
      {/* Section 1 — Header strip */}
      <div style={{ ...trimStyle, marginBottom: "1rem" }}>
        <Row className="align-items-center g-3">
          <Col xs={12} md={3} className="text-center">
            <img
              src="/landing/images/p51_icon_512sq.png"
              alt="p51 Automator"
              style={{
                width: "100%",
                maxWidth: 180,
                height: "auto",
                border: `2px solid ${trimColor}`,
                borderRadius: 8,
              }}
            />
          </Col>
          <Col xs={12} md={6} className="text-center">
            <h2 className="mb-3">{app_title}</h2>
            {versionString && (
              <div
                className="d-inline-block px-3 py-1"
                style={{
                  border: `2px solid ${trimColor}`,
                  borderRadius: 6,
                  fontSize: "0.95rem",
                  fontFamily: "monospace",
                }}
              >
                {versionString}
              </div>
            )}
          </Col>
          <Col xs={12} md={3} className="text-center">
            <img
              src="/landing/images/cogwrite-semantic-Technologies-600x600_4.png"
              alt="CogWrite Semantic Technologies"
              style={{ width: "100%", maxWidth: 200, height: "auto" }}
            />
          </Col>
        </Row>
      </div>

      {/* Section 2 — Stats */}
      {stats && (
        <div style={{ ...trimStyle, marginBottom: "1rem" }}>
          <Row className="g-3">
            <Col md={3}>
              <Card className="text-center border-0">
                <Card.Body>
                  <Card.Title className="display-6 mb-0">{stats.total_workflows}</Card.Title>
                  <Card.Text className="text-muted">Workflows</Card.Text>
                </Card.Body>
              </Card>
            </Col>
            <Col md={3}>
              <Card className="text-center border-0">
                <Card.Body>
                  <Card.Title className="display-6 mb-0">{stats.total_runs}</Card.Title>
                  <Card.Text className="text-muted">Total Runs</Card.Text>
                </Card.Body>
              </Card>
            </Col>
            <Col md={3}>
              <Card className="text-center border-0">
                <Card.Body>
                  <Card.Title className="display-6 mb-0">{stats.runs_today}</Card.Title>
                  <Card.Text className="text-muted">Runs Today</Card.Text>
                </Card.Body>
              </Card>
            </Col>
            <Col md={3}>
              <Card className="text-center border-0">
                <Card.Body>
                  <Card.Title className="display-6 mb-0">
                    {stats.scheduler_running ? "On" : "Off"}
                  </Card.Title>
                  <Card.Text className="text-muted">Scheduler</Card.Text>
                </Card.Body>
              </Card>
            </Col>
          </Row>
        </div>
      )}

      {/* Section 3 — Most Recent Workflow Runs */}
      <div style={{ ...trimStyle, marginBottom: "1rem" }}>
        <h5 className="text-center mb-3">Most Recent Workflow Runs</h5>
        {recentRuns === null ? (
          <div className="text-muted small">Loading…</div>
        ) : recentRuns.length === 0 ? (
          <div className="text-muted small">No runs yet.</div>
        ) : (
          <Table hover responsive className="mb-0">
            <thead>
              <tr>
                <th>ID</th>
                <th>Category</th>
                <th>Type</th>
                <th>Name</th>
                <th>Status</th>
                <th>Last Run</th>
              </tr>
            </thead>
            <tbody>
              {recentRuns.map((r) => (
                <tr
                  key={r.run_id}
                  onClick={() => navigate(`/app/runs/${r.run_id}`)}
                  style={{ cursor: "pointer" }}
                >
                  <td>#{r.run_id}</td>
                  <td>{r.category_id}-{r.category_short_name}</td>
                  <td>{r.type_id}-{r.type_long_name}</td>
                  <td>{r.workflow_name}</td>
                  <td><StatusBadge status={r.status} /></td>
                  <td>{new Date(r.started_at).toLocaleString()}</td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </div>

      {/* Section 4 — Available Workflow Types */}
      <div style={trimStyle}>
        <h5 className="text-center mb-3">Available Workflow Types</h5>
        <WorkflowTypeCardsGrid />
      </div>
    </Container>
  );
}
