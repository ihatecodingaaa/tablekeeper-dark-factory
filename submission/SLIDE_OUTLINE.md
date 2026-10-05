# Slide outline — six slides

The participant guide asks the presentation and video to explain four things: the factory design, what it cost, a bad result it caught, and the stage you reached. Slides 4, 5 and 6 carry those. Slides 1–3 make the product clear in under 30 seconds.

**Visual system for all six slides:**

- **Background:** warm off-white (the app uses a cream background).
- **Accent:** one terracotta, taken from the app's primary button.
- **Type:** a serif headline face and a plain sans-serif for body text, like the app.
- **Images:** real screenshots only, cropped tight, and no device-frame mock-ups unless they are plain.
- **Text:** at most one accent colour and three lines of body text per slide.

**Export:** PDF. lablab's general guidance asks for PDF slides; I could not open the event's form to confirm this.

---

## 1. TABLEKEEPER

- **Headline:** TABLEKEEPER
- **Single takeaway:** a reservation system for what happens after the booking.
- **Visual:** the cover image (see `COVER_BRIEF.md`), full bleed, with the title in its negative space.
- **Maximum text:** "TABLEKEEPER", "Reservations that survive reality.", and a small "Built by a four-seat Band Desktop factory · WeAreDevelopers Dark Factory".
- **Speaker note:** "Tablekeeper is a reservation system built for what happens after the booking. And it was built entirely by a factory of four agent seats."
- **Do not include:** logos of tools, model names, robot or AI imagery, or a feature list.

## 2. The promise breaks after the booking

- **Headline:** The promise breaks after the booking
- **Single takeaway:** real evenings fail in four ordinary ways, and most systems stop caring at "book".
- **Visual:** four short lines, set as a quiet vertical list with a thin terracotta rule:
  - A confirmation lost on a bad connection.
  - Two people tap the same table.
  - The restaurant changes its hours.
  - A table breaks before service.
- **Maximum text:** the headline and those four lines.
- **Speaker note:** "None of these is exotic. Each one, handled badly, ruins someone's evening or someone's service."
- **Do not include:** market sizes, statistics or "X% of diners" claims. We have no sourced numbers.

## 3. Protect the evening · Recover the night

- **Headline:** Protect the evening · Recover the night
- **Single takeaway:** one system, two promises: one for the guest, one for the restaurant.
- **Visual:** two real screenshots side by side, from the seeded demo.
  - Left: *My Evening* (Booth 4, Guarantee Held €45.00).
  - Right: the *Recovery simulator* after preview (Booth 4 → Corner 4, "Guest is told").
- **Maximum text:**
  - Under the left screenshot: "Guests: no duplicate bookings, a traceable deposit, calendar and wishes in one place."
  - Under the right screenshot: "Restaurants: rehearse a closure on the exact planner, then apply."
- **Speaker note:** "For guests, the promise is to protect the evening. For restaurants, the promise is to recover the night. The seating repair is exact: fewest bookings moved, then fewest empty seats, previewed before anything changes."
- **Do not include:** a grid of twelve features, or the Control Room's Guarantees table, which shows a known `[object Object]` defect.

## 4. A factory of four seats

- **Headline:** Four seats. One dispatch. No human in the room.
- **Single takeaway:** a small, generic factory with an independent verifier and frozen stages.
- **Visual:**
  - Four labelled boxes: Coordinator, Developer, Product engineer, Independent verifier.
  - One flow line under them: *spec pasted in the room → contract → parallel owned work → coordinator gate → independent verdict on one commit → freeze and carry forward*.
- **Maximum text:** the box labels, the flow line, and "RUN-START 08:52 → END 12:18 UTC · 2,795 room events, none from a human".
- **Speaker note:** "Each mandate says how a seat works, never what to build. You could point them at a payments app tomorrow. The verifier writes its own tests from the spec, never reads our code, and gives a binding verdict on one exact commit."
- **Do not include:** brain or robot icons, glowing network diagrams, or seat chat excerpts longer than one line.

## 5. It rejected its own work

- **Headline:** It rejected its own work, then fixed it
- **Single takeaway:** the review was real. The factory caught a defect that its own verifier had first accepted.
- **Visual:**
  - Left: a five-step timeline using the room's exact times (UTC):
    - **10:05** Coordinator: page shifts sideways at 375 px.
    - **10:23** Verifier: ACCEPT (missed it).
    - **10:24** Coordinator: stage stays open.
    - **10:25** Verifier: REJECT, reproduced.
    - **10:30** Fixed candidate: ACCEPT.
  - Right: a real 375 px screenshot of the fixed search screen.
- **Maximum text:** the timeline, plus one footnote line: "Also caught: a credential echoed into the room log. Final head rejected, redacted before END."
- **Speaker note:** "The verifier's test data never produced the broken layout, so it accepted. The coordinator didn't trust a green verdict and held the stage open. The verifier reproduced the bug, withdrew its own ACCEPT and rejected. Twenty-five minutes, no human."
- **Do not include:** the claim that the verifier caught it first. The coordinator did.

## 6. What it reached, and what it cost

- **Headline:** Four of four stages
- **Single takeaway:** the factory finished the whole track, and the cost is stated honestly.
- **Visual:** three plain figures in a row, with one line of small print.

  | All four stages accepted | 3 h 26 min | ≈ $285 |
  |---|---|---|
  | official checks 120 · 25 · 7 · 6 in isolated mode; verifier suites 424 · 143 · 164 · 343 | RUN-START to END | catalog estimate for the machine's whole day, rehearsals included |

  Small print: the repository URL, `github.com/ihatecodingaaa/tablekeeper-dark-factory`.
- **Maximum text:** the three figures and their captions, plus the URL.
- **Speaker note:** "All four stages were accepted on exact commits, each folder passes the official checks in isolated mode, and the optimizer was checked against brute force on 640 seeded cases. The spend is an estimate for the whole machine-day, rehearsals included."
- **Do not include:** a precise "cost of the run" (we do not have one), speed-up or productivity percentages, or comparisons with human teams.
