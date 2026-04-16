import { createBrowserRouter, Navigate } from "react-router-dom";
import App from "./App";
import Login from "./pages/Login";
import Logout from "./pages/Logout";
import Dashboard from "./pages/Dashboard";
import Workflows from "./pages/Workflows";

export const Router = createBrowserRouter([
  {
    path: "app",
    element: <App />,
    children: [
      {
        index: true,
        element: <Dashboard />,
      },
      {
        path: "workflows",
        element: <Workflows />,
      },
      {
        path: "logout",
        element: <Logout />,
      },
    ],
  },
  {
    path: "login",
    element: <Login />,
  },
  {
    path: "*",
    element: <Navigate to="/login" replace />,
  },
]);
