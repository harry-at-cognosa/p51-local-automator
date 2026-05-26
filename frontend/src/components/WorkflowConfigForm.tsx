import React, { useEffect, useState } from "react";
import { Accordion, Form, Row, Col, Badge, Button, InputGroup } from "react-bootstrap";
import { Link } from "react-router-dom";
import SchemaConfigForm, { type FieldDescriptor } from "./SchemaConfigForm";
import FilePicker, { type FilePickerSelection } from "./FilePicker";
import axiosClient from "../api/axiosClient";

// ── Advanced limits section, shared across hand-tuned forms ─────────
//
// Each Types 1–6 form appends an <AdvancedLimitsSection /> with the
// type's relevant numeric knobs. Blank input means "use whatever
// resolve_int_setting() resolves at run time" (group_settings →
// api_settings → runner fallback). The placeholder displays the
// currently-configured api_settings default for the field.

interface LimitField {
  key: string;
  label: string;
  defaultValue: number | null;  // shown in placeholder; null = "(no cap)"
  help?: string;
  min?: number;
  max?: number;
}

function AdvancedLimitsSection({
  config,
  set,
  fields,
}: {
  config: Record<string, unknown>;
  set: (key: string, value: unknown) => void;
  fields: LimitField[];
}) {
  return (
    <Accordion className="mt-3">
      <Accordion.Item eventKey="advanced-limits">
        <Accordion.Header>Advanced — limits and caps</Accordion.Header>
        <Accordion.Body>
          <Row className="g-3">
            {fields.map((f) => (
              <Col md={6} key={f.key}>
                <Form.Group>
                  <Form.Label>{f.label}</Form.Label>
                  <Form.Control
                    type="number"
                    min={f.min}
                    max={f.max}
                    placeholder={
                      f.defaultValue !== null
                        ? `Default: ${f.defaultValue}`
                        : "(no cap)"
                    }
                    value={
                      typeof config[f.key] === "number" || typeof config[f.key] === "string"
                        ? (config[f.key] as number | string)
                        : ""
                    }
                    onChange={(e) => {
                      const v = e.target.value;
                      if (v === "") {
                        set(f.key, undefined);
                      } else {
                        const n = parseInt(v, 10);
                        set(f.key, Number.isNaN(n) ? undefined : n);
                      }
                    }}
                  />
                  {f.help && <Form.Text className="text-muted">{f.help}</Form.Text>}
                </Form.Group>
              </Col>
            ))}
          </Row>
        </Accordion.Body>
      </Accordion.Item>
    </Accordion>
  );
}

const LIMITS_TYPE1: LimitField[] = [
  { key: "email_fetch_limit", label: "Max emails fetched per account", defaultValue: 100, min: 1,
    help: "Per run, per account. Larger values raise API/IMAP cost." },
];

const LIMITS_TYPE2: LimitField[] = [
  { key: "analyzer_timeout_seconds", label: "Analyzer script timeout (sec)", defaultValue: 120, min: 5 },
  { key: "analyzer_text_truncate_chars", label: "Profile/summary text cap (chars)", defaultValue: 8000, min: 500,
    help: "Each markdown report sent to the LLM is truncated to this length." },
];

const LIMITS_TYPE4: LimitField[] = [
  { key: "sql_llm_sample_rows", label: "Rows sent to LLM for analysis", defaultValue: 50, min: 1 },
  { key: "sql_row_limit", label: "Hard cap on returned rows", defaultValue: null,
    help: "Blank = no cap; query results pass through unbounded." },
];

const LIMITS_TYPE56: LimitField[] = [
  { key: "reply_max_candidates", label: "Max reply drafts per run", defaultValue: 20, min: 1,
    help: "After dedup-by-sender, run stops generating once this many drafts exist." },
];

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
  /**
   * Per-type opt-in flag for the "email me results" final step. When TRUE,
   * the EmailResultsSection is rendered below the per-type form.
   */
  emailableResults?: boolean;
  /**
   * {kind_key: human_label} the workflow type produces. Drives the checkboxes
   * in the EmailResultsSection. Empty when the type doesn't opt in.
   */
  emailArtifactKinds?: Record<string, string>;
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

export default function WorkflowConfigForm({
  typeId,
  config,
  onChange,
  configSchema,
  emailableResults,
  emailArtifactKinds,
}: Props) {
  const set = (key: string, value: unknown) => {
    onChange({ ...config, [key]: value });
  };

  const emailSection = emailableResults ? (
    <EmailResultsSection
      config={config}
      set={set}
      kinds={emailArtifactKinds || {}}
    />
  ) : null;

  // Email Topic Monitor — extracted to its own component so the
  // service-switch + gmail-accounts fetch can use hooks.
  if (typeId === 1) {
    return (
      <>
        <Type1EmailMonitorForm config={config} onChange={onChange} set={set} />
        {emailSection}
      </>
    );
  }

  // Transaction Data Analyzer — extracted to a subcomponent so the
  // FilePicker modal can own its show/hide state via hooks.
  if (typeId === 2) {
    return (
      <>
        <Type2DataAnalyzerForm config={config} onChange={onChange} set={set} />
        {emailSection}
      </>
    );
  }

  // Calendar Digest — apple_calendar (existing) or google_calendar (Track GC).
  // Subcomponent owns hooks for the lazy-fetch of the Google calendar list.
  if (typeId === 3) {
    return (
      <>
        <Type3CalendarDigestForm config={config} onChange={onChange} set={set} />
        {emailSection}
      </>
    );
  }

  // SQL Query Runner — wraps the return so the email section can append
  // below the existing inline JSX.
  const wrapWithEmail = (node: React.ReactNode) => (
    <>
      {node}
      {emailSection}
    </>
  );

  if (typeId === 4) {
    const hasStoredSecret = Boolean(config.connection_string_enc);
    return wrapWithEmail(
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
        <Col md={12}>
          <AdvancedLimitsSection config={config} set={set} fields={LIMITS_TYPE4} />
        </Col>
      </Row>
    );
  }

  // Auto-Reply (Draft Only) = type 5, Auto-Reply (Approve Before Send) = type 6.
  // Same config shape for both; subcomponent owns hooks for the gmail
  // account picker (Track B Phase B2).
  if (typeId === 5 || typeId === 6) {
    return wrapWithEmail(<Type56AutoReplyForm config={config} onChange={onChange} set={set} />);
  }

  // Schema-driven path for new workflow types whose typeId has no
  // hand-tuned branch above. The backend's config_schema describes the
  // fields and the generic renderer handles them.
  if (configSchema && configSchema.length > 0) {
    return wrapWithEmail(<SchemaConfigForm schema={configSchema} config={config} onChange={onChange} />);
  }

  // Final fallback: raw JSON when no schema is available either.
  return wrapWithEmail(
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


// ── EmailResultsSection — opt-in "email me my results" final-step config ──

interface EmailResultsSectionProps {
  config: Record<string, unknown>;
  set: (key: string, value: unknown) => void;
  kinds: Record<string, string>;
}

interface MeOutboundInfo {
  outbound_service: string | null;
  outbound_identifier: string | null;
}

function EmailResultsSection({ config, set, kinds }: EmailResultsSectionProps) {
  const [me, setMe] = useState<MeOutboundInfo | null>(null);

  useEffect(() => {
    let cancelled = false;
    axiosClient
      .get<MeOutboundInfo>("/users/me")
      .then((res) => { if (!cancelled) setMe(res.data); })
      .catch(() => { if (!cancelled) setMe({ outbound_service: null, outbound_identifier: null }); });
    return () => { cancelled = true; };
  }, []);

  const emailCfg = (config.email_results as { enabled?: boolean; artifact_kinds?: string[] } | undefined) || {};
  const enabled = Boolean(emailCfg.enabled);
  const selectedKinds = emailCfg.artifact_kinds || [];

  const setEmailCfg = (next: { enabled?: boolean; artifact_kinds?: string[] }) => {
    set("email_results", { ...emailCfg, ...next });
  };

  const toggleKind = (kind: string, checked: boolean) => {
    const cur = new Set(selectedKinds);
    if (checked) cur.add(kind);
    else cur.delete(kind);
    setEmailCfg({ artifact_kinds: Array.from(cur) });
  };

  const hasOutbound = Boolean(me?.outbound_service);
  const outboundLabel = describeOutbound(me);

  return (
    <Row className="g-3 mt-3 pt-3 border-top">
      <Col md={12}>
        <h6>Email results</h6>
        <Form.Check
          type="checkbox"
          id="email-results-enabled"
          label="Email me selected results when this workflow finishes"
          checked={enabled}
          disabled={!hasOutbound}
          onChange={(e) => setEmailCfg({ enabled: e.target.checked })}
        />
        {!hasOutbound && (
          <Form.Text className="text-muted d-block ms-4">
            Set your outbound results email in{" "}
            <Link to="/app/profile">Profile</Link> first to enable this option.
          </Form.Text>
        )}
        {hasOutbound && enabled && (
          <>
            <Form.Text className="text-muted d-block ms-4 mb-2">
              Will be sent via: {outboundLabel} — change in{" "}
              <Link to="/app/profile">Profile</Link>.
            </Form.Text>
            {Object.keys(kinds).length === 0 ? (
              <Form.Text className="text-muted d-block ms-4">
                (No selectable artifact kinds defined for this workflow type — nothing to attach.)
              </Form.Text>
            ) : (
              <div className="ms-4">
                <div className="text-muted small mb-1">Attach:</div>
                {Object.entries(kinds).map(([key, label]) => (
                  <Form.Check
                    type="checkbox"
                    key={key}
                    id={`email-results-kind-${key}`}
                    label={label}
                    checked={selectedKinds.includes(key)}
                    onChange={(e) => toggleKind(key, e.target.checked)}
                  />
                ))}
              </div>
            )}
          </>
        )}
      </Col>
    </Row>
  );
}

function describeOutbound(me: MeOutboundInfo | null): string {
  if (!me || !me.outbound_service) return "(unset)";
  const svc = me.outbound_service;
  const ident = me.outbound_identifier || "";
  if (svc === "apple_mail") {
    try {
      const blob = JSON.parse(ident) as { account_name?: string; destination?: string };
      const dest = blob.destination || "(no destination)";
      const sender = blob.account_name || "Mail.app default";
      return `Apple Mail (${sender}) → ${dest}`;
    } catch {
      return "Apple Mail (invalid config)";
    }
  }
  if (svc === "gmail") return `Gmail OAuth account #${ident}`;
  if (svc === "gmail_imap") return `Gmail App Password (${ident})`;
  return svc;
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
    // an apple_mail account string, a gmail OAuth account_id, or a
    // gmail_imap email into the wrong-service run.
    const next: Record<string, unknown> = { ...config, service: newService };
    delete next.account;
    delete next.account_id;
    delete next.email;
    delete next.app_password;
    // app_password_enc and storage_method are intentionally preserved across
    // a service flip so the user doesn't lose a stored credential by toggling
    // accidentally. The runner ignores them when service != gmail_imap.
    onChange(next);
  };

  const activeGmailAccounts = gmailAccounts.filter((a) => a.status === "active");
  const hasStoredAppPassword = Boolean(config.app_password_enc);

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
              <option value="gmail">Gmail (connected workspace account)</option>
              <option value="gmail_imap">Gmail (App Password — for consumer Gmail)</option>
            </Form.Select>
          </Form.Group>
        </Col>
        <Col md={6}>
          {service === "apple_mail" && (
            <Form.Group>
              <Form.Label>Mail Account</Form.Label>
              <Form.Control
                type="text"
                list="mail-accounts-datalist"
                value={(config.account as string) || ""}
                placeholder="e.g. iCloud, harry@cognosa.net"
                onChange={(e) => set("account", e.target.value)}
              />
              <datalist id="mail-accounts-datalist">
                {MAIL_ACCOUNTS.map((a) => (
                  <option key={a.value} value={a.value}>{a.label}</option>
                ))}
              </datalist>
              <Form.Text className="text-muted">
                Must match the account name exactly as it appears in Mail.app → Settings → Accounts.
                Suggestions in the dropdown are starting points; type the actual name if it differs.
              </Form.Text>
            </Form.Group>
          )}
          {service === "gmail" && (
            <Form.Group>
              <Form.Label>Gmail Account</Form.Label>
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
            </Form.Group>
          )}
          {service === "gmail_imap" && (
            <Form.Group>
              <Form.Label>Gmail address</Form.Label>
              <Form.Control
                type="email"
                value={(config.email as string) || ""}
                placeholder="you@gmail.com"
                onChange={(e) => set("email", e.target.value)}
              />
            </Form.Group>
          )}
        </Col>
        {service === "gmail_imap" && (
          <>
            <Col md={6}>
              <Form.Group>
                <Form.Label>
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
                  value={(config.app_password as string) || ""}
                  placeholder={
                    hasStoredAppPassword
                      ? "(stored — leave blank to keep, or type to replace)"
                      : "16-char code"
                  }
                  onChange={(e) => set("app_password", e.target.value)}
                />
                {hasStoredAppPassword && (
                  <Form.Text className="text-muted">
                    Password is stored encrypted. The original value is not
                    displayed. Leave blank to keep; type a new value to replace.
                  </Form.Text>
                )}
              </Form.Group>
            </Col>
            <Col md={6}>
              <Form.Group>
                <Form.Label>Credential storage</Form.Label>
                <Form.Check
                  type="radio"
                  id="t1-storage-enc"
                  name="t1_storage_method"
                  label="Encrypted database column (recommended)"
                  checked={((config.storage_method as string) || "encrypted_db") === "encrypted_db"}
                  onChange={() => set("storage_method", "encrypted_db")}
                />
                <Form.Check
                  type="radio"
                  id="t1-storage-plain"
                  name="t1_storage_method"
                  label="Plaintext .gmailpasswords.json (per-machine)"
                  checked={(config.storage_method as string) === "plaintext_file"}
                  onChange={() => set("storage_method", "plaintext_file")}
                />
              </Form.Group>
            </Col>
          </>
        )}
        <Col md={6}>
          <Form.Group>
            <Form.Label>{service === "apple_mail" ? "Mailbox" : "Label"}</Form.Label>
            <Form.Control
              value={(config.mailbox as string) || "INBOX"}
              onChange={(e) => set("mailbox", e.target.value)}
            />
            {service !== "apple_mail" && (
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
      <AdvancedLimitsSection config={config} set={set} fields={LIMITS_TYPE1} />
    </>
  );
}


// ── Types 5/6 Auto-Reply form — apple_mail or gmail (Track B Phase B2) ──

interface Type56Props {
  config: Record<string, unknown>;
  onChange: (config: Record<string, unknown>) => void;
  set: (key: string, value: unknown) => void;
}

function Type56AutoReplyForm({ config, onChange, set }: Type56Props) {
  const service = (config.service as string) || "apple_mail";

  const [gmailAccounts, setGmailAccounts] = useState<GmailAccountOption[]>([]);
  const [gmailLoading, setGmailLoading] = useState(false);
  const [gmailError, setGmailError] = useState<string | null>(null);

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
    const next: Record<string, unknown> = { ...config, service: newService };
    delete next.account;
    delete next.account_id;
    onChange(next);
  };

  const activeGmailAccounts = gmailAccounts.filter((a) => a.status === "active");

  return (
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
          <Form.Text className="text-muted">
            {service === "gmail"
              ? "Drafts and sends use the connected Gmail account below."
              : "Drafts and sends use this Apple Mail account."}
          </Form.Text>
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
                <option value="">— select an account —</option>
                {activeGmailAccounts.map((a) => (
                  <option key={a.id} value={a.id}>{a.email}</option>
                ))}
              </Form.Select>
              {gmailLoading && (
                <Form.Text className="text-muted">Loading Gmail accounts…</Form.Text>
              )}
              {gmailError && (
                <Form.Text className="text-danger">{gmailError}</Form.Text>
              )}
              {!gmailLoading && !gmailError && activeGmailAccounts.length === 0 && (
                <Form.Text className="text-muted">
                  No active Gmail accounts. Connect one at <code>/app/connections</code>.
                </Form.Text>
              )}
            </>
          ) : (
            <>
              <Form.Control
                type="text"
                list="mail-accounts-datalist-t56"
                value={(config.account as string) || ""}
                placeholder="e.g. iCloud, harry@cognosa.net"
                onChange={(e) => set("account", e.target.value)}
              />
              <datalist id="mail-accounts-datalist-t56">
                {MAIL_ACCOUNTS.map((a) => (
                  <option key={a.value} value={a.value}>{a.label}</option>
                ))}
              </datalist>
              <Form.Text className="text-muted">
                Must match the account name exactly as it appears in Mail.app → Settings → Accounts.
              </Form.Text>
            </>
          )}
        </Form.Group>
      </Col>
      <Col md={6}>
        <Form.Group>
          <Form.Label>Mailbox</Form.Label>
          <Form.Control
            value={(config.mailbox as string) || "INBOX"}
            onChange={(e) => set("mailbox", e.target.value)}
          />
          <Form.Text className="text-muted">
            {service === "gmail" ? "Gmail label (INBOX, or any custom label)." : "Apple Mail mailbox."}
          </Form.Text>
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
          <Form.Label>Sender filter (substring, case-insensitive)</Form.Label>
          <Form.Control
            placeholder="e.g. form-submission@squarespace.info"
            value={(config.sender_filter as string) || ""}
            onChange={(e) => set("sender_filter", e.target.value)}
          />
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
            For form-submission emails where the sender is a no-reply transport (e.g. <code>form-submission@squarespace.info</code>), specify the body label that precedes the actual submitter's email. Leave blank for emails with a real Reply-To header.
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
      <Col md={12}>
        <AdvancedLimitsSection config={config} set={set} fields={LIMITS_TYPE56} />
      </Col>
    </Row>
  );
}


// ── Type 3 Calendar Digest — apple_calendar or google_calendar (Track GC) ──

interface Type3Props {
  config: Record<string, unknown>;
  onChange: (config: Record<string, unknown>) => void;
  set: (key: string, value: unknown) => void;
}

interface GoogleCalendarOption {
  id: string;
  summary: string;
  primary: boolean;
  access_role: string;
  color: string;
}

function Type3CalendarDigestForm({ config, onChange, set }: Type3Props) {
  const service = (config.service as string) || "apple_calendar";

  const [gmailAccounts, setGmailAccounts] = useState<GmailAccountOption[]>([]);
  const [gmailLoading, setGmailLoading] = useState(false);
  const [gmailError, setGmailError] = useState<string | null>(null);

  const [calendars, setCalendars] = useState<GoogleCalendarOption[]>([]);
  const [calendarsLoading, setCalendarsLoading] = useState(false);
  const [calendarsError, setCalendarsError] = useState<string | null>(null);

  const accountId = config.account_id as number | undefined;

  // Load gmail accounts when service flips to google_calendar.
  useEffect(() => {
    if (service !== "google_calendar") return;
    setGmailLoading(true);
    setGmailError(null);
    axiosClient
      .get<GmailAccountOption[]>("/gmail/accounts")
      .then((res) => setGmailAccounts(res.data))
      .catch((e: unknown) => {
        const err = e as { response?: { data?: { detail?: string } }; message?: string };
        setGmailError(err?.response?.data?.detail || err?.message || "Failed to load Google accounts.");
      })
      .finally(() => setGmailLoading(false));
  }, [service]);

  // Load calendars when an account is picked.
  useEffect(() => {
    if (service !== "google_calendar" || !accountId) {
      setCalendars([]);
      return;
    }
    setCalendarsLoading(true);
    setCalendarsError(null);
    axiosClient
      .get<GoogleCalendarOption[]>(`/google-calendar/calendars?account_id=${accountId}`)
      .then((res) => setCalendars(res.data))
      .catch((e: unknown) => {
        const err = e as { response?: { data?: { detail?: string } }; message?: string };
        setCalendarsError(err?.response?.data?.detail || err?.message || "Failed to load calendars.");
      })
      .finally(() => setCalendarsLoading(false));
  }, [service, accountId]);

  const handleServiceChange = (newService: string) => {
    const next: Record<string, unknown> = { ...config, service: newService };
    delete next.calendars;
    delete next.calendar_ids;
    delete next.account_id;
    onChange(next);
  };

  const activeGmailAccounts = gmailAccounts.filter((a) => a.status === "active");
  const selectedAppleCals = (config.calendars as string[]) || ["Work", "Family"];
  const selectedGoogleCalIds = (config.calendar_ids as string[]) || [];

  return (
    <Row className="g-3">
      <Col md={6}>
        <Form.Group>
          <Form.Label>Calendar Service</Form.Label>
          <Form.Select
            value={service}
            onChange={(e) => handleServiceChange(e.target.value)}
          >
            <option value="apple_calendar">Apple Calendar</option>
            <option value="google_calendar">Google Calendar (Workspace)</option>
          </Form.Select>
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

      {service === "apple_calendar" ? (
        <Col md={12}>
          <Form.Group>
            <Form.Label>Calendars</Form.Label>
            {CALENDAR_OPTIONS.map((cal) => (
              <Form.Check
                key={cal}
                type="checkbox"
                label={cal}
                checked={selectedAppleCals.includes(cal)}
                onChange={(e) => {
                  if (e.target.checked) {
                    set("calendars", [...selectedAppleCals, cal]);
                  } else {
                    set("calendars", selectedAppleCals.filter((c) => c !== cal));
                  }
                }}
              />
            ))}
          </Form.Group>
        </Col>
      ) : (
        <>
          <Col md={6}>
            <Form.Group>
              <Form.Label>Google Account</Form.Label>
              <Form.Select
                value={accountId ?? ""}
                onChange={(e) => set("account_id", e.target.value ? Number(e.target.value) : null)}
                disabled={gmailLoading || activeGmailAccounts.length === 0}
              >
                <option value="">— select an account —</option>
                {activeGmailAccounts.map((a) => (
                  <option key={a.id} value={a.id}>{a.email}</option>
                ))}
              </Form.Select>
              {gmailLoading && <Form.Text className="text-muted">Loading accounts…</Form.Text>}
              {gmailError && <Form.Text className="text-danger">{gmailError}</Form.Text>}
              {!gmailLoading && !gmailError && activeGmailAccounts.length === 0 && (
                <Form.Text className="text-muted">
                  No active Google accounts. Connect one at <code>/app/connections</code>.
                </Form.Text>
              )}
            </Form.Group>
          </Col>
          <Col md={12}>
            <Form.Group>
              <Form.Label>Calendars</Form.Label>
              {!accountId && <Form.Text className="text-muted d-block">Select an account above first.</Form.Text>}
              {accountId !== undefined && calendarsLoading && (
                <Form.Text className="text-muted d-block">Loading calendars…</Form.Text>
              )}
              {calendarsError && (
                <Form.Text className="text-danger d-block">{calendarsError}</Form.Text>
              )}
              {accountId !== undefined && !calendarsLoading && !calendarsError && calendars.length === 0 && (
                <Form.Text className="text-muted d-block">No calendars found.</Form.Text>
              )}
              {calendars.map((cal) => (
                <Form.Check
                  key={cal.id}
                  type="checkbox"
                  label={
                    <>
                      {cal.summary}
                      {cal.primary && <Badge bg="secondary" className="ms-2">primary</Badge>}
                    </>
                  }
                  checked={selectedGoogleCalIds.includes(cal.id)}
                  onChange={(e) => {
                    if (e.target.checked) {
                      set("calendar_ids", [...selectedGoogleCalIds, cal.id]);
                    } else {
                      set("calendar_ids", selectedGoogleCalIds.filter((c) => c !== cal.id));
                    }
                  }}
                />
              ))}
            </Form.Group>
          </Col>
        </>
      )}
    </Row>
  );
}


interface Type2Props {
  config: Record<string, unknown>;
  onChange: (config: Record<string, unknown>) => void;
  set: (key: string, value: unknown) => void;
}

function Type2DataAnalyzerForm({ config, set }: Type2Props) {
  const [showPicker, setShowPicker] = useState(false);

  // Tolerate three shapes for config.file_path:
  //   { path, name }  — current shape after T2S
  //   string          — legacy rows that predate T2S (migration in T2S.3)
  //   undefined       — fresh workflow
  const fp = config.file_path;
  let display = "No file selected";
  if (fp && typeof fp === "object" && "path" in fp) {
    const sel = fp as FilePickerSelection;
    display = sel.name || sel.path;
  } else if (typeof fp === "string" && fp.trim()) {
    display = fp;
  }

  const onSelect = (selection: FilePickerSelection) => {
    set("file_path", selection);
    setShowPicker(false);
  };

  return (
    <Row className="g-3">
      <Col md={12}>
        <Form.Group>
          <Form.Label>Data File</Form.Label>
          <InputGroup>
            <Form.Control readOnly value={display} />
            <Button variant="outline-secondary" onClick={() => setShowPicker(true)}>
              Pick file
            </Button>
            {!!fp && (
              <Button
                variant="outline-secondary"
                onClick={() => set("file_path", null)}
              >
                Clear
              </Button>
            )}
          </InputGroup>
          <Form.Text className="text-muted">
            Pick from your inputs sandbox at
            {" "}
            <code>&lt;file_system_root&gt;/&#123;group_id&#125;/&#123;user_id&#125;/inputs/</code>.
            To add new files, drop them in via SMB or the local filesystem.
          </Form.Text>
        </Form.Group>
        <FilePicker
          show={showPicker}
          mode="file"
          filterExtensions={[".csv", ".xlsx"]}
          onSelect={onSelect}
          onCancel={() => setShowPicker(false)}
        />
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
      <Col md={12}>
        <AdvancedLimitsSection config={config} set={set} fields={LIMITS_TYPE2} />
      </Col>
    </Row>
  );
}
