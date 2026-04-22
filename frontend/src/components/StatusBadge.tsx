import { Badge } from "react-bootstrap";

const COLORS: Record<string, string> = {
  completed: "success",
  running: "primary",
  failed: "danger",
  pending: "secondary",
};

interface Props {
  status: string | null | undefined;
  placeholder?: string;
}

export default function StatusBadge({ status, placeholder = "—" }: Props) {
  if (!status) return <span className="text-muted">{placeholder}</span>;
  return <Badge bg={COLORS[status] || "secondary"}>{status}</Badge>;
}
