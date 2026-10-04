import { useEffect } from "react";
import { Form } from "react-bootstrap";
import axiosClient from "../api/axiosClient";
import { useAuthStore } from "../stores/useAuthStore";
import {
  ALL_GROUPS,
  GROUP_CONTEXT_SELECT_ID,
  useGroupContextStore,
  type GroupOption,
} from "../stores/useGroupContextStore";

/**
 * Lets a superuser act as a member of any one group, or view across all of
 * them. Renders nothing for everyone else — a single group is the only
 * context they can have, so a selector would be a control with one option.
 *
 * Changing the selection remounts the routed page (see the key in App.tsx),
 * which is what makes every page refetch under the new group rather than
 * showing another group's rows until something happens to reload them.
 */
export default function GroupContextSelector() {
  const isSuperuser = useAuthStore((s) => s.is_superuser);
  const { selected, setSelected, groups, setGroups } = useGroupContextStore();

  useEffect(() => {
    if (!isSuperuser) return;
    axiosClient
      .get<GroupOption[]>("/manage/groups")
      .then((res) => setGroups(res.data))
      .catch(() => {
        // Non-fatal: the selector still works with the persisted selection,
        // it just shows ids instead of names.
      });
  }, [isSuperuser, setGroups]);

  if (!isSuperuser) return null;

  const viewingAll = selected === ALL_GROUPS;

  return (
    <div className="d-flex align-items-center gap-2 ms-3">
      <span className="small" style={{ color: "var(--theme-color-900)" }}>
        Acting as:
      </span>
      <Form.Select
        id={GROUP_CONTEXT_SELECT_ID}
        size="sm"
        style={{ width: "auto" }}
        value={String(selected)}
        aria-label="Group context"
        title={
          viewingAll
            ? "Viewing every group. Pick a group to open or run anything."
            : "You are acting as a member of this group."
        }
        onChange={(e) => {
          const v = e.target.value;
          setSelected(v === ALL_GROUPS ? ALL_GROUPS : Number(v));
        }}
      >
        <option value={ALL_GROUPS}>All groups (view only)</option>
        {groups.map((g) => (
          <option key={g.group_id} value={String(g.group_id)}>
            {g.group_name}
          </option>
        ))}
      </Form.Select>
    </div>
  );
}
