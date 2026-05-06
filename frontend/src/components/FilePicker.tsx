/**
 * Modal file/folder picker scoped to the authenticated user's inputs sandbox.
 *
 * Calls GET /api/v1/files/list to navigate the directory tree under
 * <file_system_root>/{group_id}/{user_id}/inputs/. The path is computed
 * server-side from the authenticated user; the client only controls the
 * relative subpath and an optional extension filter.
 *
 * mode="file"   — only files are selectable; clicking a file calls onSelect
 * mode="folder" — only folders are selectable; "Use this folder" button confirms
 *
 * The selection's `path` field is relative to the user's inputs root (NOT
 * the absolute server path). Consumers store the relative path in workflow
 * config; the engine joins it with the resolved root at run time.
 */
import { useEffect, useState } from "react";
import { Modal, Button, ListGroup, Spinner, Alert, Breadcrumb } from "react-bootstrap";
import axiosClient from "../api/axiosClient";

export interface FilePickerSelection {
  path: string;   // relative to user's inputs root
  name: string;   // basename (filename or folder name)
}

interface FileEntry {
  name: string;
  kind: "file" | "dir";
  size: number | null;
  modified: string;
}

interface FileListResponse {
  root_path: string;
  subpath: string;
  entries: FileEntry[];
}

interface Props {
  show: boolean;
  mode: "file" | "folder";
  filterExtensions?: string[];
  initialSubpath?: string;
  onSelect: (selection: FilePickerSelection) => void;
  onCancel: () => void;
}

const formatSize = (bytes: number | null): string => {
  if (bytes == null) return "";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
};

const joinPath = (a: string, b: string): string => {
  if (!a) return b;
  if (!b) return a;
  return `${a.replace(/\/+$/, "")}/${b.replace(/^\/+/, "")}`;
};

const parentOf = (subpath: string): string => {
  if (!subpath) return "";
  const trimmed = subpath.replace(/\/+$/, "");
  const idx = trimmed.lastIndexOf("/");
  return idx < 0 ? "" : trimmed.slice(0, idx);
};

const breadcrumbSegments = (subpath: string): { name: string; path: string }[] => {
  if (!subpath) return [];
  const out: { name: string; path: string }[] = [];
  const parts = subpath.split("/").filter(Boolean);
  let acc = "";
  for (const p of parts) {
    acc = acc ? `${acc}/${p}` : p;
    out.push({ name: p, path: acc });
  }
  return out;
};

export default function FilePicker({
  show,
  mode,
  filterExtensions,
  initialSubpath,
  onSelect,
  onCancel,
}: Props) {
  const [subpath, setSubpath] = useState<string>(initialSubpath ?? "");
  const [data, setData] = useState<FileListResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!show) return;
    setLoading(true);
    setError(null);
    const params = new URLSearchParams();
    if (subpath) params.set("subpath", subpath);
    if (filterExtensions && filterExtensions.length > 0) {
      params.set("filter_extensions", filterExtensions.join(","));
    }
    const qs = params.toString();
    axiosClient
      .get<FileListResponse>(`/files/list${qs ? `?${qs}` : ""}`)
      .then((res) => setData(res.data))
      .catch((e) => {
        const detail = e?.response?.data?.detail || e?.message || "Failed to list files";
        setError(String(detail));
      })
      .finally(() => setLoading(false));
  }, [show, subpath, filterExtensions ? filterExtensions.join(",") : ""]);

  // Reset to initialSubpath each time the modal opens fresh.
  useEffect(() => {
    if (show) setSubpath(initialSubpath ?? "");
  }, [show]);

  const navigate = (newSubpath: string) => setSubpath(newSubpath);

  const handleEntryClick = (entry: FileEntry) => {
    const fullPath = joinPath(subpath, entry.name);
    if (entry.kind === "dir") {
      navigate(fullPath);
      return;
    }
    if (mode === "file") {
      onSelect({ path: fullPath, name: entry.name });
    }
  };

  const handleConfirmFolder = () => {
    const name = subpath ? subpath.split("/").filter(Boolean).slice(-1)[0] : "(root)";
    onSelect({ path: subpath, name });
  };

  return (
    <Modal show={show} onHide={onCancel} size="lg" centered>
      <Modal.Header closeButton>
        <Modal.Title>{mode === "file" ? "Pick a file" : "Pick a folder"}</Modal.Title>
      </Modal.Header>
      <Modal.Body>
        <Breadcrumb>
          <Breadcrumb.Item active={!subpath} onClick={() => navigate("")}>
            inputs/
          </Breadcrumb.Item>
          {breadcrumbSegments(subpath).map((seg, i, arr) => (
            <Breadcrumb.Item
              key={seg.path}
              active={i === arr.length - 1}
              onClick={() => navigate(seg.path)}
            >
              {seg.name}
            </Breadcrumb.Item>
          ))}
        </Breadcrumb>

        {subpath && (
          <Button
            size="sm"
            variant="outline-secondary"
            className="mb-2"
            onClick={() => navigate(parentOf(subpath))}
          >
            ← Up
          </Button>
        )}

        {loading && (
          <div className="text-center py-3">
            <Spinner animation="border" size="sm" /> Loading…
          </div>
        )}

        {error && <Alert variant="danger">{error}</Alert>}

        {!loading && !error && data && (
          <>
            {data.entries.length === 0 ? (
              <Alert variant="info" className="mb-0">
                No files yet. Place files via your SMB share at{" "}
                <code>{data.root_path}</code>
                {subpath ? <> / <code>{subpath}</code></> : null}.
              </Alert>
            ) : (
              <ListGroup variant="flush">
                {data.entries.map((entry) => {
                  const isFile = entry.kind === "file";
                  // dirs are always interactive (click to navigate);
                  // files are interactive only in file mode (click to select).
                  const selectable = isFile ? mode === "file" : true;
                  return (
                    <ListGroup.Item
                      key={entry.name}
                      action={selectable}
                      onClick={selectable ? () => handleEntryClick(entry) : undefined}
                      className="d-flex justify-content-between align-items-center"
                      style={selectable ? undefined : { opacity: 0.5, cursor: "default" }}
                    >
                      <span>
                        {isFile ? "📄 " : "📁 "}
                        {entry.name}
                      </span>
                      <small className="text-muted">
                        {isFile ? formatSize(entry.size) : ""}
                      </small>
                    </ListGroup.Item>
                  );
                })}
              </ListGroup>
            )}
          </>
        )}
      </Modal.Body>
      <Modal.Footer>
        <Button variant="secondary" onClick={onCancel}>
          Cancel
        </Button>
        {mode === "folder" && (
          <Button variant="primary" onClick={handleConfirmFolder} disabled={loading}>
            Use this folder
          </Button>
        )}
      </Modal.Footer>
    </Modal>
  );
}
