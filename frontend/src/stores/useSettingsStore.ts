import { create } from "zustand";
import { API_URL } from "../api/apiURL";

interface SettingsState {
  app_title: string;
  navbar_color: string;
  instance_label: string;
  loaded: boolean;
  fetchSettings: () => Promise<void>;
}

export const useSettingsStore = create<SettingsState>((set) => ({
  app_title: "Local Automator",
  navbar_color: "slate",
  instance_label: "DEV",
  loaded: false,
  fetchSettings: async () => {
    try {
      const res = await fetch(`${API_URL}/settings/webapp_options`);
      if (res.ok) {
        const data = await res.json();
        set({
          app_title: data.app_title || "Local Automator",
          navbar_color: data.navbar_color || "slate",
          instance_label: data.instance_label || "",
          loaded: true,
        });
      }
    } catch {
      set({ loaded: true });
    }
  },
}));
