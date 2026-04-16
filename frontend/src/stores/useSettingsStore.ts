import { create } from "zustand";
import { API_URL } from "../api/apiURL";
import getColor from "../api/getColor";

interface SettingsState {
  app_title: string;
  navbar_color: string;
  instance_label: string;
  loaded: boolean;
  fetchSettings: () => Promise<void>;
}

function applyThemeColors(colorName: string) {
  const root = document.documentElement;
  const shades = [50, 100, 200, 300, 400, 500, 600, 700, 800, 900];
  shades.forEach((shade) => {
    root.style.setProperty(`--theme-color-${shade}`, getColor(colorName, shade));
  });
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
        const color = data.navbar_color || "slate";
        applyThemeColors(color);
        set({
          app_title: data.app_title || "Local Automator",
          navbar_color: color,
          instance_label: data.instance_label || "",
          loaded: true,
        });
      }
    } catch {
      applyThemeColors("slate");
      set({ loaded: true });
    }
  },
}));
