import { useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { setOnUnauthenticated } from "./axiosClient";

export default function NavigationInjector() {
  const navigate = useNavigate();

  useEffect(() => {
    setOnUnauthenticated(() => {
      localStorage.removeItem("token");
      navigate("/login");
    });
  }, [navigate]);

  return null;
}
