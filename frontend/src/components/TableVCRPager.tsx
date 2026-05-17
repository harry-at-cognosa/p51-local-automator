import { useEffect, useState } from "react";
import { Button, Form, InputGroup } from "react-bootstrap";

interface Props {
  page: number;
  totalRows: number;
  pageSize: number;
  onPage: (page: number) => void;
  onPageSizeCommit: (size: number) => void;
  selectedCount: number;
  onSelectAllOnPage: () => void;
  onBulkDelete: () => void;
  // Optional Schedule action: enabled only when exactly one row is selected.
  // Renders to the right of "Select all on page" / "Delete Selected" when
  // onSchedule is provided; omitted entirely otherwise (other tables that
  // reuse this pager don't get a stray button).
  onSchedule?: () => void;
}

export default function TableVCRPager({
  page,
  totalRows,
  pageSize,
  onPage,
  onPageSizeCommit,
  selectedCount,
  onSelectAllOnPage,
  onBulkDelete,
  onSchedule,
}: Props) {
  const totalPages = Math.max(1, Math.ceil(totalRows / pageSize));
  const atFirst = page <= 1;
  const atLast = page >= totalPages;
  const needsPaging = totalRows > pageSize;

  const [sizeInput, setSizeInput] = useState(String(pageSize));
  useEffect(() => setSizeInput(String(pageSize)), [pageSize]);

  const commitSize = () => {
    const n = parseInt(sizeInput, 10);
    if (Number.isFinite(n) && n > 0 && n !== pageSize) onPageSizeCommit(n);
    else setSizeInput(String(pageSize));
  };

  const firstRow = totalRows === 0 ? 0 : (page - 1) * pageSize + 1;
  const lastRow = Math.min(page * pageSize, totalRows);

  return (
    <div className="d-flex align-items-center gap-3 flex-wrap py-2 border-bottom">
      <span className="text-muted small">Page scroll:</span>
      <div className="btn-group btn-group-sm" role="group" aria-label="VCR paging">
        <Button
          variant="outline-secondary"
          disabled={!needsPaging || atFirst}
          onClick={() => onPage(1)}
          title="First page"
        >
          {"|<<"}
        </Button>
        <Button
          variant="outline-secondary"
          disabled={!needsPaging || atFirst}
          onClick={() => onPage(page - 1)}
          title="Previous page"
        >
          {"<<"}
        </Button>
        <Button
          variant="outline-secondary"
          disabled={!needsPaging || atLast}
          onClick={() => onPage(page + 1)}
          title="Next page"
        >
          {">>"}
        </Button>
        <Button
          variant="outline-secondary"
          disabled={!needsPaging || atLast}
          onClick={() => onPage(totalPages)}
          title="Last page"
        >
          {">>|"}
        </Button>
      </div>

      <InputGroup size="sm" style={{ width: "auto" }}>
        <InputGroup.Text>Max rows</InputGroup.Text>
        <Form.Control
          type="number"
          min={1}
          value={sizeInput}
          style={{ width: 70 }}
          onChange={(e) => setSizeInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              commitSize();
            }
          }}
        />
        <Button variant="outline-secondary" onClick={commitSize} title="Apply">
          ✓
        </Button>
      </InputGroup>

      <span className="text-muted small">
        Rows shown: {firstRow === 0 ? "0" : `${firstRow}–${lastRow}`} (of {totalRows})
      </span>

      <div className="ms-auto d-flex gap-2">
        <Button
          size="sm"
          variant="outline-primary"
          disabled={totalRows === 0}
          onClick={onSelectAllOnPage}
        >
          Select all on page
        </Button>
        <Button
          size="sm"
          variant="danger"
          disabled={selectedCount === 0}
          onClick={onBulkDelete}
        >
          Delete selected{selectedCount > 0 ? ` (${selectedCount})` : ""}
        </Button>
        {onSchedule && (
          <Button
            size="sm"
            variant="outline-success"
            disabled={selectedCount !== 1}
            onClick={onSchedule}
            title={
              selectedCount === 0
                ? "Select a single workflow to schedule it."
                : selectedCount > 1
                ? "Schedule supports one workflow at a time. Select just one."
                : "Schedule this workflow"
            }
          >
            Schedule
          </Button>
        )}
      </div>
    </div>
  );
}
