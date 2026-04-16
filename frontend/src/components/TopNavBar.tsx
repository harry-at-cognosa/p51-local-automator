import { Navbar, Nav, NavDropdown, Badge, Container } from "react-bootstrap";
import { LinkContainer } from "react-router-bootstrap";
import { useAuthStore } from "../stores/useAuthStore";
import { useSettingsStore } from "../stores/useSettingsStore";

export default function TopNavBar() {
  const auth = useAuthStore();
  const { app_title, instance_label } = useSettingsStore();

  return (
    <Navbar expand="lg" className="px-3" bg="dark" data-bs-theme="dark">
      <Container fluid>
        <LinkContainer to="/app">
          <Navbar.Brand className="fw-bold">
            {app_title}
            {instance_label && (
              <>
                {" "}
                <Badge bg="secondary" className="ms-2" style={{ fontSize: "0.65em" }}>
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
