/**
 * EmailSendBadge — small icon + tooltip surfacing the per-run delivery status
 * from workflow_run_email_log. Hidden when the run had no email-send attempt.
 */
import { OverlayTrigger, Tooltip } from "react-bootstrap";

interface Props {
  status: string | null | undefined;
  recipient?: string | null;
  error?: string | null;
}

interface StatusMeta {
  symbol: string;
  color: string;
  label: string;
}

const meta: Record<string, StatusMeta> = {
  sent: { symbol: "✉", color: "#198754", label: "Results emailed" },
  failed: { symbol: "✉", color: "#dc3545", label: "Email send failed" },
  skipped_no_outbound: { symbol: "✉", color: "#6c757d", label: "Email skipped — no outbound configured" },
  skipped_no_artifacts: { symbol: "✉", color: "#6c757d", label: "Email skipped — no matching artifacts" },
  skipped_disabled: { symbol: "✉", color: "#6c757d", label: "Email skipped — not enabled" },
};

export default function EmailSendBadge({ status, recipient, error }: Props) {
  if (!status) return null;
  const m = meta[status] ?? { symbol: "✉", color: "#6c757d", label: status };
  const tooltipLines = [m.label];
  if (recipient) tooltipLines.push(`To: ${recipient}`);
  if (error) tooltipLines.push(`Error: ${error}`);
  return (
    <OverlayTrigger
      placement="top"
      overlay={
        <Tooltip id={`email-send-tooltip-${status}`}>
          {tooltipLines.map((line, i) => (
            <div key={i}>{line}</div>
          ))}
        </Tooltip>
      }
    >
      <span
        style={{
          color: m.color,
          fontSize: "1.1em",
          cursor: "help",
          marginLeft: "0.4em",
        }}
        aria-label={m.label}
      >
        {m.symbol}
      </span>
    </OverlayTrigger>
  );
}
