# ADHD-Friendly Content Guidelines

**Purpose:** Define what "good" looks like for briefing summaries, so we can (1) write the
summarizer prompt, (2) build an eval rubric with measurable criteria, and (3) design a
synthetic golden set that exercises each failure mode.

These guidelines are grounded in widely-described features of ADHD cognition and in
information-design practice — not in a specific cited study. They describe *mechanisms*
and the writing rules that follow from them.

---

## 1. Why ADHD changes how content should be written (mechanisms)

| Mechanism | Consequence for content |
|---|---|
| **Working memory load** — harder to hold several items / nested clauses in mind | Short sentences, one idea each; no long wind-ups before the point |
| **Activation energy** — starting is the hard part; high-friction text doesn't get read | Lower the cost to start: lead with the payoff, keep it short, make it skimmable |
| **Attention regulation** (dysregulation, not absence) — pulled away easily | Hook fast, front-load value; structure so the reader can re-enter after drifting |
| **Interest/relevance-driven engagement** — relevance and clear payoff sustain attention | Make "why this matters to me" explicit; concrete > abstract |
| **Overwhelm threshold** — walls of text and too many choices trigger shutdown | Cap quantity; chunk; whitespace; predictable structure |
| **Time blindness** — fuzzy sense of effort/scope | Optional scope cues (length, "what to do"); bounded, finite output |

---

## 2. Writing rules (the "how")

### A. Brevity & density
- Cut filler, hedging, and throat-clearing ("In today's fast-paced world…", "It's important to note…").
- One idea per sentence and per bullet.
- Prefer concrete nouns and strong verbs over abstractions.

### B. Front-load the point (BLUF — bottom line up front)
- Lead with the outcome / "so what." Supporting detail comes after.
- The main takeaway should stand on its own without reading the bullets.

### C. Scannability & structure
- Bullets over paragraphs; atomic and parallel.
- Most important first.
- Consistent, predictable layout every day (lowers re-orientation cost).
- Signposts (emoji/labels) used sparingly and consistently as visual anchors — not decoration.

### D. Cognitive-load management
- Cap quantity: max 5 articles per briefing; 2–4 bullets per article.
- No nested complexity; avoid jargon or define it inline.
- Be literal and unambiguous — don't make the reader infer.

### E. Relevance & engagement
- Make relevance explicit: why this matters / who should care.
- Concrete specifics (numbers, names, the actual claim) beat vague gestures ("discusses various aspects").
- A hook in the opening line — without sacrificing clarity.

### F. Action orientation (bridge to the "A" in CRA)
- Favor takeaways the reader can *act on* ("what you can do with this").
- This is the seed for the future Action phase; even now, an actionable main_outcome beats a descriptive one.

---

## 3. Anti-patterns (what to penalize)

- **Wall of text** — dense paragraph instead of bullets.
- **Buried lede** — the point arrives in sentence four.
- **Filler / hedging** — "might possibly perhaps", "it could be argued".
- **Vagueness** — "explores several important themes" with no actual content.
- **Jargon dump** — unexplained terms.
- **Overload** — too many bullets / too many articles.
- **Clickbait or empty title echo** — title restated as the takeaway with no added meaning.
- **Decode cost** — arrow-chains (A → B → fails), stacked abbreviations, invented shorthand.
- **Hallucination** — claims not supported by the source (the cardinal sin).

---

## 4. Derived eval rubric (measurable criteria)

Each summary scored on these dimensions. Marked **[gate]** = a hard failure regardless of other
scores; **[judge]** = needs an LLM judge; **[auto]** = checkable programmatically.

| # | Dimension | What "good" means | Type |
|---|---|---|---|
| 1 | **Faithfulness** [gate] | Every claim is supported by the source; nothing invented | judge |
| 2 | **Front-loaded** | `main_outcome` states the key point and stands alone | judge |
| 3 | **Conciseness** | No filler; every word earns its place | judge |
| 4 | **Specificity** | Concrete facts (numbers, names, the actual claim), not vague gestures | judge |
| 5 | **Actionability/relevance** | Reader can tell why it matters / what to do | judge |
| 6 | **Clarity** | Plain language, no unexplained jargon, unambiguous | judge |
| 7 | **Atomic bullets** | Each bullet is one idea, parallel structure | judge |
| 8 | **Length bounds** | 2–4 bullets; bullets reasonably short; `main_outcome` one sentence | auto |
| 9 | **Format validity** | Valid structure (tldr list + main_outcome string) | auto |

**Scoring:** dimensions 2–7 on 1–5; dimension 1 (faithfulness) is pass/fail and gates the whole
summary; 8–9 are deterministic checks. Overall = gated weighted average (weights TBD with you).

---

## 5. How this drives the golden set

The synthetic golden set pairs **source text → reference summary**, plus deliberately **bad
variants** that each violate one principle, so evals can prove they catch the failure:

- ✅ *Good* — concise, front-loaded, specific, faithful, atomic bullets.
- ❌ *Buried lede* — same facts, point hidden at the end.
- ❌ *Vague* — no concrete facts, generic phrasing.
- ❌ *Filler-heavy* — padded with throat-clearing.
- ❌ *Hallucinated* — adds a claim not in the source.
- ❌ *Overlong* — 8 bullets, long sentences.

A working eval should score the good variant high and each bad variant low on the dimension it
violates. That validates the *eval itself* before we use it to tune the prompt.

---

## 6. Decisions (locked with the user)

- **Weighting:** `faithfulness` is a hard gate. Highest-weighted quality dimensions are
  **front-loaded (BLUF)** and **specificity (concrete facts)** — these are what makes the
  user actually read vs bounce. Conciseness, actionability, clarity, atomic bullets are
  secondary contributors.
- **Tone = user choice (feature):** the user picks a tone preset; it parameterizes the
  summarizer prompt and is stored per user. Presets:
  - `neutral` — factual, no ornament (default)
  - `warm` — factual + light accountability/encouragement (ADHD external-motivation angle)
  - `direct` — short, punchy, second-person ("You should…")
  Tone is a *stylistic layer*; the core quality dimensions (faithfulness, BLUF, specificity)
  are tone-independent and are what evals optimize first.
- **Reading-time cue:** YES — show an estimated read time per article (helps time-blindness /
  activation energy). Computed from available source text (≈200 wpm); approximate for feed
  items where only the RSS summary is available.
- **Length target:** 2–4 bullets + one `main_outcome` sentence (unchanged).

### Implications for build order
1. **Now:** synthetic golden set + eval harness (validate the eval discriminates good vs bad).
2. **Then:** refine summarizer prompt against the eval; add read-time to the briefing format.
3. **Then:** tone-as-user-choice — onboarding question + `users.tone` column + prompt param.
