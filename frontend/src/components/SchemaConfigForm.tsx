/**
 * Generic config form driven by a schema descriptor list.
 *
 * Reads workflow_types.config_schema (an array of field descriptors) and
 * renders a Bootstrap form. Designed for future workflow types — types
 * 1–6 keep their hand-tuned forms in WorkflowConfigForm.tsx for now.
 *
 * Field types supported: string, multiline, number, date, string_list,
 * select, checkbox_list, file_picker, repeating_rows.
 */
import { useState } from "react";
import { Form, Row, Col, Badge, Button, InputGroup, Card } from "react-bootstrap";
import FilePicker, { type FilePickerSelection } from "./FilePicker";
import axiosClient from "../api/axiosClient";

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
    | "file_picker"
    | "repeating_rows";
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
  row_schema?: FieldDescriptor[]; // repeating_rows only
  min_rows?: number;              // repeating_rows only
  max_rows?: number;              // repeating_rows only
  add_label?: string;             // repeating_rows only — defaults to "Add row"
}

interface Props {
  schema: FieldDescriptor[];
  config: Record<string, unknown>;
  onChange: (config: Record<string, unknown>) => void;
}

const widthToCol = (w?: string) =>
  w === "full" ? 12 : w === "third" ? 4 : 6;

export default function SchemaConfigForm({ schema, config, onChange }: Props) {
  return (
    <Row className="g-3">
      {schema.map((f) => {
        const current = config[f.name] ?? f.default ?? "";
        const setValue = (v: unknown) => onChange({ ...config, [f.name]: v });
        return (
          <Col key={f.name} md={widthToCol(f.width)}>
            <Form.Group>
              <Form.Label>
                {f.label}
                {f.label_suffix && (
                  <span className="text-muted fw-normal"> {f.label_suffix}</span>
                )}
              </Form.Label>
              {renderInput(f, current, setValue)}
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
  setValue: (v: unknown) => void,
) {
  const monoStyle = f.mono ? { fontFamily: "monospace", fontSize: "0.9em" } : undefined;

  switch (f.type) {
    case "string":
      return (
        <Form.Control
          type="text"
          placeholder={f.placeholder}
          value={(current as string) || ""}
          onChange={(e) => setValue(e.target.value)}
        />
      );

    case "multiline":
      return (
        <Form.Control
          as="textarea"
          rows={f.rows ?? 4}
          placeholder={f.placeholder}
          value={(current as string) || ""}
          onChange={(e) => setValue(e.target.value)}
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
          onChange={(e) => setValue(Number(e.target.value))}
        />
      );

    case "date":
      return (
        <Form.Control
          type="date"
          value={(current as string) || ""}
          onChange={(e) => setValue(e.target.value)}
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
            setValue(v ? v.split(",").map((t) => t.trim()).filter(Boolean) : []);
          }}
        />
      );
    }

    case "select":
      return (
        <Form.Select
          value={(current as string) || ""}
          onChange={(e) => setValue(e.target.value)}
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
                  setValue([...selected, opt]);
                } else {
                  setValue(selected.filter((x) => x !== opt));
                }
              }}
            />
          ))}
        </>
      );
    }

    case "file_picker":
      return <FilePickerInput field={f} value={current} onChange={setValue} />;

    case "repeating_rows":
      return <RepeatingRows field={f} value={current} onChange={setValue} />;

    default:
      return (
        <Form.Control
          type="text"
          value={String(current ?? "")}
          onChange={(e) => setValue(e.target.value)}
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

type RowDict = Record<string, unknown>;

interface FileListResponse {
  root_path: string;
  subpath: string;
  entries: { name: string; kind: "file" | "dir"; size: number | null; modified: string }[];
}

function RepeatingRows({
  field,
  value,
  onChange,
}: {
  field: FieldDescriptor;
  value: unknown;
  onChange: (v: RowDict[]) => void;
}) {
  const rowSchema = field.row_schema ?? [];
  const minRows = field.min_rows ?? 0;
  const maxRows = field.max_rows ?? Infinity;

  const rows: RowDict[] = Array.isArray(value)
    ? (value as RowDict[])
    : Array.from({ length: Math.max(minRows, 0) }, () => ({}));

  // The folder-import convenience button appears only when the row_schema
  // contains exactly one file_picker sub-field; with zero or multiple, the
  // bulk-add target would be ambiguous.
  const filePickerSubFields = rowSchema.filter((s) => s.type === "file_picker");
  const filePickerSub = filePickerSubFields.length === 1 ? filePickerSubFields[0] : null;
  const [showFolderPicker, setShowFolderPicker] = useState(false);
  const [importError, setImportError] = useState<string | null>(null);
  const [importing, setImporting] = useState(false);

  const updateRow = (idx: number, key: string, v: unknown) => {
    const next = rows.map((r, i) => (i === idx ? { ...r, [key]: v } : r));
    onChange(next);
  };

  const addRow = () => {
    if (rows.length >= maxRows) return;
    onChange([...rows, {}]);
  };

  const deleteRow = (idx: number) => {
    if (rows.length <= minRows) return;
    onChange(rows.filter((_, i) => i !== idx));
  };

  const importFolder = async (selection: FilePickerSelection) => {
    if (!filePickerSub) return;
    setImporting(true);
    setImportError(null);
    try {
      const params = new URLSearchParams();
      if (selection.path) params.set("subpath", selection.path);
      if (filePickerSub.filter_extensions && filePickerSub.filter_extensions.length > 0) {
        params.set("filter_extensions", filePickerSub.filter_extensions.join(","));
      }
      const qs = params.toString();
      const res = await axiosClient.get<FileListResponse>(
        `/files/list${qs ? `?${qs}` : ""}`,
      );
      const files = res.data.entries.filter((e) => e.kind === "file");
      const slotsLeft = Math.max(0, maxRows - rows.length);
      const toAdd = files.slice(0, slotsLeft);
      if (toAdd.length === 0) {
        setImportError(
          files.length === 0
            ? "Folder is empty (no matching files)."
            : `Row cap reached (max ${maxRows}).`,
        );
        return;
      }
      const newRows: RowDict[] = toAdd.map((f) => ({
        [filePickerSub.name]: {
          path: selection.path ? `${selection.path}/${f.name}` : f.name,
          name: f.name,
        } as FilePickerSelection,
      }));
      onChange([...rows, ...newRows]);
      if (files.length > toAdd.length) {
        setImportError(
          `Added ${toAdd.length} of ${files.length} files (cap ${maxRows}). Delete rows and re-import to pick a different subset.`,
        );
      }
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } }; message?: string };
      setImportError(err?.response?.data?.detail || err?.message || "Folder import failed");
    } finally {
      setImporting(false);
      setShowFolderPicker(false);
    }
  };

  const canAdd = rows.length < maxRows;
  const canDelete = rows.length > minRows;

  return (
    <div>
      {rows.length === 0 && (
        <div className="text-muted small mb-2">No rows yet — use the button below to add one.</div>
      )}
      {rows.map((row, idx) => (
        <Card key={idx} className="mb-2">
          <Card.Body className="py-2">
            <Row className="g-2 align-items-end">
              {rowSchema.map((sub) => {
                const subCurrent = row[sub.name] ?? sub.default ?? "";
                const subSet = (v: unknown) => updateRow(idx, sub.name, v);
                return (
                  <Col key={sub.name} md={widthToCol(sub.width)}>
                    <Form.Group>
                      <Form.Label className="small mb-1">
                        {sub.label}
                        {sub.label_suffix && (
                          <span className="text-muted fw-normal"> {sub.label_suffix}</span>
                        )}
                      </Form.Label>
                      {renderInput(sub, subCurrent, subSet)}
                      {sub.help && (
                        <Form.Text className="text-muted small">{sub.help}</Form.Text>
                      )}
                    </Form.Group>
                  </Col>
                );
              })}
              <Col xs="auto">
                <Button
                  size="sm"
                  variant="outline-danger"
                  onClick={() => deleteRow(idx)}
                  disabled={!canDelete}
                  title={canDelete ? "Remove this row" : `At least ${minRows} required`}
                >
                  Remove
                </Button>
              </Col>
            </Row>
          </Card.Body>
        </Card>
      ))}
      <div className="d-flex gap-2 flex-wrap">
        <Button
          size="sm"
          variant="outline-primary"
          onClick={addRow}
          disabled={!canAdd}
          title={canAdd ? "" : `Maximum ${maxRows} rows`}
        >
          + {field.add_label ?? "Add row"}
        </Button>
        {filePickerSub && (
          <Button
            size="sm"
            variant="outline-secondary"
            onClick={() => {
              setImportError(null);
              setShowFolderPicker(true);
            }}
            disabled={!canAdd || importing}
            title={
              canAdd
                ? "Pick a folder; adds one row per file inside"
                : `Maximum ${maxRows} rows`
            }
          >
            {importing ? "Importing…" : "Import folder"}
          </Button>
        )}
        {rows.length > 0 && (
          <span className="text-muted small align-self-center">
            {rows.length} {rows.length === 1 ? "row" : "rows"}
            {Number.isFinite(maxRows) ? ` (max ${maxRows})` : ""}
          </span>
        )}
      </div>
      {importError && (
        <div className="text-danger small mt-2">{importError}</div>
      )}
      {filePickerSub && (
        <FilePicker
          show={showFolderPicker}
          mode="folder"
          filterExtensions={filePickerSub.filter_extensions}
          onSelect={importFolder}
          onCancel={() => setShowFolderPicker(false)}
        />
      )}
    </div>
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
