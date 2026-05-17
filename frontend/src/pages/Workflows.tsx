import { useEffect, useMemo, useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { Container, Table, Button, Modal, Form, Alert, OverlayTrigger, Popover } from "react-bootstrap";
import axiosClient from "../api/axiosClient";
import WorkflowConfigForm from "../components/WorkflowConfigForm";
import StatusBadge from "../components/StatusBadge";
import TableVCRPager from "../components/TableVCRPager";
import EditScheduleModal from "../components/EditScheduleModal";
import { useWorkflowsStore } from "../stores/workflowsStore";

interface ScheduleEntry {
  workflow_id: number;
  next_fires_utc: string[];
  enabled: boolean;
}

function formatFireShort(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    weekday: "short",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

const STATUS_OPTIONS = ["completed", "running", "failed", "pending"];
const STATUS_NONE = "__none__";

export default function Workflows() {
  const navigate = useNavigate();
  const {
    items,
    categories,
    types,
    filters,
    sortBy,
    page,
    pageSize,
    selectedIds,
    loading,
    error,
    fetchAll,
    setFilter,
    setSortBy,
    setPage,
    setPageSize,
    toggleSelected,
    selectMany,
    clearSelection,
    bulkDelete,
  } = useWorkflowsStore();

  const [showCreate, setShowCreate] = useState(false);
  const [selectedTypeId, setSelectedTypeId] = useState<number>(0);
  const [newName, setNewName] = useState("");
  const [newConfig, setNewConfig] = useState<Record<string, unknown>>({});

  const [scheduledOnly, setScheduledOnly] = useState(false);
  const [scheduleMap, setScheduleMap] = useState<Record<number, ScheduleEntry>>({});

  // Schedule modal target — set when the bulk-action Schedule button is
  // clicked with exactly one row selected. The modal is the same
  // EditScheduleModal used by WorkflowDetail and the Schedules-page picker.
  const [scheduleTarget, setScheduleTarget] = useState<{
    workflow_id: number;
    name: string;
    schedule: Record<string, unknown> | null;
  } | null>(null);

  useEffect(() => { fetchAll(); }, [fetchAll]);

  useEffect(() => {
    axiosClient
      .get<ScheduleEntry[]>("/schedules")
      .then((res) => {
        const m: Record<number, ScheduleEntry> = {};
        for (const s of res.data) m[s.workflow_id] = s;
        setScheduleMap(m);
      })
      .catch(() => { /* schedules are optional info — fail silent */ });
  }, [items]);

  // Filtered dataset (client-side)
  const filtered = useMemo(() => {
    const nameQ = filters.name.trim().toLowerCase();
    return items.filter((w) => {
      if (filters.category && w.type.category.category_key !== filters.category) return false;
      if (filters.type && String(w.type_id) !== filters.type) return false;
      if (filters.status) {
        if (filters.status === STATUS_NONE) {
          if (w.latest_run_status) return false;
        } else if (w.latest_run_status !== filters.status) {
          return false;
        }
      }
      if (nameQ && !w.name.toLowerCase().includes(nameQ)) return false;
      if (scheduledOnly && !scheduleMap[w.workflow_id]) return false;
      return true;
    });
  }, [items, filters, scheduledOnly, scheduleMap]);

  // Sorted (after filter, before pagination). All sorts are descending.
  // last_run_at puts NULL (never run) rows at the bottom.
  const sorted = useMemo(() => {
    const arr = [...filtered];
    arr.sort((a, b) => {
      if (sortBy === "workflow_id") return b.workflow_id - a.workflow_id;
      if (sortBy === "created_at") return b.created_at.localeCompare(a.created_at);
      if (sortBy === "last_run_at") {
        if (!a.last_run_at && !b.last_run_at) return 0;
        if (!a.last_run_at) return 1;
        if (!b.last_run_at) return -1;
        return b.last_run_at.localeCompare(a.last_run_at);
      }
      return 0;
    });
    return arr;
  }, [filtered, sortBy]);

  const totalRows = sorted.length;
  const pageStart = (page - 1) * pageSize;
  const pageItems = useMemo(
    () => sorted.slice(pageStart, pageStart + pageSize),
    [sorted, pageStart, pageSize]
  );

  // Clamp page if filter reduced it below current
  useEffect(() => {
    const maxPage = Math.max(1, Math.ceil(totalRows / pageSize));
    if (page > maxPage) setPage(maxPage);
  }, [totalRows, pageSize, page, setPage]);

  // Types filtered by chosen category (dropdown sub-filter)
  const typesForFilter = useMemo(() => {
    if (!filters.category) return types;
    return types.filter((t) => t.category.category_key === filters.category);
  }, [types, filters.category]);

  const handleSelectAllOnPage = () => {
    selectMany(pageItems.map((w) => w.workflow_id));
  };

  const handleBulkDelete = async () => {
    const ids = Array.from(selectedIds);
    if (ids.length === 0) return;
    const ok = window.confirm(
      `Delete ${ids.length} selected workflow${ids.length === 1 ? "" : "s"}? This is a soft delete — rows are hidden but can be recovered from the database.`
    );
    if (!ok) return;
    await bulkDelete(ids);
  };

  const handleSchedule = () => {
    if (selectedIds.size !== 1) return;
    const id = Array.from(selectedIds)[0];
    const wf = items.find((w) => w.workflow_id === id);
    if (!wf) return;
    setScheduleTarget({
      workflow_id: wf.workflow_id,
      name: wf.name,
      schedule: wf.schedule,
    });
  };

  const handleCreate = async (e: FormEvent) => {
    e.preventDefault();
    const wfType = types.find((t) => t.type_id === selectedTypeId);
    if (!wfType) return;
    await axiosClient.post("/workflows", {
      type_id: selectedTypeId,
      name: newName || wfType.long_name,
      config: newConfig,
    });
    setShowCreate(false);
    setNewName("");
    setSelectedTypeId(0);
    setNewConfig({});
    await fetchAll();
  };

  return (
    <Container fluid className="p-4">
      <div className="d-flex justify-content-between align-items-center mb-4">
        <h3 className="mb-0">My Workflows</h3>
        <Button variant="primary" onClick={() => setShowCreate(true)}>
          + New Workflow
        </Button>
      </div>

      {error && <Alert variant="danger">{error}</Alert>}

      {loading && items.length === 0 ? (
        <p className="text-muted">Loading…</p>
      ) : items.length === 0 ? (
        <p className="text-muted">No workflows configured yet. Click "+ New Workflow" to get started.</p>
      ) : (
        <>
          <div className="d-flex align-items-center gap-3 py-2">
            <div className="d-flex align-items-center gap-2">
              <span className="text-muted small">Sort by:</span>
              <Form.Select
                size="sm"
                style={{ width: "auto" }}
                value={sortBy}
                onChange={(e) => setSortBy(e.target.value as "workflow_id" | "last_run_at" | "created_at")}
                aria-label="Sort workflows"
              >
                <option value="workflow_id">ID (newest first)</option>
                <option value="last_run_at">Last run (newest first)</option>
                <option value="created_at">Created (newest first)</option>
              </Form.Select>
            </div>
            <Form.Check
              type="switch"
              id="scheduled-only"
              label="Show scheduled only"
              checked={scheduledOnly}
              onChange={(e) => setScheduledOnly(e.target.checked)}
              className="small text-muted"
            />
          </div>

          <TableVCRPager
            page={page}
            totalRows={totalRows}
            pageSize={pageSize}
            onPage={setPage}
            onPageSizeCommit={setPageSize}
            selectedCount={selectedIds.size}
            onSelectAllOnPage={handleSelectAllOnPage}
            onBulkDelete={handleBulkDelete}
            onSchedule={handleSchedule}
          />

          <Table striped bordered hover size="sm" className="mt-2">
            <thead>
              <tr>
                <th style={{ width: 36 }}></th>
                <th style={{ width: 56 }}>ID</th>
                <th>Category</th>
                <th>Type</th>
                <th>Name <span className="text-muted fw-normal small">(click to review)</span></th>
                <th>Status</th>
                <th>Last Run</th>
                <th>Next Fire</th>
              </tr>
              <tr className="table-light">
                <th></th>
                <th></th>
                <th>
                  <Form.Select
                    size="sm"
                    value={filters.category}
                    onChange={(e) => {
                      setFilter("category", e.target.value);
                      // Reset type filter if it no longer belongs to the chosen category
                      if (e.target.value && filters.type) {
                        const stillValid = types.some(
                          (t) => String(t.type_id) === filters.type && t.category.category_key === e.target.value
                        );
                        if (!stillValid) setFilter("type", "");
                      }
                    }}
                  >
                    <option value="">(any)</option>
                    {categories.map((c) => (
                      <option key={c.category_id} value={c.category_key} title={c.long_name}>
                        {c.short_name}
                      </option>
                    ))}
                  </Form.Select>
                </th>
                <th>
                  <Form.Select
                    size="sm"
                    value={filters.type}
                    onChange={(e) => setFilter("type", e.target.value)}
                  >
                    <option value="">(any)</option>
                    {typesForFilter.map((t) => (
                      <option key={t.type_id} value={String(t.type_id)} title={t.long_name}>
                        {t.short_name}
                      </option>
                    ))}
                  </Form.Select>
                </th>
                <th>
                  <Form.Control
                    size="sm"
                    type="text"
                    placeholder="filter name…"
                    value={filters.name}
                    onChange={(e) => setFilter("name", e.target.value)}
                  />
                </th>
                <th>
                  <Form.Select
                    size="sm"
                    value={filters.status}
                    onChange={(e) => setFilter("status", e.target.value)}
                  >
                    <option value="">(any)</option>
                    <option value={STATUS_NONE}>(never run)</option>
                    {STATUS_OPTIONS.map((s) => (
                      <option key={s} value={s}>{s}</option>
                    ))}
                  </Form.Select>
                </th>
                <th></th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {pageItems.map((w) => {
                const checked = selectedIds.has(w.workflow_id);
                return (
                  <tr key={w.workflow_id}>
                    <td className="text-center">
                      <Form.Check
                        type="checkbox"
                        aria-label={`Select ${w.name}`}
                        checked={checked}
                        onChange={() => toggleSelected(w.workflow_id)}
                      />
                    </td>
                    <td className="text-muted small font-monospace">#{w.workflow_id}</td>
                    <td title={w.type.category.long_name}>{w.type.category.short_name}</td>
                    <td title={`${w.type.long_name}${w.type.type_desc ? " — " + w.type.type_desc : ""}`}>
                      {w.type.short_name}
                    </td>
                    <td
                      className="fw-semibold"
                      style={{ cursor: "pointer" }}
                      onClick={() => navigate(`/app/workflows/${w.workflow_id}`)}
                    >
                      {w.name}
                    </td>
                    <td>
                      <StatusBadge status={w.latest_run_status} />
                      {w.latest_run_status === "completed" && w.latest_run_artifact_count === 0 && (
                        <span
                          className="ms-1"
                          title="Latest run produced no output"
                          style={{ cursor: "help" }}
                        >
                          ⚠️
                        </span>
                      )}
                    </td>
                    <td>{w.latest_run_at ? new Date(w.latest_run_at).toLocaleString() : "Never"}</td>
                    <td className="small">
                      {(() => {
                        const sch = scheduleMap[w.workflow_id];
                        if (!sch || sch.next_fires_utc.length === 0) {
                          return <span className="text-muted">—</span>;
                        }
                        const popover = (
                          <Popover id={`next-fires-${w.workflow_id}`}>
                            <Popover.Header as="h6" className="small">
                              Next {sch.next_fires_utc.length} fire{sch.next_fires_utc.length === 1 ? "" : "s"}
                              {!sch.enabled && " (paused)"}
                            </Popover.Header>
                            <Popover.Body className="small p-2">
                              <ol className="mb-0 ps-3">
                                {sch.next_fires_utc.map((iso, i) => (
                                  <li key={i}>{formatFireShort(iso)}</li>
                                ))}
                              </ol>
                            </Popover.Body>
                          </Popover>
                        );
                        return (
                          <OverlayTrigger trigger={["hover", "focus"]} placement="left" overlay={popover}>
                            <span
                              style={{ cursor: "help", textDecoration: sch.enabled ? undefined : "line-through" }}
                            >
                              {formatFireShort(sch.next_fires_utc[0])}
                              {sch.next_fires_utc.length > 1 && (
                                <span className="text-muted ms-1">+{sch.next_fires_utc.length - 1}</span>
                              )}
                            </span>
                          </OverlayTrigger>
                        );
                      })()}
                    </td>
                  </tr>
                );
              })}
              {pageItems.length === 0 && (
                <tr>
                  <td colSpan={8} className="text-center text-muted py-3">
                    No workflows match the current filters.{" "}
                    <Button variant="link" size="sm" onClick={() => { clearSelection(); useWorkflowsStore.getState().resetFilters(); }}>
                      Clear filters
                    </Button>
                  </td>
                </tr>
              )}
            </tbody>
          </Table>
        </>
      )}

      <Modal show={showCreate} onHide={() => setShowCreate(false)} size="lg">
        <Modal.Header closeButton>
          <Modal.Title>Create Workflow</Modal.Title>
        </Modal.Header>
        <Form onSubmit={handleCreate}>
          <Modal.Body>
            <Form.Group className="mb-3">
              <Form.Label>Workflow Type</Form.Label>
              <Form.Select
                value={selectedTypeId}
                onChange={(e) => {
                  const id = Number(e.target.value);
                  setSelectedTypeId(id);
                  const wfType = types.find((t) => t.type_id === id);
                  setNewConfig(wfType ? { ...wfType.default_config } : {});
                }}
                required
              >
                <option value={0}>Select a type...</option>
                {/* Group by category. The backend returns types pre-sorted
                    by (category.sort_order, type.sort_order, type.type_id),
                    so a linear pass produces correct optgroup boundaries. */}
                {(() => {
                  const groups: { categoryId: number; label: string; types: typeof types }[] = [];
                  for (const t of types) {
                    const last = groups[groups.length - 1];
                    if (!last || last.categoryId !== t.category.category_id) {
                      groups.push({
                        categoryId: t.category.category_id,
                        label: `${t.category.category_id}-${t.category.short_name}`,
                        types: [t],
                      });
                    } else {
                      last.types.push(t);
                    }
                  }
                  return groups.map((g) => (
                    <optgroup key={g.categoryId} label={g.label}>
                      {g.types.map((t) => (
                        <option key={t.type_id} value={t.type_id}>
                          {t.type_id}-{t.long_name}
                        </option>
                      ))}
                    </optgroup>
                  ));
                })()}
              </Form.Select>
            </Form.Group>
            <Form.Group className="mb-3">
              <Form.Label>Name</Form.Label>
              <Form.Control
                type="text"
                placeholder="Give it a name..."
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
              />
              <Form.Text className="text-muted">
                Leave blank to use the type name as default. If you are making more than one,
                consider adding a configuration-related hint to identify which one this is.
              </Form.Text>
            </Form.Group>
            {selectedTypeId > 0 && (
              <>
                <hr />
                <h6 className="mb-3">Configuration</h6>
                <WorkflowConfigForm
                  typeId={selectedTypeId}
                  config={newConfig}
                  onChange={setNewConfig}
                  configSchema={
                    (types.find((t) => t.type_id === selectedTypeId)?.config_schema as
                      | import("../components/SchemaConfigForm").FieldDescriptor[]
                      | undefined) ?? null
                  }
                />
              </>
            )}
          </Modal.Body>
          <Modal.Footer>
            <Button variant="secondary" onClick={() => setShowCreate(false)}>Cancel</Button>
            <Button variant="primary" type="submit" disabled={!selectedTypeId}>Create</Button>
          </Modal.Footer>
        </Form>
      </Modal>

      {scheduleTarget && (
        <EditScheduleModal
          show={true}
          workflowId={scheduleTarget.workflow_id}
          workflowName={scheduleTarget.name}
          currentSchedule={scheduleTarget.schedule}
          onHide={() => setScheduleTarget(null)}
          onSaved={() => { setScheduleTarget(null); fetchAll(); }}
        />
      )}
    </Container>
  );
}
