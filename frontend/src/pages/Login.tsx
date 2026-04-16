import { useState, useEffect, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { Container, Card, Form, Button, Alert } from "react-bootstrap";
import { API_URL } from "../api/apiURL";
import { useSettingsStore } from "../stores/useSettingsStore";

export default function Login() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();
  const { app_title, instance_label, loaded, fetchSettings } = useSettingsStore();

  useEffect(() => {
    if (!loaded) fetchSettings();
  }, [loaded, fetchSettings]);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError("");
    setLoading(true);

    try {
      const formData = new URLSearchParams();
      formData.append("username", username);
      formData.append("password", password);

      const res = await fetch(`${API_URL}/auth/jwt/login`, {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body: formData.toString(),
      });

      if (res.ok) {
        const data = await res.json();
        localStorage.setItem("token", data.access_token);
        navigate("/app");
      } else {
        setError("Invalid username or password");
      }
    } catch {
      setError("Connection error. Please try again.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-vh-100 d-flex align-items-center bg-light">
      <Container style={{ maxWidth: 420 }}>
        <Card className="shadow-sm">
          <Card.Body className="p-4">
            <h4 className="text-center mb-1">{app_title}</h4>
            {instance_label && (
              <p className="text-center">
                <span className="badge bg-secondary">{instance_label}</span>
              </p>
            )}
            {error && <Alert variant="danger" className="py-2">{error}</Alert>}
            <Form onSubmit={handleSubmit}>
              <Form.Group className="mb-3">
                <Form.Label>Username or Email</Form.Label>
                <Form.Control
                  type="text"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  required
                  autoFocus
                />
              </Form.Group>
              <Form.Group className="mb-3">
                <Form.Label>Password</Form.Label>
                <Form.Control
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  required
                />
              </Form.Group>
              <Button type="submit" className="w-100" disabled={loading}>
                {loading ? "Signing in..." : "Sign In"}
              </Button>
            </Form>
          </Card.Body>
        </Card>
      </Container>
    </div>
  );
}
