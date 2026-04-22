import { useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import {
  Container, Card, Button, Form, Alert, Spinner, Badge,
} from "react-bootstrap";
import axiosClient from "../api/axiosClient";

interface PendingReply {
  pending_id: number;
  workflow_id: number;
  run_id: number;
  source_message_id: string;
  source_from: string;
  source_subject: string;
  to_address: string;
  subject: string;
  body_draft: string;
  status: string;
  created_at: string;
}

interface Props {
  workflowName?: string;
}

export default function PendingReplies({ workflowName }: Props = {}) {
  const { id } = useParams();
  const [items, setItems] = useState<PendingReply[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [drafts, setDrafts] = useState<Record<number, string>>({});
  const [busyIds, setBusyIds] = useState<Set<number>>(new Set());
  const [notice, setNotice] = useState<string | null>(null);

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const r = await axiosClient.get(`/workflows/${id}/pending-replies`);
      setItems(r.data);
      // Seed edit buffers with the current draft body
      const next: Record<number, string> = {};
      for (const p of r.data as PendingReply[]) next[p.pending_id] = p.body_draft;
      setDrafts(next);
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Failed to load pending replies";
      setError(msg);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, [id]);

  const editedBody = (p: PendingReply) => {
    const current = drafts[p.pending_id] ?? p.body_draft;
    return current !== p.body_draft ? current : undefined;
  };

  const runAction = async (
    p: PendingReply,
    endpoint: "approve" | "save-draft" | "reject",
  ) => {
    const pending_id = p.pending_id;
    setBusyIds((s) => new Set(s).add(pending_id));
    setNotice(null);
    try {
      const payload: { final_body?: string } = {};
      if (endpoint !== "reject") {
        const edited = editedBody(p);
        if (edited !== undefined) payload.final_body = edited;
      }
      const r = await axiosClient.post(`/pending-replies/${pending_id}/${endpoint}`, payload);
      setNotice(`#${pending_id}: ${r.data?.detail || endpoint}`);
      await load();
    } catch (e) {
      type AxiosErr = { response?: { data?: { detail?: string } } ; message?: string };
      const err = e as AxiosErr;
      const detail = err.response?.data?.detail || err.message || "action failed";
      setError(`#${pending_id}: ${detail}`);
    } finally {
      setBusyIds((s) => {
        const next = new Set(s);
        next.delete(pending_id);
        return next;
      });
    }
  };

  return (
    <Container fluid className="p-4">
      <div className="d-flex justify-content-between align-items-center mb-3">
        <div>
          <h3 className="mb-0">Pending Email Replies</h3>
          {workflowName && <small className="text-muted">Workflow: {workflowName}</small>}
        </div>
        <Link to={`/app/workflows/${id}`} className="btn btn-outline-secondary btn-sm">
          ← Back to workflow
        </Link>
      </div>

      {error && <Alert variant="danger" dismissible onClose={() => setError(null)}>{error}</Alert>}
      {notice && <Alert variant="success" dismissible onClose={() => setNotice(null)}>{notice}</Alert>}

      {loading ? (
        <Spinner animation="border" />
      ) : items.length === 0 ? (
        <p className="text-muted">
          No replies awaiting approval. Run the workflow to queue new candidates.
        </p>
      ) : (
        items.map((p) => {
          const isBusy = busyIds.has(p.pending_id);
          const edited = editedBody(p) !== undefined;
          return (
            <Card key={p.pending_id} className="mb-3">
              <Card.Header className="d-flex justify-content-between align-items-start">
                <div>
                  <div className="fw-semibold">To: {p.to_address}</div>
                  <div className="text-muted small">
                    Subject: {p.subject}
                  </div>
                  <div className="text-muted small">
                    Source: <code>{p.source_from}</code> — “{p.source_subject}”
                  </div>
                </div>
                <div className="text-end">
                  <Badge bg="warning" text="dark">pending</Badge>
                  {edited && <Badge bg="info" className="ms-1">edited</Badge>}
                  <div className="text-muted small mt-1">
                    #{p.pending_id} · {new Date(p.created_at).toLocaleString()}
                  </div>
                </div>
              </Card.Header>
              <Card.Body>
                <Form.Group>
                  <Form.Label className="fw-semibold">Reply body (editable)</Form.Label>
                  <Form.Control
                    as="textarea"
                    rows={Math.min(12, Math.max(4, (drafts[p.pending_id] || "").split("\n").length))}
                    value={drafts[p.pending_id] ?? p.body_draft}
                    onChange={(e) => setDrafts((d) => ({ ...d, [p.pending_id]: e.target.value }))}
                    style={{ fontFamily: "ui-monospace, Menlo, monospace", fontSize: "0.92em" }}
                  />
                </Form.Group>
              </Card.Body>
              <Card.Footer className="d-flex gap-2 flex-wrap">
                <Button
                  variant="success"
                  disabled={isBusy}
                  onClick={() => runAction(p, "approve")}
                  title={edited ? "Send with your edits" : "Send as-drafted"}
                >
                  {edited ? "Edit & Send" : "Approve & Send"}
                </Button>
                <Button
                  variant="outline-primary"
                  disabled={isBusy}
                  onClick={() => runAction(p, "save-draft")}
                >
                  Save as Draft
                </Button>
                <Button
                  variant="outline-danger"
                  disabled={isBusy}
                  onClick={() => runAction(p, "reject")}
                >
                  Reject
                </Button>
                <Button
                  variant="link"
                  size="sm"
                  disabled={isBusy || !edited}
                  onClick={() =>
                    setDrafts((d) => ({ ...d, [p.pending_id]: p.body_draft }))
                  }
                >
                  Revert edits
                </Button>
                {isBusy && <Spinner size="sm" animation="border" className="ms-auto" />}
              </Card.Footer>
            </Card>
          );
        })
      )}
    </Container>
  );
}
