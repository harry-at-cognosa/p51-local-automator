/**
 * Available Workflow Types — card grid.
 *
 * Extracted from Workflows.tsx so the Dashboard can render it too.
 * Cards are clustered by category (the /workflow-types endpoint returns
 * rows already sorted by category.sort_order, type.sort_order, type.type_id).
 * Descriptions truncate to 4 lines with `…` so card heights are uniform.
 */
import { useEffect, useState } from "react";
import { Row, Col } from "react-bootstrap";
import axiosClient from "../api/axiosClient";

interface WorkflowCategory {
  category_id: number;
  short_name: string;
}

interface WorkflowType {
  type_id: number;
  long_name: string;
  type_desc: string;
  category: WorkflowCategory;
}

interface Props {
  /** Optional: caller passes the types it already has. If omitted, this
   * component fetches /workflow-types itself. */
  types?: WorkflowType[];
}

export default function WorkflowTypeCardsGrid({ types: typesProp }: Props) {
  const [types, setTypes] = useState<WorkflowType[]>(typesProp || []);
  const [loading, setLoading] = useState(!typesProp);

  useEffect(() => {
    if (typesProp) {
      setTypes(typesProp);
      return;
    }
    axiosClient
      .get<WorkflowType[]>("/workflow-types")
      .then((res) => setTypes(res.data))
      .finally(() => setLoading(false));
  }, [typesProp]);

  if (loading) return <div className="text-muted small">Loading workflow types…</div>;

  return (
    <Row className="g-3">
      {types.map((t) => (
        <Col md={6} lg={3} key={t.type_id} className="d-flex">
          <div className="border rounded p-3 h-100 d-flex flex-column flex-grow-1">
            <div className="mb-2 text-muted small text-uppercase">
              {t.category.category_id}-{t.category.short_name}
            </div>
            <h6>{t.type_id}-{t.long_name}</h6>
            <p
              className="text-muted small mb-0"
              style={{
                display: "-webkit-box",
                WebkitLineClamp: 4,
                WebkitBoxOrient: "vertical",
                overflow: "hidden",
                textOverflow: "ellipsis",
              }}
            >
              {t.type_desc}
            </p>
          </div>
        </Col>
      ))}
    </Row>
  );
}
