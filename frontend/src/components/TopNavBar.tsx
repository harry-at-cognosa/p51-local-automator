import { Navbar, Nav, NavDropdown, Badge, Container } from "react-bootstrap";
import { LinkContainer } from "react-router-bootstrap";
import { useAuthStore } from "../stores/useAuthStore";
import { useSettingsStore } from "../stores/useSettingsStore";

export default function TopNavBar() {
  const auth = useAuthStore();
  const { app_title, instance_label } = useSettingsStore();

  return (
    <Navbar expand="lg" className="px-3" variant="light"
      style={{ backgroundColor: "var(--theme-color-300, #cbd5e1)" }}
    >
      <style>{`
        .navbar .nav-link, .navbar .navbar-brand {
          color: var(--theme-color-900) !important;
        }
        .navbar .nav-link:hover {
          background-color: var(--theme-color-400) !important;
          border-radius: 4px;
        }
        .navbar .dropdown-toggle::after {
          color: var(--theme-color-800);
        }
      `}</style>
      <Container fluid>
        <LinkContainer to="/app">
          <Navbar.Brand className="fw-bold">
            {app_title}
            {instance_label && (
              <>
                {" "}
                <Badge
                  className="ms-2"
                  style={{ fontSize: "0.65em", backgroundColor: "var(--theme-color-600)" }}
                >
                  {instance_label}
                </Badge>
              </>
            )}
          </Navbar.Brand>
        </LinkContainer>

        <Navbar.Toggle aria-controls="main-navbar" />
        <Navbar.Collapse id="main-navbar">
          <Nav className="me-auto">
            <LinkContainer to="/app">
              <Nav.Link>Dashboard</Nav.Link>
            </LinkContainer>
            <LinkContainer to="/app/workflows">
              <Nav.Link>Workflows</Nav.Link>
            </LinkContainer>
          </Nav>

          <Nav>
            <NavDropdown
              title={auth.user_name || "User"}
              id="user-dropdown"
              align="end"
            >
              <NavDropdown.ItemText className="text-muted" style={{ fontSize: "0.85em" }}>
                {auth.email}
                <br />
                Group: {auth.group_name}
              </NavDropdown.ItemText>
              <NavDropdown.Divider />
              <LinkContainer to="/app/logout">
                <NavDropdown.Item>Logout</NavDropdown.Item>
              </LinkContainer>
            </NavDropdown>
          </Nav>
        </Navbar.Collapse>
      </Container>
    </Navbar>
  );
}
