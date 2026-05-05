import { useEffect, useMemo, useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { Container, Table, Button, Modal, Form, Row, Col, Alert } from "react-bootstrap";
import axiosClient from "../api/axiosClient";
import WorkflowConfigForm from "../components/WorkflowConfigForm";
import StatusBadge from "../components/StatusBadge";
import TableVCRPager from "../components/TableVCRPager";
import { useWorkflowsStore } from "../stores/workflowsStore";

const STATUS_OPTIONS = ["completed", "running", "failed", "pending"];
const STATUS_NONE = "__none__";

export default function Workflows() {
  const navigate = useNavigate();
  const {
    items,
    categories,
    types,
    filters,
    page,
    pageSize,
    selectedIds,
    loading,
    error,
    fetchAll,
    setFilter,
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

  useEffect(() => { fetchAll(); }, [fetchAll]);

  // Filtered, sorted dataset (client-side)
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
      return true;
    });
  }, [items, filters]);

  const totalRows = filtered.length;
  const pageStart = (page - 1) * pageSize;
  const pageItems = useMemo(
    () => filtered.slice(pageStart, pageStart + pageSize),
    [filtered, pageStart, pageSize]
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
          <TableVCRPager
            page={page}
            totalRows={totalRows}
            pageSize={pageSize}
            onPage={setPage}
            onPageSizeCommit={setPageSize}
            selectedCount={selectedIds.size}
            onSelectAllOnPage={handleSelectAllOnPage}
            onBulkDelete={handleBulkDelete}
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
                  </tr>
                );
              })}
              {pageItems.length === 0 && (
                <tr>
                  <td colSpan={7} className="text-center text-muted py-3">
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

      <h4 className="mt-5 mb-3">Available Workflow Types</h4>
      <Row className="g-3">
        {types.map((t) => (
          <Col md={6} lg={3} key={t.type_id}>
            <div className="border rounded p-3 h-100">
              <div className="mb-2 text-muted small text-uppercase">{t.category.short_name}</div>
              <h6>{t.long_name}</h6>
              <p className="text-muted small mb-0">{t.type_desc}</p>
            </div>
          </Col>
        ))}
      </Row>

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
                {types.map((t) => (
                  <option key={t.type_id} value={t.type_id}>
                    {t.category.short_name} — {t.long_name}
                  </option>
                ))}
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
                <WorkflowConfigForm typeId={selectedTypeId} config={newConfig} onChange={setNewConfig} />
              </>
            )}
          </Modal.Body>
          <Modal.Footer>
            <Button variant="secondary" onClick={() => setShowCreate(false)}>Cancel</Button>
            <Button variant="primary" type="submit" disabled={!selectedTypeId}>Create</Button>
          </Modal.Footer>
        </Form>
      </Modal>
    </Container>
  );
}
