# Superuser group switching

How p51 lets a superuser act as a member of another group, what follows that
choice, what deliberately does not, and the behaviours that will surprise you
six months from now.

Shipped 2026-10-04. Code: `backend/api/group_context.py`,
`frontend/src/stores/useGroupContextStore.ts`,
`frontend/src/components/GroupContextSelector.tsx`.

---

## The model

A superuser is always in exactly one of two states, chosen from the **Acting
as** selector in the top navigation bar:

| State | Lists show | Can open / run / modify | `user.group_id` used for writes |
|---|---|---|---|
| **All groups** (default) | every group's rows | nothing at all | n/a — refused |
| **Group N** | group N only | group N only | N |

Picking a concrete group makes the superuser a member of that group for the
duration of each request. Not a privileged superset — the *same* scope a real
member of that group gets. There is a test asserting the superuser's scope
clause is identical to a groupadmin's of the same group.

Everyone who is not a superuser has no selector, and the server pins them to
their own group regardless of what any client sends.

## The invariant

> A superuser can never create or modify data in a group other than the one
> they are currently acting as.

This holds **by construction**, not by a guard that could be forgotten. Reads
and writes both derive their group from the same request-scoped context, so
there is no state in which "the group I can see" and "the group I would write
to" differ. All-groups mode — the only state with no single group — refuses to
produce a group id at all, so nothing that writes can run in it.

The one zone outside this rule is user and group administration; see
*Deliberate exceptions* below.

## How the context travels

A header on every API request:

```
X-Group-Context: 2        # act as group 2
X-Group-Context: all      # view-only across all groups
```

Attached by the axios interceptor (`frontend/src/api/axiosClient.ts`) from the
persisted store, so no page has to remember to send it.

**Artifact downloads are the exception.** A download link is a plain browser
navigation and cannot set headers — which is also why that route already
authenticates from a `?token=` query param rather than a header. The context
rides along the same way:

```
/api/v1/artifacts/{id}/download?token=...&group_context=2
```

Both forms are parsed by the same `resolve_group_context()`, so they cannot
drift. **If you ever build an artifact download URL somewhere new, it must
include `group_context` or it will 409.**

## Why the context is not stored on the user

Two reasons, both load-bearing:

1. **It must not be server-side session state.** An "assumed group" held on the
   server is a hidden mode that leaks across browser tabs — the same session
   would be group 1 in one tab and group 2 in another, with no way to tell
   which produced a given result.

2. **It must never touch the user row.** The obvious cheap implementation is to
   override `User.group_id` in memory for the request, which would need zero
   changes at any call site. That is a **destructive bug**: `async_get_user_db`
   hands out a `User` attached to the *request's* session, and
   `backend/api/users.py` calls `session.flush()` + `commit()` on the Profile
   route. The overridden group would have been written to the user row
   permanently, silently relocating the superuser to another group.

So the context is carried *beside* the user, never on it. No ORM state is
mutated anywhere in this feature.

---

## Quirks you will forget

**1. All-groups mode is uniformly view-only — including your own group.**
Acting as "All groups", `GET /workflows/141` returns 409 even though 141 is in
your own home group. The mode has no group at all, not "your group plus
read-only visibility into others". Verified: `/workflows/141`,
`/workflows/141/runs`, `/runs/361` and `/files/list` all 409 in that mode.

**2. 409 and 404 mean different things.** Easy to conflate when debugging:

- **409** — "you are in all-groups mode; pick a group." Nothing is wrong with
  the row.
- **404** — "that row is not in the group you are currently acting as." The row
  exists; you are standing in the wrong place.

**3. Switching groups discards unsaved form state.** The routed page is keyed
on the selection in `App.tsx`, so changing groups remounts it. That is what
makes every page refetch under the new context instead of showing the previous
group's rows — but a half-filled workflow config form will be wiped. By design,
worth knowing before you blame the form.

**4. You get a separate ad-hoc row per group.** Ad-hoc workflows are keyed on
`(user_id, group_id, type_id, is_adhoc)`. Switching groups gives you a
*different* ad-hoc Email Topic Monitor with its own saved config — your group-1
settings will appear to have vanished. They have not; they belong to the
group-1 row.

Current rows: **wf 143** (group 1, created 2026-05-23) and **wf 150** (group 2,
created 2026-10-04 during verification).

To see them, turn on **Include ad-hoc** on the Workflows page — a
superuser-only switch beside "Show scheduled only", which sends
`?include_adhoc=true`. Ad-hoc rows then appear in the normal list with an
"ad-hoc" badge next to the id. The switch is deliberately *not* persisted:
it is a triage mode, and one that silently stayed on would quietly change
what the list means. The Ad-hoc Runs page also shows the workflow id now.

Before 2026-10-04 there was no way to see an ad-hoc workflow's id in the UI
at all — the backend supported `include_adhoc` but nothing ever sent it.

`group_id` is part of the *lookup key*, not merely the stamp, and that is the
whole point. Before this, acting as group 2 would have found your group-1
ad-hoc row and run it — and since runners derive output paths from
`workflow.group_id`, the artifacts would have landed under **group 1's**
filesystem root. A cross-group write by the back door, with every explicit
permission check still passing.

**5. Group Settings follows the selector too** *(since 2026-10-04)*. It used
to be the exception: `_resolve_group_id()` in `backend/api/group_settings.py`
ignored the context, and the page carried its *own* group picker. A superuser
could therefore be looking at group 2's workflows while editing group 1's
settings — two pickers for one concept, disagreeing silently.

`_resolve_group_id` now defaults to the acting group, and the page's rival
picker is gone. Measured: acting as group 1 → group 1's settings; acting as
group 2 → group 2's; all-groups → 409, nothing to administer. An explicit
`?group_id=N` still overrides and is still refused for a non-superuser
reaching outside their own group, since it predates the context and may have
other callers.

**Consequence worth knowing:** editing another group's settings now means
*switching into that group*, which also changes what you see on Workflows,
Dashboard and Schedules. You can no longer administer group 2's settings
while standing in group 1.

**6. The health banner uses your home group in all-groups mode.** A deliberate
exception (`group_or_home()`): the Dashboard loads
`/system/health` unconditionally, and an error banner there in view-only mode
would be wrong. So the filesystem-root check reports on *your* group when no
group is selected. Never use `group_or_home` anywhere a write could follow.

**7. Your user row never changes.** Switching is request-scoped. `api_users`
still says the superuser is in group 1, and the Profile page shows the real
group, not the acting one.

**8. The selection is persisted per browser.** localStorage key
`group-context`. It survives reloads and outlives a logout. Clearing site data
returns you to all-groups. If a superuser reports "I can't open anything," the
first question is which group the selector is on.

**9. Dashboard numbers move when you switch.** Stats are scoped to the acting
group: 20 workflows / 314 runs across all groups, 19 / 313 in group 1, 1 / 1 in
group 2. Not a bug.

**10. Background runs ignore all of this.** The scheduler and
`_run_workflow_background` derive everything from `workflow.group_id` and never
see a viewer. A scheduled run always writes to its own workflow's group, no
matter what any browser has selected. The context is purely a request-scoped
concept for interactive use.

## Deliberate exceptions

**User and group administration is not confined by the acting group.**
`manage_users.py` and `manage_groups.py` branch on `user.is_superuser`, never
on `user.group_id`, so a superuser can list users across all groups and create
a user in any group by passing `payload.group_id` — regardless of which group
they are acting as.

This is required, not an oversight: a brand-new group has no members, so if
creating its first user demanded switching into it, the group could never be
bootstrapped through the UI. Chicken and egg.

It does mean the invariant above is scoped to *workflow* data — workflows,
runs, artifacts, files, settings. Account administration is a separate axis.

## Authority model

`is_superuser` is the **single** authority axis. No code treats any
`group_id` as privileged, and none should start.

Group 1 being named "System" is a deployment convention carried in data, not
in code. Gating all-groups mode on membership of that group was considered and
rejected: it would create a second source of truth for one permission, make
group 1 the first magic group id in the codebase, and add no security —
`manage_users.py` already restricts minting a superuser to superusers, so the
gate would only guard a superuser's own mistake. It would also wrongly break a
single-tenant install where the superuser legitimately lives in the only group
that exists. The policy "only system-group users get superuser" belongs in
deployment process.

## Testing

Hermetic unit tests: `backend/tests/test_group_context.py` (34 tests). Covers
context resolution, per-role scoping, the no-cross-group-write guarantee, the
read-only fallback, and immutability of the context object.

### Verified manually, 2026-10-04

As superuser `admin@localhost`:

- **All groups** — selector present in the top bar; indicator banner renders on
  Workflows, Dashboard and Schedules stating nothing can be opened, run or
  changed; Group column present; rows not clickable; Create disabled.
- **Acting as a group** — indicator names the group and states you see and
  change what a member of it does; Group column gone; rows clickable.

As `cogmgr` (groupadmin, group 2, not a superuser): neither the selector nor
the indicator renders anywhere.

### Non-superuser confinement

Two halves, verified separately:

- **The UI half** — confirmed manually above: no selector and no indicator
  render for `cogmgr`.
- **The server half** — covered by unit tests, parametrized across 3 roles ×
  5 header values including a non-superuser explicitly requesting another
  group. This is the half that matters: the absence of a control proves only
  that the UI does not offer one, whereas the server ignores
  `X-Group-Context` outright for non-superusers, so a hand-crafted request
  cannot escape the caller's own group either.

Measured end-to-end as superuser `admin@localhost` (home group 1):

| Endpoint | all-groups | group 1 | group 2 |
|---|---|---|---|
| `GET /workflows` | 20 rows, groups `[1,2]` | 19, `[1]` | 1, `[2]` |
| `GET /workflows/135` (in group 2) | 409 | 404 | 200 |
| `GET /workflows/141` (in group 1) | 409 | 200 | 404 |
| `GET /dashboard/stats` | 20 wf / 314 runs | 19 / 313 | 1 / 1 |
| `GET /files/list` | 409 | 200 | 200 |
| `GET /ad-hoc/email-topic-monitor` | 409 | 200 | 200 |
| artifact download | 409 | 200 | 404 |

## What this fixed

The long-standing inconsistency where a superuser saw a cross-group workflow
listed but got a 404 opening it (`_get_active_workflow` hard-rejected
`workflow.group_id != user.group_id` for every role). The check was duplicated
at seven sites in `workflows.py` and `artifacts.py`; four more endpoints
reached it indirectly through `_get_pending_reply` and never appeared in a
naive grep. All twenty now resolve through the same context.
