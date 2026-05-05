import { createBrowserRouter, Navigate } from "react-router-dom";
import App from "./App";
import Login from "./pages/Login";
import Logout from "./pages/Logout";
import Dashboard from "./pages/Dashboard";
import Workflows from "./pages/Workflows";
import WorkflowDetail from "./pages/WorkflowDetail";
import RunDetail from "./pages/RunDetail";
import PendingReplies from "./pages/PendingReplies";
import ManageUsers from "./pages/ManageUsers";
import ManageGroups from "./pages/ManageGroups";
import ManageWorkflowCategories from "./pages/ManageWorkflowCategories";
import ManageWorkflowTypes from "./pages/ManageWorkflowTypes";
import Settings from "./pages/Settings";
import GroupSettings from "./pages/GroupSettings";

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
        path: "workflows/:id",
        element: <WorkflowDetail />,
      },
      {
        path: "workflows/:id/pending-replies",
        element: <PendingReplies />,
      },
      {
        path: "runs/:runId",
        element: <RunDetail />,
      },
      {
        path: "admin/users",
        element: <ManageUsers />,
      },
      {
        path: "admin/groups",
        element: <ManageGroups />,
      },
      {
        path: "admin/workflow-categories",
        element: <ManageWorkflowCategories />,
      },
      {
        path: "admin/workflow-types",
        element: <ManageWorkflowTypes />,
      },
      {
        path: "admin/settings",
        element: <Settings />,
      },
      {
        path: "admin/group-settings",
        element: <GroupSettings />,
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
