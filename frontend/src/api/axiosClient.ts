import axios from "axios";
import { API_URL } from "./apiURL";
import { currentGroupContextHeader } from "../stores/useGroupContextStore";

const axiosClient = axios.create({
  baseURL: API_URL,
  headers: { "Content-Type": "application/json" },
});

let onUnauthenticated: (() => void) | null = null;

export const setOnUnauthenticated = (callback: () => void) => {
  onUnauthenticated = callback;
};

axiosClient.interceptors.request.use(
  (config) => {
    const token = localStorage.getItem("token");
    if (!token) {
      if (onUnauthenticated) onUnauthenticated();
      return Promise.reject(new Error("No token found"));
    }
    config.headers.set("Authorization", `Bearer ${token}`);
    // Which group the caller is acting as. Sent on every request so the
    // server never has to guess; ignored server-side for non-superusers,
    // so it is harmless to send unconditionally.
    config.headers.set("X-Group-Context", currentGroupContextHeader());
    return config;
  },
  (error) => Promise.reject(error)
);

axiosClient.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      if (onUnauthenticated) onUnauthenticated();
    }
    return Promise.reject(error);
  }
);

export default axiosClient;
