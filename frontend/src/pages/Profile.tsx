/**
 * Profile — user info + outbound results-email preferences.
 *
 * The "Outbound results email" section is the entry point for the
 * "email me my results" feature. The user picks ONE designated account
 * (apple_mail / gmail OAuth / gmail_imap) that will both send and receive
 * results emails (sender + destination roles, sends to itself).
 */
import { useEffect, useState } from "react";
import {
  Alert,
  Button,
  Card,
  Col,
  Container,
  Form,
  Row,
  Spinner,
} from "react-bootstrap";
import axiosClient from "../api/axiosClient";

interface UsersMe {
  id: string;
  user_id: number;
  group_id: number;
  group_name: string;
  email: string;
  user_name: string;
  full_name: string;
  is_active: boolean;
  is_superuser: boolean;
  is_verified: boolean;
  is_groupadmin: boolean;
  is_manager: boolean;
  outbound_service: string | null;
  outbound_identifier: string | null;
}

interface GmailAccount {
  id: number;
  email: string;
  status: "active" | "disconnected" | "revoked";
  scopes: string;
}

type Service = "" | "apple_mail" | "gmail" | "gmail_imap";

interface AppleMailIdentifier {
  account_name: string;
  destination: string;
}

const parseAppleMailIdentifier = (raw: string | null): AppleMailIdentifier => {
  if (!raw) return { account_name: "", destination: "" };
  try {
    const parsed = JSON.parse(raw) as Partial<AppleMailIdentifier>;
    return {
      account_name: parsed.account_name ?? "",
      destination: parsed.destination ?? "",
    };
  } catch {
    return { account_name: "", destination: "" };
  }
};

export default function Profile() {
  const [me, setMe] = useState<UsersMe | null>(null);
  const [gmailAccounts, setGmailAccounts] = useState<GmailAccount[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);

  // Edited form state — split so we can switch service without losing input.
  const [service, setService] = useState<Service>("");
  const [gmailAccountId, setGmailAccountId] = useState<string>("");
  const [imapEmail, setImapEmail] = useState<string>("");
  const [imapPassword, setImapPassword] = useState<string>("");
  const [hasStoredPassword, setHasStoredPassword] = useState<boolean>(false);
  const [appleAccountName, setAppleAccountName] = useState<string>("");
  const [appleDestination, setAppleDestination] = useState<string>("");

  const loadAll = async () => {
    setLoading(true);
    setError(null);
    try {
      const [meRes, gmailRes] = await Promise.all([
        axiosClient.get<UsersMe>("/users/me"),
        axiosClient.get<GmailAccount[]>("/gmail/accounts").catch(() => ({ data: [] as GmailAccount[] })),
      ]);
      const meData = meRes.data;
      setMe(meData);
      setGmailAccounts(gmailRes.data);

      // Hydrate form state from the loaded user.
      const svc = (meData.outbound_service || "") as Service;
      setService(svc);
      if (svc === "gmail") {
        setGmailAccountId(meData.outbound_identifier || "");
      } else if (svc === "gmail_imap") {
        setImapEmail(meData.outbound_identifier || "");
        setHasStoredPassword(Boolean(meData.outbound_identifier));
      } else if (svc === "apple_mail") {
        const parsed = parseAppleMailIdentifier(meData.outbound_identifier);
        setAppleAccountName(parsed.account_name);
        setAppleDestination(parsed.destination);
      }
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } }; message?: string };
      setError(err?.response?.data?.detail || err?.message || "Failed to load profile.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadAll();
  }, []);

  const save = async () => {
    setSaving(true);
    setError(null);
    setInfo(null);
    try {
      let outbound_identifier: string | null = null;
      if (service === "gmail") {
        outbound_identifier = gmailAccountId || null;
      } else if (service === "gmail_imap") {
        outbound_identifier = imapEmail.trim() || null;
      } else if (service === "apple_mail") {
        outbound_identifier = JSON.stringify({
          account_name: appleAccountName.trim(),
          destination: appleDestination.trim(),
        });
      }

      const body: Record<string, unknown> = {
        outbound_service: service || null,
        outbound_identifier,
      };
      // Only send the password when the user typed something — blank
      // leaves the existing stored value alone (masked-secret UX).
      if (service === "gmail_imap" && imapPassword.trim()) {
        body.outbound_app_password = imapPassword.trim();
      }

      const res = await axiosClient.patch<UsersMe>("/users/me", body);
      setMe(res.data);
      setImapPassword("");
      if (service === "gmail_imap") {
        setHasStoredPassword(true);
      }
      setInfo("Saved.");
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } }; message?: string };
      setError(err?.response?.data?.detail || err?.message || "Save failed.");
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <Container className="py-4">
        <Spinner animation="border" />
      </Container>
    );
  }

  if (!me) {
    return (
      <Container className="py-4">
        <Alert variant="danger">{error || "Failed to load profile."}</Alert>
      </Container>
    );
  }

  const connectedGmail = gmailAccounts.filter((a) => a.status === "active");

  return (
    <Container className="py-4">
      <h2 className="mb-4">Profile</h2>

      <Card className="mb-4">
        <Card.Header>Account</Card.Header>
        <Card.Body>
          <Row>
            <Col md={6}>
              <div className="text-muted small">Username</div>
              <div>{me.user_name}</div>
            </Col>
            <Col md={6}>
              <div className="text-muted small">Email (login)</div>
              <div>{me.email}</div>
            </Col>
          </Row>
          <Row className="mt-3">
            <Col md={6}>
              <div className="text-muted small">Full name</div>
              <div>{me.full_name || <span className="text-muted">(not set)</span>}</div>
            </Col>
            <Col md={6}>
              <div className="text-muted small">Group</div>
              <div>{me.group_name}</div>
            </Col>
          </Row>
        </Card.Body>
      </Card>

      <Card>
        <Card.Header>Outbound results email</Card.Header>
        <Card.Body>
          <p className="text-muted">
            Pick one designated account to receive workflow result emails. The
            same account both sends and receives (it emails itself). This is
            optional — leave it unset if you don't want any workflow to email
            you results.
          </p>

          {error && <Alert variant="danger" onClose={() => setError(null)} dismissible>{error}</Alert>}
          {info && <Alert variant="success" onClose={() => setInfo(null)} dismissible>{info}</Alert>}

          <Form.Group className="mb-3">
            <Form.Label>Service</Form.Label>
            <Form.Check
              type="radio"
              id="ob-none"
              name="outbound_service"
              label="None — do not email me any results"
              checked={service === ""}
              onChange={() => setService("")}
            />
            <Form.Check
              type="radio"
              id="ob-apple"
              name="outbound_service"
              label="Apple Mail (sends via Mail.app on the Mac Mini)"
              checked={service === "apple_mail"}
              onChange={() => setService("apple_mail")}
            />
            <Form.Check
              type="radio"
              id="ob-gmail"
              name="outbound_service"
              label="Gmail — connected Workspace account"
              checked={service === "gmail"}
              onChange={() => setService("gmail")}
              disabled={connectedGmail.length === 0}
            />
            {connectedGmail.length === 0 && service !== "gmail" && (
              <Form.Text className="text-muted ms-4">
                Connect a Workspace Gmail account on the Connections page first.
              </Form.Text>
            )}
            <Form.Check
              type="radio"
              id="ob-imap"
              name="outbound_service"
              label="Gmail (App Password) — for consumer Gmail"
              checked={service === "gmail_imap"}
              onChange={() => setService("gmail_imap")}
            />
          </Form.Group>

          {service === "apple_mail" && (
            <Row className="mb-3">
              <Col md={6}>
                <Form.Group>
                  <Form.Label>Mail.app sending account name</Form.Label>
                  <Form.Control
                    value={appleAccountName}
                    placeholder="(leave blank to use Mail.app default)"
                    onChange={(e) => setAppleAccountName(e.target.value)}
                  />
                  <Form.Text className="text-muted">
                    Match the account name shown in Mail.app → Settings → Accounts (e.g. "iCloud", "acme_kpi_bot").
                  </Form.Text>
                </Form.Group>
              </Col>
              <Col md={6}>
                <Form.Group>
                  <Form.Label>Destination email address</Form.Label>
                  <Form.Control
                    type="email"
                    value={appleDestination}
                    placeholder="where to send results"
                    onChange={(e) => setAppleDestination(e.target.value)}
                  />
                  <Form.Text className="text-muted">
                    Required. Apple Mail accounts are identified by name, not by address — tell us where results should land.
                  </Form.Text>
                </Form.Group>
              </Col>
            </Row>
          )}

          {service === "gmail" && (
            <Row className="mb-3">
              <Col md={6}>
                <Form.Group>
                  <Form.Label>Connected Workspace Gmail account</Form.Label>
                  <Form.Select
                    value={gmailAccountId}
                    onChange={(e) => setGmailAccountId(e.target.value)}
                  >
                    <option value="">— choose an account —</option>
                    {connectedGmail.map((a) => (
                      <option key={a.id} value={String(a.id)}>
                        {a.email}
                      </option>
                    ))}
                  </Form.Select>
                </Form.Group>
              </Col>
            </Row>
          )}

          {service === "gmail_imap" && (
            <Row className="mb-3">
              <Col md={6}>
                <Form.Group>
                  <Form.Label>Consumer Gmail address</Form.Label>
                  <Form.Control
                    type="email"
                    value={imapEmail}
                    placeholder="you@gmail.com"
                    onChange={(e) => setImapEmail(e.target.value)}
                  />
                </Form.Group>
              </Col>
              <Col md={6}>
                <Form.Group>
                  <Form.Label>
                    App Password{" "}
                    <a
                      href="https://myaccount.google.com/apppasswords"
                      target="_blank"
                      rel="noreferrer"
                      className="small ms-2"
                    >
                      get one
                    </a>
                  </Form.Label>
                  <Form.Control
                    type="password"
                    value={imapPassword}
                    placeholder={
                      hasStoredPassword
                        ? "(stored — leave blank to keep, or type to replace)"
                        : "16-char code"
                    }
                    onChange={(e) => setImapPassword(e.target.value)}
                  />
                  {hasStoredPassword && (
                    <Form.Text className="text-muted">
                      A password is already stored in .gmailpasswords.json for this address.
                      Leave blank to keep it; type a new value to replace.
                    </Form.Text>
                  )}
                </Form.Group>
              </Col>
            </Row>
          )}

          <Button onClick={save} disabled={saving} variant="primary">
            {saving ? "Saving…" : "Save"}
          </Button>
        </Card.Body>
      </Card>
    </Container>
  );
}
