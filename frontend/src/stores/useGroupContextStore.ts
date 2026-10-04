import { create } from "zustand";
import { persist } from "zustand/middleware";

/**
 * Which group a superuser is currently acting as.
 *
 * ALL_GROUPS is a viewing mode: every group's rows appear in the lists, but
 * nothing can be opened, run or modified, because there is no single group
 * such an action would belong to. Picking a concrete group makes the
 * superuser a member of it for every request — same reads, same writes, same
 * filesystem root as an actual member of that group sees.
 *
 * The value rides on the X-Group-Context header, attached by the axios
 * interceptor. This store deliberately imports no API client: the
 * interceptor reads this store, so importing it back would be a cycle.
 * Callers that need the group list fetch it themselves and hand it here.
 *
 * Ignored entirely for non-superusers — the server pins them to their own
 * group regardless of what any client sends.
 */
export const ALL_GROUPS = "all" as const;

export type GroupSelection = number | typeof ALL_GROUPS;

export interface GroupOption {
  group_id: number;
  group_name: string;
}

interface GroupContextState {
  selected: GroupSelection;
  groups: GroupOption[];
  setSelected: (s: GroupSelection) => void;
  setGroups: (g: GroupOption[]) => void;
  groupName: (id: number) => string;
}

export const useGroupContextStore = create<GroupContextState>()(
  persist(
    (set, get) => ({
      // All-groups is the default because it is what a superuser saw before
      // this existed — the system-wide view stays the landing state.
      selected: ALL_GROUPS,
      groups: [],
      setSelected: (selected) => set({ selected }),
      setGroups: (groups) => set({ groups }),
      groupName: (id) =>
        get().groups.find((g) => g.group_id === id)?.group_name ?? `Group ${id}`,
    }),
    {
      name: "group-context",
      // The group list is server state and is refetched on load; only the
      // selection is worth remembering across reloads.
      partialize: (state) => ({ selected: state.selected }),
    }
  )
);

/** Header value for the current selection. Read by the axios interceptor. */
export const currentGroupContextHeader = (): string => {
  const { selected } = useGroupContextStore.getState();
  return selected === ALL_GROUPS ? ALL_GROUPS : String(selected);
};
