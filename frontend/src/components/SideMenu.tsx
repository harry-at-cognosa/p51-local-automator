import { Nav } from "react-bootstrap";
import { LinkContainer } from "react-router-bootstrap";
import { useAuthStore } from "../stores/useAuthStore";

export default function SideMenu() {
  const auth = useAuthStore();

  return (
    <div
      className="bg-light border-end p-3 d-flex flex-column"
      style={{ width: 220, minHeight: "calc(100vh - 56px)" }}
    >
      <Nav className="flex-column flex-grow-1">
        <small className="text-muted text-uppercase fw-bold mb-2">Navigation</small>

        <LinkContainer to="/app">
          <Nav.Link>Dashboard</Nav.Link>
        </LinkContainer>
        <LinkContainer to="/app/workflows">
          <Nav.Link>Workflows</Nav.Link>
        </LinkContainer>
        <LinkContainer to="/app/connections">
          <Nav.Link>Connections</Nav.Link>
        </LinkContainer>

        {(auth.is_groupadmin || auth.is_superuser) && (
          <>
            <hr className="my-2" />
            <small className="text-muted text-uppercase fw-bold mb-2">
              Administration
            </small>
            <LinkContainer to="/app/admin/users">
              <Nav.Link>Manage Users</Nav.Link>
            </LinkContainer>
            <LinkContainer to="/app/admin/group-settings">
              <Nav.Link>Group Settings</Nav.Link>
            </LinkContainer>
          </>
        )}

        {auth.is_superuser && (
          <>
            <LinkContainer to="/app/admin/groups">
              <Nav.Link>Manage Groups</Nav.Link>
            </LinkContainer>
            <LinkContainer to="/app/admin/workflow-categories">
              <Nav.Link>Workflow Categories</Nav.Link>
            </LinkContainer>
            <LinkContainer to="/app/admin/workflow-types">
              <Nav.Link>Workflow Types</Nav.Link>
            </LinkContainer>
            <LinkContainer to="/app/admin/settings">
              <Nav.Link>Global Settings</Nav.Link>
            </LinkContainer>
            <LinkContainer to="/app/admin/maintenance">
              <Nav.Link>Maintenance</Nav.Link>
            </LinkContainer>
          </>
        )}
      </Nav>
    </div>
  );
}
