import { Nav } from "react-bootstrap";
import { LinkContainer } from "react-router-bootstrap";
import { useAuthStore } from "../stores/useAuthStore";

export default function SideMenu() {
  const auth = useAuthStore();

  return (
    <div
      className="bg-light border-end p-3"
      style={{ width: 220, minHeight: "calc(100vh - 56px)" }}
    >
      <Nav className="flex-column">
        <small className="text-muted text-uppercase fw-bold mb-2">Navigation</small>

        <LinkContainer to="/app">
          <Nav.Link>Dashboard</Nav.Link>
        </LinkContainer>
        <LinkContainer to="/app/workflows">
          <Nav.Link>Workflows</Nav.Link>
        </LinkContainer>

        {auth.is_superuser && (
          <>
            <hr className="my-2" />
            <small className="text-muted text-uppercase fw-bold mb-2">
              Administration
            </small>
            <LinkContainer to="/app/su/settings">
              <Nav.Link>Settings</Nav.Link>
            </LinkContainer>
          </>
        )}
      </Nav>
    </div>
  );
}
