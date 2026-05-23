/**
 * Ad-hoc Email Topic Monitor — top-nav shortcut page.
 *
 * Opens directly to a pre-populated config form for a hidden per-user
 * Type 1 (Email Topic Monitor) workflow row. Four actions:
 *   Run    — save + trigger immediate execution
 *   Test   — validate credentials against each account in parallel
 *   Save   — persist for later, no run
 *   Clear  — wipe config + stored credentials (both backends)
 *
 * Multi-account: up to N accounts (apple_mail OR gmail_imap with an
 * App Password). The masked-secret "(stored — leave blank to keep)"
 * pattern from Type 4 SQL Runner is reused for the app_password field.
 */
import { useEffect, useState } from "react";
import {
  Button,
  Card,
  Col,
  Container,
  Form,
  Modal,
  Row,
  Spinner,
} from "react-bootstrap";
import axiosClient from "../api/axiosClient";

const STORED_SENTINEL = "__STORED__";

interface AccountOut {
  service: string;
  account?: string;
  email?: string;
  app_password?: string;  // STORED_SENTINEL or undefined
  account_id?: number;    // gmail (Workspace OAuth)
}

interface ConfigRead {
  workflow_id: number;
  storage_method: string;
  accounts: AccountOut[];
  mailbox: string;
  period: string;
  topics: string[];
  scope: string;
}

interface TestResult {
  label: string;
  ok: boolean;
  reason: string;
}

interface GmailAccountOption {
  id: number;
  email: string;
  status: "active" | "disconnected" | "revoked";
}

type ServiceKind = "apple_mail" | "gmail_imap" | "gmail";

interface AccountForm {
  service: ServiceKind;
  account: string;        // apple_mail
  email: string;          // gmail_imap
  app_password: string;   // gmail_imap — empty means "keep stored"
  has_stored: boolean;    // tracks whether server has a password stored
  account_id: number | null;  // gmail (Workspace OAuth — FK into gmail_accounts.id)
}

function emptyAppleMailRow(): AccountForm {
  return { service: "apple_mail", account: "iCloud", email: "", app_password: "", has_stored: false, account_id: null };
}

function emptyGmailImapRow(): AccountForm {
  return { service: "gmail_imap", account: "", email: "", app_password: "", has_stored: false, account_id: null };
}

function emptyGmailOAuthRow(): AccountForm {
  return { service: "gmail", account: "", email: "", app_password: "", has_stored: false, account_id: null };
}

function readToForm(c: ConfigRead): AccountForm[] {
  return c.accounts.map((a) => ({
    service: (a.service as ServiceKind) || "apple_mail",
    account: a.account || "",
    email: a.email || "",
    app_password: "",
    has_stored: a.app_password === STORED_SENTINEL,
    account_id: typeof a.account_id === "number" ? a.account_id : null,
  }));
}

function formToWriteAccounts(forms: AccountForm[]): unknown[] {
  return forms.map((f) => {
    if (f.service === "apple_mail") {
      return { service: "apple_mail", account: f.account.trim() || "iCloud" };
    }
    if (f.service === "gmail") {
      return { service: "gmail", account_id: f.account_id };
    }
    return {
      service: "gmail_imap",
      email: f.email.trim(),
      // Empty input + has_stored → server keeps existing.
      // Non-empty → new password to persist.
      app_password: f.app_password.length > 0 ? f.app_password : (f.has_stored ? STORED_SENTINEL : ""),
    };
  });
}

export default function AdHocEmailMonitor() {
  const [loading, setLoading] = useState(true);
  const [workflowId, setWorkflowId] = useState<number | null>(null);
  const [storageMethod, setStorageMethod] = useState<"encrypted_db" | "plaintext_file">("encrypted_db");
  const [accounts, setAccounts] = useState<AccountForm[]>([]);
  const [mailbox, setMailbox] = useState("INBOX");
  const [period, setPeriod] = useState("last 7 days");
  const [topics, setTopics] = useState<string>("");
  const [scope, setScope] = useState("");

  const [busyAction, setBusyAction] = useState<null | "run" | "test" | "save" | "clear">(null);
  const [testResults, setTestResults] = useState<TestResult[] | null>(null);
  const [feedback, setFeedback] = useState<string | null>(null);
  const [feedbackKind, setFeedbackKind] = useState<"success" | "danger" | "info">("info");
  const [showClearModal, setShowClearModal] = useState(false);

  // Workspace Gmail (OAuth) accounts available for the gmail-service picker.
  // Fetched on mount; stays empty if no rows are connected (the picker will
  // surface a "no connected accounts" message in that case).
  const [gmailAccounts, setGmailAccounts] = useState<GmailAccountOption[]>([]);
  useEffect(() => {
    axiosClient
      .get<GmailAccountOption[]>("/gmail/accounts")
      .then((res) => setGmailAccounts(res.data || []))
      .catch(() => setGmailAccounts([]));
  }, []);

  const loadConfig = async () => {
    setLoading(true);
    try {
      const { data } = await axiosClient.get<ConfigRead>("/ad-hoc/email-topic-monitor");
      applyServerState(data);
    } finally {
      setLoading(false);
    }
  };

  const applyServerState = (data: ConfigRead) => {
    setWorkflowId(data.workflow_id);
    setStorageMethod((data.storage_method as "encrypted_db" | "plaintext_file") || "encrypted_db");
    setAccounts(readToForm(data));
    setMailbox(data.mailbox || "INBOX");
    setPeriod(data.period || "last 7 days");
    setTopics((data.topics || []).join(", "));
    setScope(data.scope || "");
  };

  useEffect(() => {
    loadConfig();
  }, []);

  const buildWriteBody = () => ({
    storage_method: storageMethod,
    accounts: formToWriteAccounts(accounts),
    mailbox: mailbox.trim() || "INBOX",
    period: period.trim() || "last 7 days",
    topics: topics.split(",").map((t) => t.trim()).filter(Boolean),
    scope: scope.trim(),
  });

  const showFeedback = (msg: string, kind: "success" | "danger" | "info") => {
    setFeedback(msg);
    setFeedbackKind(kind);
    window.setTimeout(() => setFeedback(null), 6000);
  };

  const handleSave = async () => {
    setBusyAction("save");
    setTestResults(null);
    try {
      const { data } = await axiosClient.put<ConfigRead>(
        "/ad-hoc/email-topic-monitor",
        buildWriteBody(),
      );
      applyServerState(data);
      showFeedback("Saved.", "success");
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      showFeedback(`Save failed: ${msg}`, "danger");
    } finally {
      setBusyAction(null);
    }
  };

  const handleRun = async () => {
    setBusyAction("run");
    setTestResults(null);
    try {
      const { data } = await axiosClient.post<ConfigRead>(
        "/ad-hoc/email-topic-monitor/run",
        buildWriteBody(),
      );
      applyServerState(data);
      showFeedback(
        "Run started. See Workflows → All Runs (or the Dashboard recent-runs feed).",
        "success",
      );
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      showFeedback(`Run failed to start: ${msg}`, "danger");
    } finally {
      setBusyAction(null);
    }
  };

  const handleTest = async () => {
    setBusyAction("test");
    setTestResults(null);
    try {
      const { data } = await axiosClient.post<{ results: TestResult[] }>(
        "/ad-hoc/email-topic-monitor/test",
        buildWriteBody(),
      );
      setTestResults(data.results || []);
      // Re-fetch so any newly-saved credentials show their stored sentinel.
      await loadConfig();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      showFeedback(`Test failed: ${msg}`, "danger");
    } finally {
      setBusyAction(null);
    }
  };

  const handleClearConfirmed = async () => {
    setShowClearModal(false);
    setBusyAction("clear");
    setTestResults(null);
    try {
      const { data } = await axiosClient.post<ConfigRead>("/ad-hoc/email-topic-monitor/clear");
      applyServerState(data);
      showFeedback("Cleared. Form reset; stored credentials wiped.", "info");
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      showFeedback(`Clear failed: ${msg}`, "danger");
    } finally {
      setBusyAction(null);
    }
  };

  const updateAccount = (i: number, patch: Partial<AccountForm>) => {
    setAccounts((prev) => prev.map((a, idx) => (idx === i ? { ...a, ...patch } : a)));
  };

  const removeAccount = (i: number) => {
    setAccounts((prev) => prev.filter((_, idx) => idx !== i));
  };

  const addAppleMail = () => setAccounts((prev) => [...prev, emptyAppleMailRow()]);
  const addGmailImap = () => setAccounts((prev) => [...prev, emptyGmailImapRow()]);
  const addGmailOAuth = () => setAccounts((prev) => [...prev, emptyGmailOAuthRow()]);

  if (loading) {
    return (
      <Container className="py-4 text-center">
        <Spinner animation="border" />
        <div className="mt-2 text-muted">Loading…</div>
      </Container>
    );
  }

  return (
    <Container className="py-4">
      <h2 className="mb-3">Ad-hoc Email Topic Monitor</h2>
      <p className="text-muted" style={{ maxWidth: 720 }}>
        Run an email topic-monitor on demand. The form remembers what
        you entered last time, including app passwords (stored according
        to the method you choose). To run on a different schedule, use
        the regular Workflows page instead.
        {workflowId !== null && (
          <span className="ms-2" style={{ fontSize: "0.85em" }}>
            (workflow_id #{workflowId})
          </span>
        )}
      </p>

      {feedback && (
        <div className={`alert alert-${feedbackKind} py-2 px-3`}>{feedback}</div>
      )}

      <Card className="mb-3">
        <Card.Header>Email accounts</Card.Header>
        <Card.Body>
          {accounts.length === 0 && (
            <div className="text-muted mb-3">
              No accounts yet. Add at least one before running.
            </div>
          )}
          {accounts.map((a, i) => (
            <Row key={i} className="g-2 align-items-end mb-3 border-bottom pb-3">
              <Col md={3}>
                <Form.Label className="small">Service</Form.Label>
                <Form.Select
                  value={a.service}
                  onChange={(e) =>
                    updateAccount(i, {
                      service: e.target.value as ServiceKind,
                    })
                  }
                >
                  <option value="apple_mail">Apple Mail (local)</option>
                  <option value="gmail_imap">Gmail (App Password)</option>
                  <option value="gmail">Gmail (connected workspace account)</option>
                </Form.Select>
              </Col>
              {a.service === "apple_mail" && (
                <Col md={6}>
                  <Form.Label className="small">Mail.app account name</Form.Label>
                  <Form.Control
                    type="text"
                    value={a.account}
                    placeholder="iCloud"
                    onChange={(e) => updateAccount(i, { account: e.target.value })}
                  />
                </Col>
              )}
              {a.service === "gmail_imap" && (
                <>
                  <Col md={4}>
                    <Form.Label className="small">Gmail address</Form.Label>
                    <Form.Control
                      type="email"
                      value={a.email}
                      placeholder="you@gmail.com"
                      onChange={(e) => updateAccount(i, { email: e.target.value })}
                    />
                  </Col>
                  <Col md={4}>
                    <Form.Label className="small">
                      App password
                      <a
                        href="https://myaccount.google.com/apppasswords"
                        target="_blank"
                        rel="noreferrer"
                        className="ms-2"
                        style={{ fontSize: "0.85em" }}
                      >
                        get one
                      </a>
                    </Form.Label>
                    <Form.Control
                      type="password"
                      value={a.app_password}
                      placeholder={a.has_stored ? "(stored — leave blank to keep)" : "16-char code"}
                      onChange={(e) => updateAccount(i, { app_password: e.target.value })}
                    />
                  </Col>
                </>
              )}
              {a.service === "gmail" && (
                <Col md={6}>
                  <Form.Label className="small">Connected Gmail account</Form.Label>
                  {gmailAccounts.length === 0 ? (
                    <Form.Text className="text-muted d-block">
                      No connected accounts yet. Connect one at{" "}
                      <a href="/app/connections">Connections</a>, then return here.
                    </Form.Text>
                  ) : (
                    <Form.Select
                      value={a.account_id === null ? "" : String(a.account_id)}
                      onChange={(e) =>
                        updateAccount(i, {
                          account_id: e.target.value ? parseInt(e.target.value, 10) : null,
                        })
                      }
                    >
                      <option value="">— select an account —</option>
                      {gmailAccounts.map((g) => (
                        <option key={g.id} value={g.id} disabled={g.status !== "active"}>
                          {g.email}
                          {g.status !== "active" ? ` (${g.status})` : ""}
                        </option>
                      ))}
                    </Form.Select>
                  )}
                </Col>
              )}
              <Col md={1} className="text-end">
                <Button
                  variant="outline-secondary"
                  size="sm"
                  onClick={() => removeAccount(i)}
                  title="Remove this account"
                >
                  ×
                </Button>
              </Col>
            </Row>
          ))}
          <div className="d-flex gap-2 flex-wrap">
            <Button variant="outline-primary" size="sm" onClick={addAppleMail}>
              + Add Apple Mail
            </Button>
            <Button variant="outline-primary" size="sm" onClick={addGmailImap}>
              + Add Gmail (App Password)
            </Button>
            <Button variant="outline-primary" size="sm" onClick={addGmailOAuth}>
              + Add Gmail (connected workspace account)
            </Button>
          </div>
        </Card.Body>
      </Card>

      <Card className="mb-3">
        <Card.Header>Credential storage (only applies to Gmail App Password accounts)</Card.Header>
        <Card.Body>
          <Form.Check
            type="radio"
            id="storage-enc"
            name="storage_method"
            label="Encrypted database column (recommended)"
            checked={storageMethod === "encrypted_db"}
            onChange={() => setStorageMethod("encrypted_db")}
          />
          <Form.Check
            type="radio"
            id="storage-plain"
            name="storage_method"
            label="Plaintext .gmailpasswords.json at project root (file mode 0600, shared across this machine)"
            checked={storageMethod === "plaintext_file"}
            onChange={() => setStorageMethod("plaintext_file")}
          />
          <Form.Text className="text-muted">
            Encrypted DB requires the server's TOKEN_ENCRYPTION_KEY env var. The
            plaintext-file option works without that env var; a shell-access
            attacker on this machine would read the file directly.
          </Form.Text>
        </Card.Body>
      </Card>

      <Card className="mb-3">
        <Card.Header>What to scan</Card.Header>
        <Card.Body>
          <Row className="g-3">
            <Col md={4}>
              <Form.Label className="small">Mailbox / label</Form.Label>
              <Form.Control
                type="text"
                value={mailbox}
                onChange={(e) => setMailbox(e.target.value)}
              />
            </Col>
            <Col md={4}>
              <Form.Label className="small">Time period</Form.Label>
              <Form.Control
                type="text"
                value={period}
                placeholder="last 7 days"
                onChange={(e) => setPeriod(e.target.value)}
              />
              <Form.Text className="text-muted">
                Examples: "last 24 hours", "last 7 days", "last 30 days".
              </Form.Text>
            </Col>
            <Col md={12}>
              <Form.Label className="small">Topics (comma-separated)</Form.Label>
              <Form.Control
                type="text"
                value={topics}
                placeholder="leave blank to use defaults"
                onChange={(e) => setTopics(e.target.value)}
              />
              <Form.Text className="text-muted">
                Default topics: Business &amp; Finance, Technology &amp; AI,
                Personal &amp; Social, Marketing &amp; Promotions, Government &amp; Institutional.
              </Form.Text>
            </Col>
            <Col md={12}>
              <Form.Label className="small">Scope / additional guidance</Form.Label>
              <Form.Control
                as="textarea"
                rows={3}
                value={scope}
                placeholder="Any extra direction for the categorization — e.g. 'flag anything mentioning project Whisper as urgent'"
                onChange={(e) => setScope(e.target.value)}
              />
            </Col>
          </Row>
        </Card.Body>
      </Card>

      <div className="d-flex gap-2 mb-4">
        <Button
          variant="primary"
          disabled={busyAction !== null || accounts.length === 0}
          onClick={handleRun}
        >
          {busyAction === "run" ? <Spinner size="sm" animation="border" /> : "Run"}
        </Button>
        <Button
          variant="outline-primary"
          disabled={busyAction !== null || accounts.length === 0}
          onClick={handleTest}
        >
          {busyAction === "test" ? <Spinner size="sm" animation="border" /> : "Test email access"}
        </Button>
        <Button
          variant="outline-secondary"
          disabled={busyAction !== null}
          onClick={handleSave}
        >
          {busyAction === "save" ? <Spinner size="sm" animation="border" /> : "Save for later"}
        </Button>
        <Button
          variant="outline-danger"
          className="ms-auto"
          disabled={busyAction !== null}
          onClick={() => setShowClearModal(true)}
        >
          Clear
        </Button>
      </div>

      {testResults && (
        <Card className="mb-3">
          <Card.Header>Test results</Card.Header>
          <Card.Body>
            {testResults.length === 0 ? (
              <div className="text-muted">No accounts to test.</div>
            ) : (
              <ul className="mb-0">
                {testResults.map((r, i) => (
                  <li key={i}>
                    <span
                      className="badge me-2"
                      style={{
                        backgroundColor: r.ok ? "#15803d" : "#b91c1c",
                        color: "#fff",
                      }}
                    >
                      {r.ok ? "OK" : "FAIL"}
                    </span>
                    <code>{r.label}</code>
                    {r.reason && r.reason !== "ok" && (
                      <span className="text-muted ms-2">— {r.reason}</span>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </Card.Body>
        </Card>
      )}

      <Modal show={showClearModal} onHide={() => setShowClearModal(false)}>
        <Modal.Header closeButton>
          <Modal.Title>Clear ad-hoc state?</Modal.Title>
        </Modal.Header>
        <Modal.Body>
          <p>
            This will wipe every account, every stored app password (in BOTH
            the encrypted database column AND the .gmailpasswords.json file),
            and reset the topic / mailbox / period fields to defaults.
          </p>
          <p className="text-muted mb-0">
            Run history is preserved.
          </p>
        </Modal.Body>
        <Modal.Footer>
          <Button variant="secondary" onClick={() => setShowClearModal(false)}>
            Cancel
          </Button>
          <Button variant="danger" onClick={handleClearConfirmed}>
            Clear everything
          </Button>
        </Modal.Footer>
      </Modal>
    </Container>
  );
}
