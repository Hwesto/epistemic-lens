# Privacy & data

Values data can infer **special-category data**. Consent, deletion, and
private-by-default are **legal necessities AND the trust feature the market asked
for** (§10). This is not optional polish.

## Principles

- **Private by default.** `users.privacy_settings = {"profile_public": false}`.
  The profile is the user's own; nothing is shared without explicit opt-in.
- **User-owned.** Friend-diff and any sharing are mutual, opt-in (`friendships`).
- **Consent at signup.** Explicit, logged consent before any profiling.
- **Deletion is real.** Account + data deletion must remove personal data.

## The deletion tension with append-only

`choice_events` is append-only and immutable — that is the measurement moat. But
users must be able to delete their data. Reconcile by **separating identity from
the event stream**:

- On deletion, **hard-delete the `users` row and any PII** (display name, auth
  mapping), and either delete or **irreversibly anonymise** that user's
  `choice_events` (e.g. detach `user_id` → a tombstone) per your retention policy
  and the consent you obtained.
- Append-only protects against *accidental/silent* mutation in normal operation;
  it is not a reason to retain a user's data against a valid deletion request.
- Document the chosen policy here before launch and reflect it in the consent copy.

> Design note: store the minimum identity needed to support friend-diff and login;
> keep the analytic value in the *de-identified* event stream wherever possible so
> deletion costs you as little signal as the law and ethics require.
