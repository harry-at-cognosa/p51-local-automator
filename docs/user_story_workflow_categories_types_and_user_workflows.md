# User story for workflow categories, workflow types, and user workflows

**Captured:** 2026-05-05

## The model from the user's perspective

The system ships with a fixed set of **workflow categories** and a fixed set of **workflow types** within each category. Users do not create categories or types; they only create instances.

When a user wants to automate something, they pick a workflow type from the catalog and **clone** it — the system creates a `user_workflows` row pre-populated from the type's `default_config`. The user then:

1. Edits the configuration to fit their specific purpose (e.g., choose mailbox, topics, scope, schedule).
2. Gives the workflow a **unique-to-them** name that reflects what this instance is for, not what type it is.

That instance is then theirs to keep. They run it ad-hoc, schedule it, and over time may **tune** the configuration to improve results or adapt to environmental changes. The workflow's purpose — and therefore its name — does not normally change once set.

## Multiple instances of the same type

If a user wants the same kind of automation for several distinct purposes (e.g., several different "Email Topic Monitor" jobs), they create **separate user workflows**, each with its own name and config. They do not reconfigure a single workflow back and forth.

## Lifecycle: tuning and retirement

- **Tuning**: in-place edits to the user workflow's configuration. Frequent and expected.
- **Retirement**: when an instance becomes obsolete, the user **disables** it (existing `enabled` boolean). Soft-delete is also supported but disable is the everyday action.

## Configuration history

The application does not need to formally track configuration changes for end-user use cases. However, **logging configuration edits** somewhere accessible to admins (e.g., for support / audit / "what changed?" debugging) would be a nice-to-have. This is not currently implemented.

## Future: UI-driven configuration

Today, configuration is hand-edited JSON in a textarea (or a hardcoded per-typeId form). Going forward, **many or all workflow types will be configured through purpose-built web pages**, with a JSON-aware control that makes structured edits easy without exposing raw JSON syntax to most users. The exact UX is open, but the direction is "configurable through end-user web pages, not raw JSON."

## Implications for design discussions

- Workflow types and categories remain **read-only** to end users; they are platform fixtures.
- Adding a new workflow type is a platform-team activity (new backend service module, new seed/migration row, new frontend form branch — eventually replaced by schema-driven forms).
- The user-given name on a `user_workflows` row is the **identity** of that instance from the user's perspective — naming hints in the UI should encourage this.
- Run-history audit needs to remain meaningful even as users tune config over time. (Snapshotting the config used by each run, or versioning the workflow's config, has been flagged as an open design question — see the earlier conversation about runs not preserving the config they ran with.)
