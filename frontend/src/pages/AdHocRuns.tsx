/**
 * Ad-hoc Workflows — Past Runs
 *
 * Read-only cross-type history of the user's ad-hoc runs. Today only
 * Email Topic Monitor surfaces here; future ad-hoc types appear
 * automatically (the backend query is type-agnostic).
 *
 * Mirrors WorkflowDetail.tsx's run-table layout for consistency. NO
 * delete, NO re-run, NO archive controls — this is a pure mirror.
 * Drill-in is via the existing /app/runs/:runId page.
 */
import { useEffect, useState } from "react";
import { Badge, Button, Card, Container, Spinner, Table } from "react-bootstrap";
import { useNavigate } from "react-router-dom";
import axiosClient from "../api/axiosClient";
import StatusBadge from "../components/StatusBadge";
import EmailSendBadge from "../components/EmailSendBadge";

interface AdHocRunListItem {
  run_id: number;
  workflow_id: number;
  workflow_name: string;
  type_id: number;
  type_long_name: string;
  status: string;
  current_step: number;
  total_steps: number;
  trigger: string;
  started_at: string;
  completed_at: string | null;
  artifact_count: number;
  email_send_status: string | null;
  email_send_recipient: string | null;
  email_send_error: string | null;
}

export default function AdHocRuns() {
  const navigate = useNavigate();
  const [runs, setRuns] = useState<AdHocRunListItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    axiosClient
      .get<AdHocRunListItem[]>("/ad-hoc/runs")
      .then((res) => {
        if (!cancelled) setRuns(res.data);
      })
      .catch((err) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : String(err));
          setRuns([]);
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <Container className="py-4">
      <h2 className="mb-2">Ad-hoc Workflows — Past Runs</h2>
      <p className="text-muted" style={{ maxWidth: 720 }}>
        Read-only history of your ad-hoc workflow runs. Click Details to see
        the steps and download artifacts. Use the Ad-hoc Workflows menu to
        launch a new run.
      </p>

      {error && (
        <div className="alert alert-warning py-2 px-3">
          Could not load run history: {error}
        </div>
      )}

      <Card>
        <Card.Header>Recent ad-hoc runs (up to 50)</Card.Header>
        <Card.Body className="p-0">
          {runs === null ? (
            <div className="p-4 text-center text-muted">
              <Spinner animation="border" size="sm" /> Loading…
            </div>
          ) : runs.length === 0 ? (
            <p className="text-muted p-3 mb-0">
              No ad-hoc runs yet. Use the Ad-hoc Workflows menu to launch one.
            </p>
          ) : (
            <Table hover className="mb-0">
              <thead>
                <tr>
                  <th>Run</th>
                  <th>Type</th>
                  <th>Workflow</th>
                  <th>Status</th>
                  <th>Steps</th>
                  <th>Trigger</th>
                  <th>Started</th>
                  <th>Duration</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {runs.map((r) => {
                  const duration = r.completed_at
                    ? Math.round(
                        (new Date(r.completed_at).getTime() -
                          new Date(r.started_at).getTime()) /
                          1000,
                      )
                    : null;
                  return (
                    <tr key={r.run_id}>
                      <td>#{r.run_id}</td>
                      <td>{r.type_long_name}</td>
                      <td>{r.workflow_name}</td>
                      <td>
                        <StatusBadge status={r.status} />
                        <EmailSendBadge
                          status={r.email_send_status}
                          recipient={r.email_send_recipient}
                          error={r.email_send_error}
                        />
                      </td>
                      <td>
                        {r.current_step}/{r.total_steps}
                      </td>
                      <td>
                        <Badge bg="light" text="dark">{r.trigger}</Badge>
                      </td>
                      <td>{new Date(r.started_at).toLocaleString()}</td>
                      <td>
                        {duration !== null ? (
                          `${duration}s`
                        ) : (
                          <Spinner size="sm" animation="border" />
                        )}
                      </td>
                      <td>
                        <Button
                          size="sm"
                          variant="outline-primary"
                          title={
                            r.artifact_count === 0
                              ? "Step + status info; no file artifacts produced"
                              : `${r.artifact_count} artifact(s)`
                          }
                          onClick={() => navigate(`/app/runs/${r.run_id}`)}
                        >
                          Details
                        </Button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </Table>
          )}
        </Card.Body>
      </Card>
    </Container>
  );
}
