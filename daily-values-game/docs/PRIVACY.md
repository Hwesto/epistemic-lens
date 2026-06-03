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

## The deletion tension with append-only — implemented: **anonymise & retain**

`choice_events` is append-only and immutable — that is the measurement moat. But
users must be able to delete their data. We reconcile this by **scrubbing
identity rather than touching the event log** (`apps/api/api/account/delete.ts`):

1. **Delete the Supabase auth user** — removes login and the PII Supabase holds
   (email, name). This is the only place real PII lived.
2. **Scrub the `users` row** — null `auth_id` and `display_name`, clear
   `privacy_settings`, set `is_anonymized = true`. This severs every link between
   the person and their events.
3. **Delete derived/relational rows** — `profiles`, `consents`, `friendships`.
4. **Leave `choice_events` untouched** — they now reference an anonymous,
   PII-free subject, so the behavioural signal is retained for the science while
   nothing identifies the person.

Why this shape:

- The append-only trigger is **never touched** — normal-operation immutability
  holds, and there is no privileged "anonymise" bypass to misuse.
- **Within-user linkage is preserved** (the events keep a single, now-anonymous
  `user_id`), so a deleted user remains one coherent anonymous respondent rather
  than being scattered — better for analysis, still non-identifying.
- We store the **minimum identity** in our DB (just the auth subject); the real
  PII lives in Supabase Auth and is deleted there. Deletion therefore costs as
  little signal as the law and ethics require.

Users can also **export** their data (`account/export.ts`, GDPR access) and
toggle profile visibility (`account/privacy.ts`); profiles stay **private by
default**. Consent is captured before any profiling (`consent.ts`,
`CONSENT_VERSION`) and the choice endpoint refuses to record without it.
