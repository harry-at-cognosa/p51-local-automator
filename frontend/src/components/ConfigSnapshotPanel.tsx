/**
 * Renders the configuration that was in effect when a workflow run started,
 * driven by the workflow type's config_schema (Phase 5 metadata).
 *
 * Read-only. Editing the live workflow config does NOT modify the snapshot —
 * historic runs always reflect the config they ran under.
 *
 * Three states:
 *   - snapshot is null  → "Configuration not captured (older run)" message.
 *   - schema is null    → raw JSON fallback (workflow type lacks config_schema).
 *   - both present      → labeled per-field display, markdown-rendered for
 *                         multiline text fields.
 */
import { Card, Table, Badge } from "react-bootstrap";
import type { FieldDescriptor, FieldOption } from "./SchemaConfigForm";
import MarkdownRender from "./MarkdownRender";

interface Props {
  snapshot: Record<string, unknown> | null | undefined;
  schema: FieldDescriptor[] | null | undefined;
}

const formatPlain = (v: unknown): string => {
  if (v === null || v === undefined || v === "") return "—";
  if (typeof v === "string") return v;
  if (typeof v === "number" || typeof v === "boolean") return String(v);
  if (Array.isArray(v)) return v.map((x) => String(x)).join(", ") || "—";
  return JSON.stringify(v);
};

const formatSelect = (v: unknown, options?: FieldOption[]): string => {
  if (typeof v !== "string") return formatPlain(v);
  const match = options?.find((o) => o.value === v);
  return match ? match.label : v || "—";
};

interface FilePickerVal {
  path: string;
  name: string;
}

const renderFilePicker = (v: unknown): React.ReactNode => {
  if (!v || typeof v !== "object") return <span className="text-muted">—</span>;
  const sel = v as FilePickerVal;
  if (!sel.path) return <span className="text-muted">—</span>;
  return <code>{sel.path}</code>;
};

const renderRepeatingRows = (
  v: unknown,
  rowSchema: FieldDescriptor[] | undefined,
): React.ReactNode => {
  if (!Array.isArray(v) || v.length === 0) {
    return <span className="text-muted">No rows</span>;
  }
  const sub = rowSchema ?? [];
  return (
    <Table size="sm" bordered className="mb-0">
      <thead>
        <tr>
          {sub.map((s) => (
            <th key={s.name}>{s.label}</th>
          ))}
        </tr>
      </thead>
      <tbody>
        {(v as Record<string, unknown>[]).map((row, i) => (
          <tr key={i}>
            {sub.map((s) => (
              <td key={s.name}>{renderFieldValue(s, row[s.name])}</td>
            ))}
          </tr>
        ))}
      </tbody>
    </Table>
  );
};

const renderFieldValue = (field: FieldDescriptor, value: unknown): React.ReactNode => {
  switch (field.type) {
    case "multiline": {
      const text = typeof value === "string" ? value : "";
      if (!text) return <span className="text-muted">—</span>;
      return <MarkdownRender source={text} />;
    }
    case "string_list": {
      if (!Array.isArray(value) || value.length === 0) return <span className="text-muted">—</span>;
      return (
        <>
          {(value as string[]).map((t, i) => (
            <Badge key={i} bg="secondary" className="me-1">{t}</Badge>
          ))}
        </>
      );
    }
    case "checkbox_list": {
      if (!Array.isArray(value) || value.length === 0) return <span className="text-muted">—</span>;
      return (
        <>
          {(value as string[]).map((t, i) => (
            <Badge key={i} bg="info" className="me-1">{t}</Badge>
          ))}
        </>
      );
    }
    case "select":
      return formatSelect(value, field.options);
    case "file_picker":
      return renderFilePicker(value);
    case "repeating_rows":
      return renderRepeatingRows(value, field.row_schema);
    case "number":
    case "date":
    case "string":
    default:
      return formatPlain(value);
  }
};

export default function ConfigSnapshotPanel({ snapshot, schema }: Props) {
  if (!snapshot) {
    return (
      <Card className="mb-4">
        <Card.Header>Configuration used for this run</Card.Header>
        <Card.Body>
          <span className="text-muted">Configuration not captured (older run, pre-Phase 1).</span>
        </Card.Body>
      </Card>
    );
  }

  if (!schema || schema.length === 0) {
    return (
      <Card className="mb-4">
        <Card.Header>Configuration used for this run</Card.Header>
        <Card.Body>
          <pre className="bg-light p-2 rounded small mb-0">
            {JSON.stringify(snapshot, null, 2)}
          </pre>
        </Card.Body>
      </Card>
    );
  }

  return (
    <Card className="mb-4">
      <Card.Header>Configuration used for this run</Card.Header>
      <Card.Body>
        <Table size="sm" className="mb-0">
          <tbody>
            {schema.map((field) => (
              <tr key={field.name}>
                <th style={{ width: "25%", verticalAlign: "top" }}>
                  {field.label}
                  {field.label_suffix && (
                    <span className="text-muted fw-normal small"> {field.label_suffix}</span>
                  )}
                </th>
                <td>{renderFieldValue(field, snapshot[field.name])}</td>
              </tr>
            ))}
          </tbody>
        </Table>
      </Card.Body>
    </Card>
  );
}
