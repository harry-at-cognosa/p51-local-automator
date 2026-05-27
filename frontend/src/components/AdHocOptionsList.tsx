/**
 * AdHocOptionsList — full-width list of ad-hoc workflow options surfaced on
 * the Dashboard below the Standard Workflow Types grid.
 *
 * Hardcoded for now: each entry needs backend support, so adding a new
 * option means adding code anyway. If the list grows past a handful or
 * we want admins to edit the prose without a deploy, this can move to
 * a DB table.
 */
import { Card, ListGroup } from "react-bootstrap";
import { LinkContainer } from "react-router-bootstrap";

interface AdHocOption {
  key: string;
  title: string;
  description: string;
  route: string;
}

const ADHOC_OPTIONS: AdHocOption[] = [
  {
    key: "email-topic-monitor",
    title: "Ad-hoc Email Topic Monitor",
    description:
      "A single re-configurable instance of the Email Topic Monitor workflow. " +
      "Switch between email account types, scope qualifications, topic choices, " +
      "and timeframes to find the configuration that works best — then create a " +
      "standard Type 1 workflow with those settings once you're satisfied.",
    route: "/app/ad-hoc/email-topic-monitor",
  },
];

export default function AdHocOptionsList() {
  return (
    <Card>
      <Card.Body>
        <p className="mb-2">
          Ad-hoc Workflow Options let you run one-time experimental workflows
          to try out different configurations.
        </p>
        <details className="mb-3">
          <summary className="text-muted" style={{ cursor: "pointer" }}>
            Show more
          </summary>
          <p className="mt-2 mb-0 text-muted">
            There's only one instance of each ad-hoc option in the system, so
            anything you intend to use regularly is better created as a
            standard Workflow Type 1–7, where the configuration can be saved
            and rerun without re-editing. The ad-hoc menu is the right place
            to iterate — try different parameter combinations until you've
            settled on the configuration you want, then promote it to a saved
            standard workflow. Ad-hoc workflows are for interactive iteration
            and cannot be scheduled.
          </p>
        </details>

        <ListGroup>
          {ADHOC_OPTIONS.map((opt) => (
            <LinkContainer to={opt.route} key={opt.key}>
              <ListGroup.Item action style={{ cursor: "pointer" }}>
                <div className="fw-semibold">{opt.title}</div>
                <div className="text-muted small">{opt.description}</div>
              </ListGroup.Item>
            </LinkContainer>
          ))}
        </ListGroup>
      </Card.Body>
    </Card>
  );
}
