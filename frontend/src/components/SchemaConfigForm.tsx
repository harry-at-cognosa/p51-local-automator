/**
 * Generic config form driven by a schema descriptor list.
 *
 * Reads workflow_types.config_schema (an array of field descriptors) and
 * renders a Bootstrap form. Designed for future workflow types — types
 * 1–6 keep their hand-tuned forms in WorkflowConfigForm.tsx for now.
 *
 * Field types supported: string, multiline, number, date, string_list,
 * select, checkbox_list, file_picker.
 */
import { useState } from "react";
import { Form, Row, Col, Badge, Button, InputGroup } from "react-bootstrap";
import FilePicker, { type FilePickerSelection } from "./FilePicker";

export interface FieldOption {
  value: string;
  label: string;
}

export interface FieldDescriptor {
  name: string;
  label: string;
  label_suffix?: string;
  type:
    | "string"
    | "multiline"
    | "number"
    | "date"
    | "string_list"
    | "select"
    | "checkbox_list"
    | "file_picker";
  default?: unknown;
  placeholder?: string;
  help?: string;
  width?: "third" | "half" | "full";
  options?: FieldOption[];
  options_simple?: string[];
  min?: number;
  max?: number;
  rows?: number;
  mono?: boolean;
  show_badges?: boolean;
  filter_extensions?: string[];   // file_picker only
}

interface Props {
  schema: FieldDescriptor[];
  config: Record<string, unknown>;
  onChange: (config: Record<string, unknown>) => void;
}

const widthToCol = (w?: string) =>
  w === "full" ? 12 : w === "third" ? 4 : 6;

export default function SchemaConfigForm({ schema, config, onChange }: Props) {
  const set = (key: string, value: unknown) => {
    onChange({ ...config, [key]: value });
  };

  return (
    <Row className="g-3">
      {schema.map((f) => {
        const current = config[f.name] ?? f.default ?? "";
        return (
          <Col key={f.name} md={widthToCol(f.width)}>
            <Form.Group>
              <Form.Label>
                {f.label}
                {f.label_suffix && (
                  <span className="text-muted fw-normal"> {f.label_suffix}</span>
                )}
              </Form.Label>
              {renderInput(f, current, set)}
              {f.help && <Form.Text className="text-muted">{f.help}</Form.Text>}
              {f.type === "string_list" && f.show_badges && renderBadges(current)}
            </Form.Group>
          </Col>
        );
      })}
    </Row>
  );
}

function renderInput(
  f: FieldDescriptor,
  current: unknown,
  set: (k: string, v: unknown) => void,
) {
  const monoStyle = f.mono ? { fontFamily: "monospace", fontSize: "0.9em" } : undefined;

  switch (f.type) {
    case "string":
      return (
        <Form.Control
          type="text"
          placeholder={f.placeholder}
          value={(current as string) || ""}
          onChange={(e) => set(f.name, e.target.value)}
        />
      );

    case "multiline":
      return (
        <Form.Control
          as="textarea"
          rows={f.rows ?? 4}
          placeholder={f.placeholder}
          value={(current as string) || ""}
          onChange={(e) => set(f.name, e.target.value)}
          style={monoStyle}
        />
      );

    case "number":
      return (
        <Form.Control
          type="number"
          min={f.min}
          max={f.max}
          value={
            typeof current === "number" || typeof current === "string"
              ? (current as number | string)
              : (f.default as number) ?? 0
          }
          onChange={(e) => set(f.name, Number(e.target.value))}
        />
      );

    case "date":
      return (
        <Form.Control
          type="date"
          value={(current as string) || ""}
          onChange={(e) => set(f.name, e.target.value)}
        />
      );

    case "string_list": {
      const list = Array.isArray(current) ? (current as string[]) : [];
      return (
        <Form.Control
          type="text"
          placeholder={f.placeholder}
          value={list.join(", ")}
          onChange={(e) => {
            const v = e.target.value;
            set(
              f.name,
              v ? v.split(",").map((t) => t.trim()).filter(Boolean) : [],
            );
          }}
        />
      );
    }

    case "select":
      return (
        <Form.Select
          value={(current as string) || ""}
          onChange={(e) => set(f.name, e.target.value)}
        >
          {(f.options ?? []).map((opt) => (
            <option key={opt.value} value={opt.value}>
              {opt.label}
            </option>
          ))}
        </Form.Select>
      );

    case "checkbox_list": {
      const selected = Array.isArray(current) ? (current as string[]) : [];
      return (
        <>
          {(f.options_simple ?? []).map((opt) => (
            <Form.Check
              key={opt}
              type="checkbox"
              label={opt}
              checked={selected.includes(opt)}
              onChange={(e) => {
                if (e.target.checked) {
                  set(f.name, [...selected, opt]);
                } else {
                  set(f.name, selected.filter((x) => x !== opt));
                }
              }}
            />
          ))}
        </>
      );
    }

    case "file_picker":
      return <FilePickerInput field={f} value={current} onChange={(v) => set(f.name, v)} />;

    default:
      return (
        <Form.Control
          type="text"
          value={String(current ?? "")}
          onChange={(e) => set(f.name, e.target.value)}
        />
      );
  }
}

function FilePickerInput({
  field,
  value,
  onChange,
}: {
  field: FieldDescriptor;
  value: unknown;
  onChange: (v: FilePickerSelection | null) => void;
}) {
  const [show, setShow] = useState(false);
  const sel = (value as FilePickerSelection | null) || null;
  const display = sel?.path || "No file selected";
  return (
    <>
      <InputGroup>
        <Form.Control readOnly value={display} placeholder={field.placeholder} />
        <Button variant="outline-secondary" onClick={() => setShow(true)}>
          Pick file
        </Button>
        {sel && (
          <Button variant="outline-secondary" onClick={() => onChange(null)}>
            Clear
          </Button>
        )}
      </InputGroup>
      <FilePicker
        show={show}
        mode="file"
        filterExtensions={field.filter_extensions}
        onSelect={(s) => {
          onChange(s);
          setShow(false);
        }}
        onCancel={() => setShow(false)}
      />
    </>
  );
}

function renderBadges(current: unknown) {
  const list = Array.isArray(current) ? (current as string[]) : [];
  if (list.length === 0) return null;
  return (
    <div className="mt-2">
      {list.map((t, i) => (
        <Badge key={i} bg="secondary" className="me-1">
          {t}
        </Badge>
      ))}
    </div>
  );
}
