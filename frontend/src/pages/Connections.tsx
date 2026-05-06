/**
 * Connections — list, connect, and revoke external service accounts.
 *
 * Currently scoped to Gmail (Track B Phase B1). Future external services
 * (consumer @gmail.com, Google Calendar, etc.) slot in here.
 */
import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import {
  Container, Card, Table, Button, Spinner, Alert, Badge,
} from "react-bootstrap";
import axiosClient from "../api/axiosClient";

interface GmailAccount {
  id: number;
  email: string;
  status: "active" | "disconnected" | "revoked";
  scopes: string;
  created_at: string;
  last_used_at: string | null;
  access_token_expires_at: string | null;
}

const statusVariant = (s: GmailAccount["status"]): string => {
  if (s === "active") return "success";
  if (s === "disconnected") return "secondary";
  return "danger";
};

export default function Connections() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [accounts, setAccounts] = useState<GmailAccount[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [connecting, setConnecting] = useState(false);
  const [info, setInfo] = useState<string | null>(null);

  const fetchAccounts = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await axiosClient.get<GmailAccount[]>("/gmail/accounts");
      setAccounts(res.data);
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } }; message?: string };
      setError(err?.response?.data?.detail || err?.message || "Failed to load connections.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchAccounts();
    const connected = searchParams.get("connected");
    if (connected) {
      setInfo(`Connected ${connected}`);
      // Strip the query param so a refresh doesn't repeat the message.
      searchParams.delete("connected");
      setSearchParams(searchParams, { replace: true });
    }
  }, []);  // eslint-disable-line react-hooks/exhaustive-deps

  const connectGmail = async () => {
    setConnecting(true);
    setError(null);
    try {
      const res = await axiosClient.post<{ auth_url: string }>("/gmail/oauth/start");
      // Top-level navigation — Google's consent screen wants a full page,
      // not a popup, and the redirect lands back at the callback endpoint.
      window.location.href = res.data.auth_url;
    } catch (e: unknown) {
      const err = e as { response?: { status?: number; data?: { detail?: string } }; message?: string };
      const status = err?.response?.status;
      if (status === 503) {
        setError(
          err.response?.data?.detail ||
            "Gmail is not configured on this server. An administrator must register a GCP project first."
        );
      } else {
        setError(err?.response?.data?.detail || err?.message || "Failed to start Google sign-in.");
      }
      setConnecting(false);
    }
  };

  const revoke = async (acct: GmailAccount) => {
    if (!confirm(`Revoke access to ${acct.email}? You can reconnect later.`)) return;
    try {
      await axiosClient.delete(`/gmail/accounts/${acct.id}`);
      setInfo(`Revoked ${acct.email}`);
      await fetchAccounts();
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } }; message?: string };
      setError(err?.response?.data?.detail || err?.message || "Failed to revoke.");
    }
  };

  return (
    <Container fluid className="p-4">
      <div className="d-flex justify-content-between align-items-center mb-4">
        <h3 className="mb-0">Connections</h3>
      </div>

      {info && (
        <Alert variant="info" dismissible onClose={() => setInfo(null)}>
          {info}
        </Alert>
      )}
      {error && (
        <Alert variant="danger" dismissible onClose={() => setError(null)}>
          {error}
        </Alert>
      )}

      <Card className="mb-4">
        <Card.Header className="d-flex justify-content-between align-items-center">
          <span>Gmail</span>
          <Button
            size="sm"
            variant="primary"
            onClick={connectGmail}
            disabled={connecting}
          >
            {connecting ? (
              <>
                <Spinner size="sm" animation="border" className="me-1" />
                Redirecting…
              </>
            ) : (
              "Connect a Gmail account"
            )}
          </Button>
        </Card.Header>
        <Card.Body className="p-0">
          {loading ? (
            <div className="p-3 text-center">
              <Spinner animation="border" size="sm" /> Loading…
            </div>
          ) : accounts.length === 0 ? (
            <div className="p-3">
              <p className="text-muted mb-2">No Gmail accounts connected yet.</p>
              <p className="text-muted small mb-0">
                Connect a Workspace Gmail account to use it as the source for
                Email Topic Monitor (and, in a later phase, Auto-Reply)
                workflows. Requires the server administrator to have configured
                a GCP project per the customer setup guide.
              </p>
            </div>
          ) : (
            <Table className="mb-0">
              <thead>
                <tr>
                  <th>Email</th>
                  <th>Status</th>
                  <th>Connected</th>
                  <th>Last used</th>
                  <th style={{ width: 110 }}></th>
                </tr>
              </thead>
              <tbody>
                {accounts.map((a) => (
                  <tr key={a.id}>
                    <td>{a.email}</td>
                    <td>
                      <Badge bg={statusVariant(a.status)}>{a.status}</Badge>
                    </td>
                    <td>{new Date(a.created_at).toLocaleDateString()}</td>
                    <td>{a.last_used_at ? new Date(a.last_used_at).toLocaleString() : "Never"}</td>
                    <td>
                      <Button
                        size="sm"
                        variant="outline-danger"
                        disabled={a.status === "revoked"}
                        onClick={() => revoke(a)}
                      >
                        {a.status === "revoked" ? "Revoked" : "Revoke"}
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </Table>
          )}
        </Card.Body>
      </Card>
    </Container>
  );
}
