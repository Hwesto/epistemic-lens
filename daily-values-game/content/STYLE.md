# MIRROR — Story Style Spec

*The rules that keep every story measuring the same thing. A story that breaks
these doesn't read worse — it reads someone else. Anything written for the corpus
passes the checklist at the bottom before it goes in.*

> Where this sits: the **measurement** vocabulary lives in `docs/MEASUREMENT.md`,
> the **experiment design** (edges, anchors, reps) in `content/coverage/`, and the
> **tagged JSON shape** in `content/stories/example-story.json`. This file governs
> the **prose** — the craft that makes a beat valence-neutral so it measures the
> player, not their reaction to the narrator.

---

## The prime directive

**The narrator has no favourite.**

Your job is to state the problem correctly, not to solve it — to be an impartial
witness, not a judge. The instant the prose signals which option is right, you
stop measuring the player and start measuring their reaction to *you*. Every rule
below is just this rule, made operational.

Test you can apply to any beat you write: **could a stranger tell which option you
would pick?** If yes, it's not finished.

---

## The locked form

These don't vary. They are the form, not a choice.

- **Second person, present tense.** "You" decide, now. It collapses the gap
  between reader and chooser — they're *deciding*, not *judging a character*.
- **The protagonist is a cipher.** No name, no face, no backstory, no fixed
  temperament. Give *you* a situation, never an identity. A characterised hero has
  their own values; the player would role-play that character instead of revealing
  themselves.
- **Five beats, four options each.** ~80% of beats are virtue-vs-virtue. ~20%
  carry one costed self-interest option (see *Writing the defection*).
- **A parable's body, a realist's interior.** The frame is spare, archetypal,
  fast — it has to travel intact to every player and land in a thumb-scroll. The
  temptation *inside* the frame is psychologically real. Folktale container, human
  pulse.

---

## The rules

**1. Choice-symmetry — the one that matters most.** Every option gets the same
sentence-weight, the same specificity, the same dignity, the same interiority. The
same care goes into the choice you'd hate as the one you'd make. If one option is
lovingly drawn and the others are terse, you've voted. Equal length, equal
texture, equal respect — across all four.

**2. Never name the value.** The prose may not say "the loyal thing," "the honest
path," "the brave move." The axes are hidden; the moment the text labels one, the
player optimises toward an image instead of choosing. Describe what is *done*,
never what it *means*.

**3. No verdict-words.** Cut every adjective that carries a built-in judgement —
*cowardly, noble, selfish, heroic, petty, principled*. Those are the narrator
picking. Report the act; let the act be the only evidence.

**4. No irony, no wink, no heroic pacing.** Irony is an instruction. Genre rhythm
(the slow-build, the swell before the "right" choice) pre-marks an option before
the player's values get a vote. When in doubt, go flatter — neutral surface over a
hard situation lands harder than any editorialising, and it doesn't tip the scale.

**5. Texture-specificity yes, identity-specificity no.** Concrete detail that
makes the moment *land* is the goal: a streetlight forty feet off, two seconds in
a doorway, the radiator nobody can switch off. Detail that localises the *player*
fractures the friend-diff — brand names, this-year's slang, an institution that
reads differently in different countries. Make the situation vivid; keep the world
placeless enough that two friends meet it on the same terms.

**6. No dominant option.** Each of the four must be the right answer for *some*
coherent person. If an option is worse on every axis, it's dead — it signals
"wrong" and collapses to a three-option beat. Every option is somebody's
principle.

**7. Legible consequences.** When a choice echoes later (branches reconverge at
shared gates), the world must respond to a *clear committed vector* of what you
chose — not a hedge, not "you sort of helped but also." Mushy consequences make
the choice unreadable, to the player and to the data.

---

## Writing the defection

The hardest craft in the whole system, and the one most often botched. A
self-interest option written as villainy measures nothing — nobody picks the
cartoon, so the beat only catches who wants to *look* good. Real defection has to
tempt.

**The rule: dress the self-interest in a virtue's clothes, and make the cost
deniable.**

- Disguise it as **humility** ("maybe you're the one who's wrong"), **proportion**
  ("one vote won't decide it"), **prudence** ("you'd only be careful"), or
  **fatigue** ("it's late; you have the morning").
- Make the cost **diffuse, deferred, and deniable.** Nobody pockets gold. They
  *stop*. They *look away*. They let a moment "somehow already pass."
- Offer an exit-line the chooser can tell themselves. The defection a person
  reaches for is the one they don't have to call a defection.

**Worked example — credit for a colleague's work.**

> ✗ *Villain (measures nothing):* "Claim the work as your own. The promotion
> should be yours."

> ✓ *Tempting (measures the gap):* "Let the room go on assuming it was you. You
> *did* carry the thing the fortnight she was out — and correcting them now would
> only muddy a story everyone's already comfortable with. The moment to say
> something has somehow already gone."

The second doesn't lie. It rests on a true thing ("you did carry it"), social ease
("everyone's comfortable"), and the soft cover of inaction ("the moment's gone").
That's how credit is actually taken. **If a tired person at 11pm could reach for
it and feel reasonable, it's right. If it reads as villainy, rewrite.**

**But symmetry still binds the defection.** Tempt it exactly as much as the
virtues compel — no more. Over-seduce the self-interest and you've built a machine
that measures your writing, not their values. The line to walk: the defection is
*as* reachable as the virtues are admirable. Neither louder.

---

## Anchors & option order

- **Anchor text is frozen forever.** The four anchor beats never change — not a
  word, not a comma, no new option, no defection slipped in. Their whole job is to
  mean the identical thing for years so you can read drift and reliability.
  Editing an anchor destroys the baseline retroactively. (Enforced in the DB:
  `gates_protect_anchors`, `choices_no_defection_on_anchor`.)
- **Fixed option order, identical for everyone.** Options are presented in the
  same authored order to every player, every time — this is what makes the shared
  split, the friend-diff, and the share card describe one thing two people both
  saw. (Order is stored as `choices.position` and served deterministically.)
  Position bias becomes a shared constant; it is de-confounded *over time* by
  re-running an edge in a later story with the options authored in a different
  order — the same "vary across re-runs, not within a beat" discipline used for
  scope and framing. Anchors keep their one order frozen forever.
- **Order-independence still binds the prose.** Because order is authored (not
  randomised) but must read cleanly for everyone, no option may depend on
  sequence — no "or instead," nothing that only parses after the option above it.
  Each option stands alone.

---

## Pre-submission checklist

A story enters the corpus only when every line is true.

- [ ] A stranger could not tell which option I'd pick.
- [ ] All four options carry equal sentence-weight, specificity, and dignity.
- [ ] No value is named; no verdict-word survives.
- [ ] No irony, no heroic swell, no narratorial wink.
- [ ] Detail makes the *situation* vivid but leaves the *player* unlocated — it
      travels to a friend unchanged.
- [ ] Every option is some coherent person's right answer; none is dominated.
- [ ] Any defection is deniable and reachable, not cartoonish — and no more
      seductive than the virtues are compelling.
- [ ] *You* are a cipher: situation, not identity.
- [ ] Second person, present tense.
- [ ] Options read cleanly in their authored order and don't depend on sequence.
- [ ] If choices echo later, the consequence reads as one clear committed vector.
- [ ] (If an anchor) not one character has changed.
