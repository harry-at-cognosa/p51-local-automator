import { useEffect, useState } from "react";
import { Form, Row, Col, Badge } from "react-bootstrap";
import SchemaConfigForm, { type FieldDescriptor } from "./SchemaConfigForm";
import axiosClient from "../api/axiosClient";

interface Props {
  typeId: number;
  config: Record<string, unknown>;
  onChange: (config: Record<string, unknown>) => void;
  /**
   * Optional config_schema from the workflow type. If supplied AND no typeId
   * branch handles this typeId, the generic SchemaConfigForm renders the form.
   * Types 1–6 keep their hand-tuned UX even when a schema is also present.
   */
  configSchema?: FieldDescriptor[] | null;
}

const PERIOD_OPTIONS = [
  "last 24 hours",
  "last 3 days",
  "last 7 days",
  "last 2 weeks",
  "last month",
];

const MAIL_ACCOUNTS = [
  { value: "iCloud", label: "iCloud (harry.layman@icloud.com)" },
  { value: "harry@cognosa.net", label: "Cognosa (harry@cognosa.net)" },
  { value: "Exchange", label: "Exchange / CogWrite (legacy)" },
];

const CALENDAR_OPTIONS = [
  "Work", "Family", "Home", "Calendar",
];

export default function WorkflowConfigForm({ typeId, config, onChange, configSchema }: Props) {
  const set = (key: string, value: unknown) => {
    onChange({ ...config, [key]: value });
  };

  // Email Topic Monitor — extracted to its own component so the
  // service-switch + gmail-accounts fetch can use hooks.
  if (typeId === 1) {
    return <Type1EmailMonitorForm config={config} onChange={onChange} set={set} />;
  }

  // Transaction Data Analyzer
  if (typeId === 2) {
    return (
      <Row className="g-3">
        <Col md={12}>
          <Form.Group>
            <Form.Label>Data File Path</Form.Label>
            <Form.Control
              placeholder="/path/to/data.csv or .xlsx"
              value={(config.file_path as string) || ""}
              onChange={(e) => set("file_path", e.target.value)}
            />
            <Form.Text className="text-muted">Full path to CSV or Excel file on the server</Form.Text>
          </Form.Group>
        </Col>
        <Col md={4}>
          <Form.Group>
            <Form.Label>Start Date</Form.Label>
            <Form.Control
              type="date"
              value={(config.start_date as string) || ""}
              onChange={(e) => set("start_date", e.target.value)}
            />
          </Form.Group>
        </Col>
        <Col md={4}>
          <Form.Group>
            <Form.Label>End Date</Form.Label>
            <Form.Control
              type="date"
              value={(config.end_date as string) || ""}
              onChange={(e) => set("end_date", e.target.value)}
            />
          </Form.Group>
        </Col>
        <Col md={4}>
          <Form.Group>
            <Form.Label>Output Format</Form.Label>
            <Form.Select
              value={(config.output_format as string) || "xlsx"}
              onChange={(e) => set("output_format", e.target.value)}
            >
              <option value="xlsx">Excel (.xlsx)</option>
              <option value="csv">CSV</option>
            </Form.Select>
          </Form.Group>
        </Col>
        <Col md={12}>
          <Form.Group>
            <Form.Label>
              Key Fields <span className="text-muted fw-normal">(optional, AI decides if blank)</span>
            </Form.Label>
            <Form.Control
              placeholder="date, amount, category, vendor"
              value={((config.key_fields as string[]) || []).join(", ")}
              onChange={(e) => {
                const val = e.target.value;
                set("key_fields", val ? val.split(",").map((t) => t.trim()).filter(Boolean) : []);
              }}
            />
          </Form.Group>
        </Col>
      </Row>
    );
  }

  // Calendar Digest
  if (typeId === 3) {
    const selectedCals = (config.calendars as string[]) || ["Work", "Family"];
    return (
      <Row className="g-3">
        <Col md={6}>
          <Form.Group>
            <Form.Label>Calendars</Form.Label>
            {CALENDAR_OPTIONS.map((cal) => (
              <Form.Check
                key={cal}
                type="checkbox"
                label={cal}
                checked={selectedCals.includes(cal)}
                onChange={(e) => {
                  if (e.target.checked) {
                    set("calendars", [...selectedCals, cal]);
                  } else {
                    set("calendars", selectedCals.filter((c) => c !== cal));
                  }
                }}
              />
            ))}
          </Form.Group>
        </Col>
        <Col md={6}>
          <Form.Group>
            <Form.Label>Days Ahead</Form.Label>
            <Form.Control
              type="number"
              min={1}
              max={90}
              value={(config.days as number) || 7}
              onChange={(e) => set("days", Number(e.target.value))}
            />
          </Form.Group>
        </Col>
      </Row>
    );
  }

  // SQL Query Runner
  if (typeId === 4) {
    const hasStoredSecret = Boolean(config.connection_string_enc);
    return (
      <Row className="g-3">
        <Col md={6}>
          <Form.Group>
            <Form.Label>Query Name</Form.Label>
            <Form.Control
              placeholder="e.g. daily_sales_summary"
              value={(config.query_name as string) || ""}
              onChange={(e) => set("query_name", e.target.value)}
            />
          </Form.Group>
        </Col>
        <Col md={6}>
          <Form.Group>
            <Form.Label>Connection String</Form.Label>
            <Form.Control
              placeholder={
                hasStoredSecret
                  ? "(stored — leave blank to keep, or type to replace)"
                  : "postgresql://user:pass@localhost:5432/dbname"
              }
              value={(config.connection_string as string) || ""}
              onChange={(e) => set("connection_string", e.target.value)}
            />
            {hasStoredSecret && (
              <Form.Text className="text-muted">
                Connection string is stored encrypted. The original value is not
                displayed. Leave the field blank to keep it; type a new string
                to replace it.
              </Form.Text>
            )}
          </Form.Group>
        </Col>
        <Col md={12}>
          <Form.Group>
            <Form.Label>SQL Query</Form.Label>
            <Form.Control
              as="textarea"
              rows={4}
              placeholder="SELECT ..."
              value={(config.query as string) || ""}
              onChange={(e) => set("query", e.target.value)}
              style={{ fontFamily: "monospace", fontSize: "0.9em" }}
            />
            <Form.Text className="text-muted">Read-only queries only (SELECT, WITH, EXPLAIN)</Form.Text>
          </Form.Group>
        </Col>
      </Row>
    );
  }

  // Auto-Reply (Draft Only) = type 5, Auto-Reply (Approve Before Send) = type 6
  // Same config shape for both.
  if (typeId === 5 || typeId === 6) {
    return (
      <Row className="g-3">
        <Col md={6}>
          <Form.Group>
            <Form.Label>Mail Account</Form.Label>
            <Form.Select
              value={(config.account as string) || "iCloud"}
              onChange={(e) => set("account", e.target.value)}
            >
              {MAIL_ACCOUNTS.map((a) => (
                <option key={a.value} value={a.value}>{a.label}</option>
              ))}
            </Form.Select>
            <Form.Text className="text-muted">Drafts/sends use this account</Form.Text>
          </Form.Group>
        </Col>
        <Col md={6}>
          <Form.Group>
            <Form.Label>Mailbox</Form.Label>
            <Form.Control
              value={(config.mailbox as string) || "INBOX"}
              onChange={(e) => set("mailbox", e.target.value)}
            />
          </Form.Group>
        </Col>
        <Col md={6}>
          <Form.Group>
            <Form.Label>Sender filter (substring, case-insensitive)</Form.Label>
            <Form.Control
              placeholder="e.g. form-submission@squarespace.info"
              value={(config.sender_filter as string) || ""}
              onChange={(e) => set("sender_filter", e.target.value)}
            />
          </Form.Group>
        </Col>
        <Col md={6}>
          <Form.Group>
            <Form.Label>Fetch limit</Form.Label>
            <Form.Control
              type="number"
              min={1}
              max={200}
              value={(config.fetch_limit as number) || 50}
              onChange={(e) => set("fetch_limit", parseInt(e.target.value, 10) || 50)}
            />
            <Form.Text className="text-muted">Max recent messages to scan per run</Form.Text>
          </Form.Group>
        </Col>
        <Col md={12}>
          <Form.Group>
            <Form.Label>Body contains (substring, case-insensitive)</Form.Label>
            <Form.Control
              placeholder="e.g. Sent via form submission from CogWrite Semantic Technologies"
              value={(config.body_contains as string) || ""}
              onChange={(e) => set("body_contains", e.target.value)}
            />
            <Form.Text className="text-muted">
              At least one filter (sender or body) is required — empty-filter runs are skipped to avoid unintended replies.
            </Form.Text>
          </Form.Group>
        </Col>
        <Col md={12}>
          <Form.Group>
            <Form.Label>Submitter-email body label (optional)</Form.Label>
            <Form.Control
              placeholder="e.g. Email:"
              value={(config.body_email_field as string) || ""}
              onChange={(e) => set("body_email_field", e.target.value)}
            />
            <Form.Text className="text-muted">
              For form-submission emails where the sender is a no-reply transport (e.g. <code>form-submission@squarespace.info</code>), specify the body label that precedes the actual submitter's email. Squarespace puts <code>Email:&nbsp;harry@example.com</code> in the body. The engine will use that address as the reply target. Leave blank for emails with a real Reply-To header.
            </Form.Text>
          </Form.Group>
        </Col>
        <Col md={12}>
          <Form.Group>
            <Form.Label>Reply tone</Form.Label>
            <Form.Control
              placeholder="e.g. warm and professional"
              value={(config.tone as string) || "warm and professional"}
              onChange={(e) => set("tone", e.target.value)}
            />
          </Form.Group>
        </Col>
        <Col md={12}>
          <Form.Group>
            <Form.Label>Signature (appended to every reply)</Form.Label>
            <Form.Control
              as="textarea"
              rows={3}
              placeholder={"Harry Layman\nCognosa"}
              value={(config.signature as string) || ""}
              onChange={(e) => set("signature", e.target.value)}
              style={{ fontFamily: "monospace", fontSize: "0.9em" }}
            />
          </Form.Group>
        </Col>
      </Row>
    );
  }

  // Schema-driven path for new workflow types whose typeId has no
  // hand-tuned branch above. The backend's config_schema describes the
  // fields and the generic renderer handles them.
  if (configSchema && configSchema.length > 0) {
    return <SchemaConfigForm schema={configSchema} config={config} onChange={onChange} />;
  }

  // Final fallback: raw JSON when no schema is available either.
  return (
    <Form.Group>
      <Form.Label>Configuration (JSON)</Form.Label>
      <Form.Control
        as="textarea"
        rows={8}
        value={JSON.stringify(config, null, 2)}
        onChange={(e) => {
          try { onChange(JSON.parse(e.target.value)); } catch { /* ignore parse errors while typing */ }
        }}
        style={{ fontFamily: "monospace", fontSize: "0.9em" }}
      />
    </Form.Group>
  );
}


// ── Type 1 Email Topic Monitor — apple_mail or gmail (Track B Phase B1) ──

interface GmailAccountOption {
  id: number;
  email: string;
  status: "active" | "disconnected" | "revoked";
}

interface Type1Props {
  config: Record<string, unknown>;
  onChange: (config: Record<string, unknown>) => void;
  set: (key: string, value: unknown) => void;
}

function Type1EmailMonitorForm({ config, onChange, set }: Type1Props) {
  const service = (config.service as string) || "apple_mail";
  const topics = (config.topics as string[]) || [];

  const [gmailAccounts, setGmailAccounts] = useState<GmailAccountOption[]>([]);
  const [gmailLoading, setGmailLoading] = useState(false);
  const [gmailError, setGmailError] = useState<string | null>(null);

  // Lazy-fetch gmail accounts only when service=gmail. Avoids hitting the
  // endpoint for the common apple_mail path.
  useEffect(() => {
    if (service !== "gmail") return;
    setGmailLoading(true);
    setGmailError(null);
    axiosClient
      .get<GmailAccountOption[]>("/gmail/accounts")
      .then((res) => setGmailAccounts(res.data))
      .catch((e: unknown) => {
        const err = e as { response?: { data?: { detail?: string } }; message?: string };
        setGmailError(err?.response?.data?.detail || err?.message || "Failed to load Gmail accounts.");
      })
      .finally(() => setGmailLoading(false));
  }, [service]);

  const handleServiceChange = (newService: string) => {
    // Switching service clears the per-service identifier so we don't carry
    // an apple_mail account string into a gmail-flavored run (or vice versa).
    const next: Record<string, unknown> = { ...config, service: newService };
    delete next.account;
    delete next.account_id;
    onChange(next);
  };

  const activeGmailAccounts = gmailAccounts.filter((a) => a.status === "active");

  return (
    <>
      <Row className="g-3">
        <Col md={6}>
          <Form.Group>
            <Form.Label>Email Service</Form.Label>
            <Form.Select
              value={service}
              onChange={(e) => handleServiceChange(e.target.value)}
            >
              <option value="apple_mail">Apple Mail</option>
              <option value="gmail">Gmail (Workspace)</option>
            </Form.Select>
          </Form.Group>
        </Col>
        <Col md={6}>
          <Form.Group>
            <Form.Label>{service === "gmail" ? "Gmail Account" : "Mail Account"}</Form.Label>
            {service === "gmail" ? (
              <>
                <Form.Select
                  value={(config.account_id as number | undefined) ?? ""}
                  onChange={(e) => set("account_id", e.target.value ? Number(e.target.value) : null)}
                  disabled={gmailLoading || activeGmailAccounts.length === 0}
                >
                  <option value="">
                    {gmailLoading
                      ? "Loading…"
                      : activeGmailAccounts.length === 0
                      ? "(no accounts connected)"
                      : "Select a connected account…"}
                  </option>
                  {activeGmailAccounts.map((a) => (
                    <option key={a.id} value={a.id}>{a.email}</option>
                  ))}
                </Form.Select>
                {gmailError && <Form.Text className="text-danger">{gmailError}</Form.Text>}
                {!gmailLoading && !gmailError && activeGmailAccounts.length === 0 && (
                  <Form.Text className="text-muted">
                    No Gmail accounts connected yet — visit Connections to add one.
                  </Form.Text>
                )}
              </>
            ) : (
              <Form.Select
                value={(config.account as string) || "iCloud"}
                onChange={(e) => set("account", e.target.value)}
              >
                {MAIL_ACCOUNTS.map((a) => (
                  <option key={a.value} value={a.value}>{a.label}</option>
                ))}
              </Form.Select>
            )}
          </Form.Group>
        </Col>
        <Col md={6}>
          <Form.Group>
            <Form.Label>{service === "gmail" ? "Label" : "Mailbox"}</Form.Label>
            <Form.Control
              value={(config.mailbox as string) || "INBOX"}
              onChange={(e) => set("mailbox", e.target.value)}
            />
            {service === "gmail" && (
              <Form.Text className="text-muted">
                Gmail label id (e.g. INBOX, SPAM, or a custom label).
              </Form.Text>
            )}
          </Form.Group>
        </Col>
        <Col md={6}>
          <Form.Group>
            <Form.Label>Time Period</Form.Label>
            <Form.Select
              value={(config.period as string) || "last 7 days"}
              onChange={(e) => set("period", e.target.value)}
            >
              {PERIOD_OPTIONS.map((p) => (
                <option key={p} value={p}>{p}</option>
              ))}
            </Form.Select>
          </Form.Group>
        </Col>
        <Col md={6}>
          <Form.Group>
            <Form.Label>
              Topics <span className="text-muted fw-normal">(leave empty for AI to decide)</span>
            </Form.Label>
            <Form.Control
              placeholder="Business & Finance, Technology & AI, ..."
              value={topics.join(", ")}
              onChange={(e) => {
                const val = e.target.value;
                set("topics", val ? val.split(",").map((t) => t.trim()).filter(Boolean) : []);
              }}
            />
          </Form.Group>
        </Col>
        <Col md={12}>
          <Form.Group>
            <Form.Label>
              Scope <span className="text-muted fw-normal">("all" = everything, or describe a focus area)</span>
            </Form.Label>
            <Form.Control
              placeholder='e.g. "all", "AI and machine learning", "client projects", "financial matters"'
              value={(config.scope as string) || ""}
              onChange={(e) => set("scope", e.target.value)}
            />
            <Form.Text className="text-muted">
              When set, the AI will only categorize emails related to this scope and skip the rest.
            </Form.Text>
          </Form.Group>
        </Col>
      </Row>
      {topics.length > 0 && (
        <div className="mt-2">
          {topics.map((t, i) => (
            <Badge key={i} bg="secondary" className="me-1">{t}</Badge>
          ))}
        </div>
      )}
    </>
  );
}
