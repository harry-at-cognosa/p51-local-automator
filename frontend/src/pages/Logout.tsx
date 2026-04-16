import { useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { useAuthStore } from "../stores/useAuthStore";

export default function Logout() {
  const navigate = useNavigate();
  const { clearLoggedUser } = useAuthStore();

  useEffect(() => {
    localStorage.removeItem("token");
    clearLoggedUser();
    navigate("/login");
  }, [navigate, clearLoggedUser]);

  return null;
}
