# p51-local-automator — Mac Mini deployment modes

_Date: 2026-05-25_

For deploying p51-local-automator on a Mac Mini, the platform supports two modes:

## i) Single-user mode

The Mac Mini serves one human, and the Apple Mail client can be used for anything a consumer Gmail or Google Workspace account can be used. In effect, just like running on the user's desktop, but the Mac Mini can be always-on and configured to wake up and do work as needed (for example, morning workflows that run before the user gets up and logs into their desktop).

## ii) Team mode

The Mac Mini serves multiple humans. Each user has their own Gmail account (Workspace or consumer) under which they own their individual workflows and settings, as well as any group-scoped resources they're entitled to. When advanced workflows that rely on the Google Workspace CLI ship, those workflows will require Workspace accounts specifically; consumer Gmail won't satisfy them. The Apple Mail client on the shared Mac Mini can be configured for any kind of email account Apple Mail supports — but those accounts are shared across all p51 users on the box, so they should only be used for genuinely shared inboxes (e.g. `acme_accounts_payable@icloud.com` or `customer_inquiry@acme-corp.com`), never for any individual's personal mail.
