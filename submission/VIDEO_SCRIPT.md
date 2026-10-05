# Video script — Tablekeeper (target 4:20, hard ceiling 4:30)

## What this video must contain

Missing any of these risks the entry.

| Requirement | Source | Where it is in this script |
|---|---|---|
| A recording of **the Band Desktop room that generated the solution** | lablab page: "A video without the room recording disqualifies your team" | 0:15–1:55, recorded live in Band Desktop |
| The factory working: **the room, a handoff between seats, and the result it produced** | Participant guide, Eligibility | Room 0:15, handoff 0:50, result 1:55 |
| A walkthrough | lablab page | 1:55–3:00 |
| Factory design, **what it cost**, **a bad result it caught**, **the stage you reached** | Participant guide, Rubric | 0:15 design · 1:10 bad result · 3:30 stage and cost |

## Ground rules for recording

- **Record the real room in Band Desktop.** Do not rebuild it, mock it or replay it from `room.json`.
- **Do not type in the room.** The run is over, and a new message would land in the judged room's history. Keep the cursor away from the message box.
- **Start the app from a clean state** with the seeder (see `JUDGE_DEMO_ROUTE.md`). The seeder's "tonight" is **Tuesday 6 October, Berlin time**. The demo restaurants are closed on Mondays.
- **Do not show the Guarantees section on *My evenings* or the Guarantees table in the Control Room.** Both show `[object Object]`, a known defect.
- **Don't linger on the simulator's "Already closed" line after applying.** It shows the closure in the viewer's time zone.
- Read the narration at a calm pace, about 135 words a minute. If you need more time, cut from 3:00–3:30 first.

Times below are the room's UTC times, with UTC+8 in brackets. Band Desktop may show either; match whichever it shows.

---

## 0:00–0:15 — Hook

**On screen:** Tablekeeper *My Evening* for Ada's 19:00 booking at 1280 px, held still, with the title card **TABLEKEEPER — Reservations that survive reality** over it.

**Narration:**
> Booking a table is easy. Keeping that promise when the evening changes is harder. A response gets lost. A table breaks an hour before service. This is Tablekeeper: reservations that survive reality.

## 0:15–0:50 — The factory, in the room

**On screen:**

1. Band Desktop with the judged room open. The room title is *Oct 5, 2026, 4:16:45 PM*; its id starts with `6c360165`.
2. Pan across the four seats: `architect-x7qk`, `developer-x7qk`, `product-engineer-x7qk`, `independent-verifier-x7qk`.
3. Stop on **RUN-START TABLEKEEPER-FINAL-JUDGED-05**, from the architect at 08:52:05 (16:52).

**Narration:**
> Tablekeeper was built by a factory: four Claude Code seats in one Band Desktop room. A coordinator, a developer, a product engineer and an independent verifier. Each one has a generic mandate that says how it works, not what to build. I dispatched the run once. The coordinator posted RUN-START. From here to END, three hours and twenty-six minutes later, no human wrote in this room.

## 0:50–1:10 — A handoff

**On screen:**

1. Scroll to **S1-DEV-T1**, from the architect to `@developer-x7qk` at 08:59:42 (16:59). Hold on "This handoff is complete when read with S1-SPEC 1/3, 2/3 and 3/3…".
2. Then **S1-DEV-T1 DONE**, from the developer at 09:19:22 (17:19). Hold on "FINAL SHA".

**Narration:**
> Every handoff carries the whole job: the official spec pasted word for word, the rulings, who owns which files, and what evidence to send back. The developer answers with a commit, the commands it ran and its test counts. Then an independent seat decides.

## 1:10–1:55 — The bad result it caught (the centre of the video)

**On screen:** five stops in the room, then a short cut to the app.

1. **S2-PE-T2 — coordinator finding A1** at 10:05:26 (18:05). Hold on "shows the WHOLE page shifted left by about 35 px".
2. **S2-VERDICT C1 … ACCEPT (binding)** from the verifier at 10:23:47 (18:23).
3. **S2 GATE: C1 ACCEPT recorded, gate held open for C2** at 10:24:07 (18:24). Hold on "I am NOT freezing stage-2".
4. **S2-VERDICT C1 REVISED … REJECT (supersedes my ACCEPT e15f88ed)** at 10:25:43 (18:25). Hold for 3 seconds.
5. **S2-VERDICT C2 … ACCEPT (binding)** at 10:30:04 (18:30).
6. Cut to the app at 375 px. The availability grid scrolls sideways inside its frame, and the page itself stays still.

**Narration:**
> This is the moment that matters most. In stage two, the coordinator spotted in a screenshot that the page slid sideways on a 375-pixel phone. The verifier's first pass accepted the build anyway: its test data never produced the layout that broke. The coordinator refused to freeze the stage. The verifier added the missing case, reproduced the overflow, withdrew its own ACCEPT and rejected the candidate. The fix came back through the room and was accepted twenty-five minutes after the problem was raised. Nobody asked me anything.

## 1:55–2:25 — Protect the evening (guest)

**On screen**, at 1280 px and signed in as Ada:

1. Search: Linden Kitchen, Tuesday 6 October, 2 guests. Hold on **Best times for 2 guests**.
2. Book **Window 2 at 17:00**, then hold on the confirmation.
3. Open *My Evening* for Ada's **19:00, Booth 4, 3 guests** booking. Move the cursor slowly over:
   - the **Guarantee — Held — €45.00** card;
   - "What happened to my money?";
   - **Google Calendar / Download .ics**;
   - *Make it yours* (shellfish, Anniversary).

**Narration:**
> For guests, the promise is to protect the evening. Ada sees the best times, with plain reasons, and books. A retry can never double-book her, and a lost response recovers the original confirmation. My Evening is the booking as a companion: the table, a forty-five euro guarantee that says exactly what happened to her money, a calendar file, and the wishes she gave the kitchen.

## 2:25–3:00 — Recover the night (operator)

**On screen:**

1. Sign in as Mara, the manager, and open the **Control room** (Linden Kitchen, Tuesday 6 October). Hold on the four numbers at the top and the bookings table. Do not scroll down to Guarantees.
2. Open the **Recovery simulator**. Choose *Booth 4 · seats 4*, from 17:00 until 23:00, then **Preview repair**.
3. Hold on the card where Booth 4 at 19:00 (Ada) goes to Corner 4, marked **Guest is told**, and on "Messages guests would get".
4. **Apply plan**, confirm, and hold on **Bookings moved — Guests have been told about their new tables.**
5. Cut to Ada's *My Evening*: **Corner 4**, and "Moved by the restaurant" under *What has happened*.

**Narration:**
> For restaurants: recover the night. Booth 4 breaks before service. The recovery simulator runs the real planner on a preview that changes nothing. Ada's party of three moves to Corner 4, with the fewest bookings moved and the fewest empty seats, at the same time and on the same terms. It shows the message she will get. Applying is a separate, deliberate step, and Ada's evening now shows the new table and why it changed.

## 3:00–3:30 — Why it holds up

**On screen:** `FACTORY.md`, *Design choices and what they cost*, scrolled slowly. Or the simulator's own line, "The preview runs the real seating planner but changes nothing".

**Narration:**
> Underneath, the dull parts are strict. Bookings are idempotent and serialised: fifty simultaneous attempts on one table give exactly one booking. Policies are dated, so each booking keeps the terms it accepted. Money is whole cents in an append-only ledger. And the seating planner is exact, checked against brute force on six hundred and forty seeded cases.

## 3:30–4:05 — Stage reached, and what it cost

**On screen:**

1. Band Desktop: the **END — TABLEKEEPER-FINAL-JUDGED-05 — RUN COMPLETE: ALL FOUR STAGES ACCEPTED** message at 12:18:14 (20:18). Hold on its "OFFICIAL HARNESS" lines.
2. Optional: a terminal showing `python -m harness run --track tablekeeper --repo <clone> --all --mode isolated`, ending with "stage-4/: claims stage 4". Speed it up and say so on screen.
3. Then the three **END-ACK** messages.

**Narration:**
> The factory reached all four stages. Each folder passes the official checks in isolated mode, and the verifier's own black-box suites: four hundred and twenty-four, one hundred and forty-three, one hundred and sixty-four and three hundred and forty-three tests. At the very end it caught one more problem: a credential echoed into its own room log. It rejected the final head and had it redacted, and the credential was retired after the run. The run took three hours twenty-six minutes. The day's model spend on that machine, rehearsals included, is estimated at two hundred and eighty-five dollars.

## 4:05–4:20 — Close

**On screen:** the cover image or a plain title card, with `github.com/ihatecodingaaa/tablekeeper-dark-factory`.

**Narration:**
> Tablekeeper: reservations that survive reality. Built by a factory that caught its own bad work, fixed it, and finished without us.

---

**Narration length:** 544 words. That is about 4:00 of speech at 135 words a minute, and the holds on key frames bring the cut to about 4:20.

**Cut order if you run long:**
1. Shorten 3:00–3:30 to one sentence.
2. Drop the optional terminal shot.
3. Shorten the handoff to the DONE message only.

**Never cut:** the room recording, the REJECT sequence, the stage reached or the cost.
