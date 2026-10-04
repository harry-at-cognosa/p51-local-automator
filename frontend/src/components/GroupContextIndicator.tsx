import { Alert } from "react-bootstrap";
import { useAuthStore } from "../stores/useAuthStore";
import {
  ALL_GROUPS,
  GROUP_CONTEXT_SELECT_ID,
  useGroupContextStore,
} from "../stores/useGroupContextStore";

/**
 * Shows which group the page below is being viewed as.
 *
 * The control itself lives once in the top bar, because the context governs
 * every request, not just the three pages that list things — putting a
 * selector on each would imply it only applied there. But that leaves the
 * state far from the table it explains: rows go non-clickable and a Group
 * column appears or vanishes because of a control at the other end of the
 * screen. This is the state, where you are looking, with a link up to the
 * control rather than a second copy of it.
 *
 * Renders nothing for non-superusers, who only ever have one context.
 */
export default function GroupContextIndicator() {
  const isSuperuser = useAuthStore((s) => s.is_superuser);
  const selected = useGroupContextStore((s) => s.selected);
  const groupName = useGroupContextStore((s) => s.groupName);

  if (!isSuperuser) return null;

  const viewingAll = selected === ALL_GROUPS;

  const focusSelector = () => {
    const el = document.getElementById(GROUP_CONTEXT_SELECT_ID);
    if (!el) return;
    el.scrollIntoView({ behavior: "smooth", block: "center" });
    el.focus();
  };

  return (
    <Alert
      variant={viewingAll ? "secondary" : "light"}
      className="py-2 px-3 mb-3 d-flex align-items-center justify-content-between"
    >
      <div className="small">
        {viewingAll ? (
          <>
            <strong>Viewing all groups.</strong> Every group's rows are listed
            here, but nothing can be opened, run or changed — pick a group
            first.
          </>
        ) : (
          <>
            Acting as a member of <strong>{groupName(selected as number)}</strong>
            . You see and change exactly what a member of that group does.
          </>
        )}
      </div>
      <button
        type="button"
        className="btn btn-link btn-sm p-0 ms-3 text-nowrap"
        onClick={focusSelector}
      >
        Change group
      </button>
    </Alert>
  );
}
