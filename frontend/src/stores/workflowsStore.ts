import { create } from "zustand";
import { persist } from "zustand/middleware";
import axiosClient from "../api/axiosClient";

export interface WorkflowCategory {
  category_id: number;
  category_key: string;
  short_name: string;
  long_name: string;
  sort_order: number;
  enabled: boolean;
}

export interface WorkflowType {
  type_id: number;
  type_name: string;
  type_desc: string;
  short_name: string;
  long_name: string;
  category: WorkflowCategory;
  default_config: Record<string, unknown>;
  enabled: boolean;
}

export interface UserWorkflowListRow {
  workflow_id: number;
  user_id: number;
  group_id: number;
  type_id: number;
  name: string;
  schedule: Record<string, unknown> | null;
  enabled: boolean;
  last_run_at: string | null;
  created_at: string;
  type: WorkflowType;
  latest_run_status: string | null;
  latest_run_at: string | null;
  latest_run_artifact_count: number | null;
}

export interface Filters {
  category: string; // category_key or ""
  type: string;     // type_id as string or ""
  name: string;     // substring match, case-insensitive
  status: string;   // "completed" | "running" | "failed" | "pending" | ""
}

interface WorkflowsState {
  items: UserWorkflowListRow[];
  categories: WorkflowCategory[];
  types: WorkflowType[];
  filters: Filters;
  page: number;
  pageSize: number;
  selectedIds: Set<number>;
  loading: boolean;
  error: string | null;

  fetchAll: () => Promise<void>;
  setFilter: <K extends keyof Filters>(key: K, value: Filters[K]) => void;
  resetFilters: () => void;
  setPage: (n: number) => void;
  setPageSize: (n: number) => void;
  toggleSelected: (id: number) => void;
  selectMany: (ids: number[]) => void;
  clearSelection: () => void;
  bulkDelete: (ids: number[]) => Promise<number>;
}

interface Persisted {
  pageSize: number;
}

const DEFAULT_FILTERS: Filters = { category: "", type: "", name: "", status: "" };

export const useWorkflowsStore = create<WorkflowsState>()(
  persist(
    (set, get) => ({
      items: [],
      categories: [],
      types: [],
      filters: { ...DEFAULT_FILTERS },
      page: 1,
      pageSize: 25,
      selectedIds: new Set<number>(),
      loading: false,
      error: null,

      fetchAll: async () => {
        set({ loading: true, error: null });
        try {
          const [itemsRes, categoriesRes, typesRes] = await Promise.all([
            axiosClient.get("/workflows"),
            axiosClient.get("/workflow-categories"),
            axiosClient.get("/workflow-types"),
          ]);
          set({
            items: itemsRes.data,
            categories: categoriesRes.data,
            types: typesRes.data,
            loading: false,
          });
        } catch (err) {
          const msg = err instanceof Error ? err.message : "Failed to load workflows";
          set({ error: msg, loading: false });
        }
      },

      setFilter: (key, value) =>
        set((s) => ({ filters: { ...s.filters, [key]: value }, page: 1 })),

      resetFilters: () => set({ filters: { ...DEFAULT_FILTERS }, page: 1 }),

      setPage: (n) => set({ page: Math.max(1, n) }),

      setPageSize: (n) => set({ pageSize: Math.max(1, n), page: 1 }),

      toggleSelected: (id) =>
        set((s) => {
          const next = new Set(s.selectedIds);
          if (next.has(id)) next.delete(id);
          else next.add(id);
          return { selectedIds: next };
        }),

      selectMany: (ids) =>
        set((s) => {
          const next = new Set(s.selectedIds);
          ids.forEach((id) => next.add(id));
          return { selectedIds: next };
        }),

      clearSelection: () => set({ selectedIds: new Set<number>() }),

      bulkDelete: async (ids) => {
        const res = await axiosClient.post("/workflows/bulk-delete", { workflow_ids: ids });
        const count: number = res.data?.deleted_count ?? 0;
        await get().fetchAll();
        set({ selectedIds: new Set<number>() });
        return count;
      },
    }),
    {
      name: "wf-list-page-size",
      partialize: (state): Persisted => ({ pageSize: state.pageSize }),
    }
  )
);
