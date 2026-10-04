# TODOs

Lightweight running list of small improvements and open issues not yet worth their own doc or commit. Promote into the relevant deployment doc / open a real issue once they grow up.

## UX

- **Gmail-IMAP setup form: password-storage-method radio is not coupled to the app-password input.**
  The form lets you pick "encrypted DB column" while the app-password text field above still accepts a paste, and the form happily saves the password to the radio's storage backend — even if every other Google account for that user is on `plaintext_file`. The mismatch only surfaces later as quiet config drift (e.g. a workflow shows `app_password_enc` instead of `storage_method: plaintext_file` in its config, and may silently fail to authenticate against the backend the user expected).
  Suggested fixes:
    - At save, warn if the chosen storage method differs from any existing entry already on file for that email address (look up `gmail_password_store` / `gmail_accounts`).
    - Or, default the radio to whatever storage backend that email is already registered under, rather than the form's hardcoded default.
  Observed: 2026-05-26 on M4 setup of `harry.layman@gmail.com` Gmail IMAP workflow.

## Open bugs

_(none currently)_

## Resolved

- ~~**All ETM-classified emails come back as "OTHER" on the M4 machine.**~~ — **closed 2026-10-04, has not reproduced.**
  Original report (2026-05-26): same workflow shape (`topics: []`, `scope: ""`, default categories) classified into
  proper default categories on the M1 desktop, but on M4 both wf 144 (run 110) and a freshly-recreated wf 146 returned
  *only* "OTHER" for every retrieved email.
  Evidence for closing — two clean passes, the second on unattended scheduled runs:
    - 2026-09-19, manual: wf 141 run 290, 17 emails, five distinct topics.
    - 2026-10-04, scheduled: wf 141 run 361 (n=4), wf 142 run 362 (n=3), and **wf 144 run 363 (n=90) — the workflow
      that originally failed** — spread across six topics (Marketing & Promotions 30, Other 27, Business & Finance 16,
      Technology & AI 9, Government & Institutional 5, Personal & Social 3), 7 flagged urgent.
  Suspected cause: commits `949566b` + `c3c10c3` (2026-06-17) refreshed stale Claude model IDs to the current family
  and externalized them to the settings chain. This entry was written 2026-06-04, *before* those landed — consistent
  with the classifier having been calling a dead model ID and falling back to a single bucket.
  If it recurs, check `default_fast_model` at `/app/admin/settings` first; the model IDs are now operator-editable
  rather than hardcoded. The M1-vs-M4 comparison was never re-run, so the original machine-to-machine delta remains
  formally unexplained.
