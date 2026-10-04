import { useEffect } from "react";
import { Outlet, useNavigate } from "react-router-dom";
import TopNavBar from "./components/TopNavBar";
import SideMenu from "./components/SideMenu";
import NavigationInjector from "./api/NavigationInjector";
import { useAuthStore } from "./stores/useAuthStore";
import { useSettingsStore } from "./stores/useSettingsStore";
import { useGroupContextStore } from "./stores/useGroupContextStore";
import { API_URL } from "./api/apiURL";

export default function App() {
  const { setLoggedUser, isLogged } = useAuthStore();
  const navigate = useNavigate();
  const { loaded, fetchSettings } = useSettingsStore();
  const groupContext = useGroupContextStore((s) => s.selected);

  useEffect(() => {
    if (!loaded) fetchSettings();
  }, [loaded, fetchSettings]);

  useEffect(() => {
    const token = localStorage.getItem("token");
    if (!token) {
      navigate("/login");
      return;
    }

    async function fetchUser() {
      const res = await fetch(`${API_URL}/users/me`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (res.ok) {
        const user = await res.json();
        setLoggedUser(user);
      } else {
        localStorage.removeItem("token");
        navigate("/login");
      }
    }

    fetchUser();
  }, [navigate, setLoggedUser]);

  if (!isLogged) return null;

  return (
    <div className="min-vh-100">
      <NavigationInjector />
      <TopNavBar />
      <div className="d-flex">
        <SideMenu />
        {/* Keyed on the acting group: switching remounts the routed page so
            it refetches under the new context, rather than continuing to
            show rows fetched for the previous group. */}
        <main className="flex-grow-1" key={String(groupContext)}>
          <Outlet />
        </main>
      </div>
    </div>
  );
}
