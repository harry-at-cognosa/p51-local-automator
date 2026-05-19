import { useEffect, useState } from "react";
import {
  Navbar,
  Nav,
  NavDropdown,
  Container,
  OverlayTrigger,
  Tooltip,
} from "react-bootstrap";
import { LinkContainer } from "react-router-bootstrap";
import { useAuthStore } from "../stores/useAuthStore";
import { useSettingsStore } from "../stores/useSettingsStore";
import { API_URL } from "../api/apiURL";

interface VersionInfo {
  app_version: string;
  db_revision: string | null;
  expected_db_revision: string | null;
  git_sha: string;
  started_at: string;
}

export default function TopNavBar() {
  const auth = useAuthStore();
  const { app_title, instance_label } = useSettingsStore();
  const [version, setVersion] = useState<VersionInfo | null>(null);

  useEffect(() => {
    // Public endpoint — surfaces the running code's view of the version.
    // Distinct from the manually-maintained sw_version / db_version pill
    // on the Dashboard header, which serves a different operational role.
    fetch(`${API_URL}/system/version`)
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => {
        if (data) setVersion(data as VersionInfo);
      })
      .catch(() => {
        // Endpoint may not exist on older backends; hide the pill silently.
      });
  }, []);

  const aligned =
    !!version &&
    !!version.db_revision &&
    !!version.expected_db_revision &&
    version.db_revision === version.expected_db_revision;

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
                {/* Plain <span className="badge"> — same reason as the
                    version pill below: react-bootstrap's <Badge> defaults
                    bg="primary" and Bootstrap's .bg-primary !important
                    would override the theme-color background. */}
                <span
                  className="badge ms-2"
                  style={{
                    fontSize: "0.65em",
                    backgroundColor: "var(--theme-color-600)",
                    color: "#ffffff",
                  }}
                >
                  {instance_label}
                </span>
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
            {version && (
              <OverlayTrigger
                placement="bottom"
                overlay={
                  <Tooltip id="version-pill-tooltip">
                    <div style={{ textAlign: "left", fontSize: "0.85em" }}>
                      <div>app: {version.app_version}</div>
                      <div>
                        db: {version.db_revision ?? "?"}
                        {!aligned && (
                          <>
                            {" "}
                            <span style={{ color: "#fca5a5" }}>
                              (expected {version.expected_db_revision ?? "?"})
                            </span>
                          </>
                        )}
                      </div>
                      <div>git: {version.git_sha}</div>
                      <div>started: {new Date(version.started_at).toLocaleString()}</div>
                      {!aligned && (
                        <div style={{ marginTop: 4, color: "#fca5a5" }}>
                          Run `alembic upgrade head` and restart uvicorn.
                        </div>
                      )}
                    </div>
                  </Tooltip>
                }
              >
                <span
                  className="d-flex align-items-center ms-2"
                  style={{ cursor: "default" }}
                >
                  {/* Plain styled span instead of <Badge>: react-bootstrap's
                      Badge defaults bg="primary", which applies .bg-primary
                      with !important and would override the inline
                      backgroundColor. Using just .badge gives us the pill
                      shape without the variant background. */}
                  <span
                    className="badge"
                    style={{
                      fontSize: "0.7em",
                      backgroundColor: aligned
                        ? "var(--theme-color-200)"
                        : "#b91c1c",
                      color: aligned
                        ? "var(--theme-color-900)"
                        : "#ffffff",
                    }}
                  >
                    v{version.app_version}
                    {!aligned && " (stale)"}
                  </span>
                </span>
              </OverlayTrigger>
            )}
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
