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

- **All ETM-classified emails come back as "OTHER" on the M4 machine.**
  Same workflow shape (`topics: []`, `scope: ""`, default categories) classifies into proper default categories on the M1 desktop. On M4, both wf 144 (run 110) and a freshly-recreated wf 146 return *only* "OTHER" for every retrieved email. Investigation pending; suspect an environmental difference between M4 and M1 (model / API key / `api_settings` defaults / silent LLM error). Observed: 2026-05-26.
