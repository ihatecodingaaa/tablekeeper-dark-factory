# Video shot list

Use this with `VIDEO_SCRIPT.md`, which holds the narration text and the full timeline.

**Times.** The room's times are UTC, with UTC+8 (Singapore) in brackets. Find each message by its first line, which is quoted below. The id in brackets is the start of its `id` in `room.json`.

**Cursor.**
- *Static* means hands off the mouse and let the text be read.
- *Slow* means one deliberate cursor move to the thing being named.
- Never scroll quickly through hundreds of tool-call events on camera.

## Before you press record

- [ ] **Band Desktop.** The judged room is open; its title is *Oct 5, 2026, 4:16:45 PM* and its id starts with `6c360165`. Notifications are muted. Do not click into the message box, and never send anything.
- [ ] **Room anchors.** Find each anchor below before recording and note its scroll position. Record each anchor as its own short clip, and keep one honest 5-second continuous scroll so viewers can see it is the live room.
- [ ] **App.** Run `docker build` and `docker run`, then `python3 demo/seed_demo.py --base http://localhost:8080` immediately before the take. Copy the printed references; you need `tonight_booth`. The full steps are in `JUDGE_DEMO_ROUTE.md`.
- [ ] **Browser.** Use a clean profile, 1280 px wide for desktop shots, 100–110% zoom, and the bookmarks bar hidden. For mobile, use DevTools device mode at 375 × 812, or a real phone on the same network.
- [ ] **Recorder.** 1920 × 1080, 30 fps, system audio off, mic checked.

## Shots

The **Room** marker means the shot must be recorded in **Band Desktop**.

| # | Screen | Action | Expected visual | Narration (script section) | Dur. | Backup plan |
|---|---|---|---|---|---|---|
| 1 | App, `/evening/<tonight_booth>` as Ada, 1280 px | Static. Add the title card in the edit. | "Your evening at Linden Kitchen", **Booth 4**, 3 guests, Guarantee **Held €45.00** | 0:00 Hook | 15 s | Use the cover image as the background. |
| 2 | **Room** — participant list | Slow pan across the four seats | `architect-x7qk`, `developer-x7qk`, `product-engineer-x7qk`, `independent-verifier-x7qk` | 0:15 Factory | 10 s | If there is no participant panel, show the three ACTIVE-ACK replies at 08:52:35–08:52:53 (16:52), which name each seat. |
| 3 | **Room** — "RUN-START TABLEKEEPER-FINAL-JUDGED-05 (FINAL JUDGED RUN, ZERO-HUMAN)", 08:52:05 (16:52) [`d9a99513`] | Static. Hold on "no seat asks Lucas anything or waits for him". | The architect's message, with the four @handles | 0:15 Factory | 17 s | — |
| 4 | **Room** — a 5-second scroll from RUN-START into the stage 1 messages | Slow, continuous scroll | Spec parts "S1-SPEC 1/3…", tool events going past | 0:15 Factory | 8 s | — |
| 5 | **Room** — "S1-DEV-T1 — TABLEKEEPER-FINAL-JUDGED-05 Stage 1 core. Assigned by the Architect to @developer-x7qk", 08:59:42 (16:59) [`1023054b`] | Static | "This handoff is complete when read with S1-SPEC 1/3, 2/3 and 3/3…" | 0:50 Handoff | 10 s | — |
| 6 | **Room** — "S1-DEV-T1 DONE — … Stage 1 core (Developer)", 09:19:22 (17:19) [`496eed61`] | Slow cursor to "FINAL SHA" | Developer reply with SHA, commands and counts | 0:50 Handoff | 10 s | Use "S1-PE-T1 DONE (Product Engineer)" at 09:23:37 [`1f3861ad`]. |
| 7 | **Room** — "S2-PE-T2 — coordinator finding A1 on S2 C1 115aaf55", 10:05:26 (18:05) [`0062bb79`] | Static | "shows the WHOLE page shifted left by about 35 px" | 1:10 Bad result | 8 s | — |
| 8 | **Room** — "S2-VERDICT C1 … Stage 2 — ACCEPT (binding)", 10:23:47 (18:23) [`e15f88ed`] | Static | The verifier's first verdict | 1:10 | 6 s | — |
| 9 | **Room** — "S2 GATE: C1 ACCEPT recorded, gate held open for C2", 10:24:07 (18:24) [`0fb2433b`] | Slow cursor to "I am NOT freezing stage-2" | The coordinator overrides a premature freeze | 1:10 | 7 s | — |
| 10 | **Room** — "S2-VERDICT C1 REVISED — 115aaf55… — REJECT (supersedes my ACCEPT e15f88ed)", 10:25:43 (18:25) [`19715d9f`] | Static, held for at least 3 s | REJECT with reproduction and observed vs expected | 1:10 | 10 s | Never cut this shot. |
| 11 | **Room** — "S2-VERDICT C2 … Stage 2 — ACCEPT (binding)", 10:30:04 (18:30) [`e110e8cc`] | Static | ACCEPT on 685b1705 | 1:10 | 5 s | — |
| 12 | App at 375 × 812, search results for Linden Kitchen, Tue 6 Oct, 2 guests | Swipe the grid sideways once | The grid scrolls inside its frame and the page header does not move | 1:10 | 9 s | Show 375 px My Evening instead; there is no sideways page scroll anywhere. |
| 13 | App 1280, `/` as Ada: Linden Kitchen, Tue 6 Oct, 2 guests, **Search tables** | Slow cursor to the first Best Times card | **Best times for 2 guests** with 17:00, 17:30 and 20:30 and text reasons, then the grid | 1:55 Guest | 8 s | Re-run the seeder and reload. |
| 14 | App: click **+ Free** at Window 2 17:00, then submit | Slow cursor | Confirmation with a reference and a link to My Evening | 1:55 | 7 s | Use any other "+ Free" cell. |
| 15 | App: `/evening/<tonight_booth>` | Slow cursor in order: Guarantee card, then "What happened to my money?", then Google Calendar / Download .ics, then *Make it yours* | €45.00 held ("Nothing has been charged"), timeline, calendar buttons, shellfish / Anniversary | 1:55 | 15 s | — |
| 16 | App as Mara: **Control room**, Linden Kitchen, Tue 6 Oct, **Show service** | Static on the top half only | Bookings confirmed, Guests expected, Busiest slot, €45.00 Guarantees held, the bookings table | 2:25 Operator | 8 s | **Do not scroll to Guarantees**: the "Last event" column shows `[object Object]`. |
| 17 | App: **Recovery simulator**, Show service, Booth 4 · seats 4, 17:00–23:00, **Preview repair** | Slow cursor to Ada's card | "Proposed repair · 1 booking would move", Booth 4 → **Corner 4**, "Guest is told", "Messages guests would get" | 2:25 | 12 s | Leaving the default 18:00–23:00 gives the same repair. |
| 18 | App: **Apply plan**, then **Apply plan** in the dialog | Slow | **Repair applied**, "Bookings moved — Guests have been told about their new tables", "Messages sent" | 2:25 | 8 s | If Apply fails, stay on the preview and say that applying is a separate step. |
| 19 | App as Ada: `/evening/<tonight_booth>` | Static | **Corner 4**; *What has happened* shows "Moved by the restaurant" | 2:25 | 7 s | Use Look up with the reference instead. |
| 20 | GitHub or editor: `FACTORY.md`, *Design choices and what they cost* | Slow scroll | Lock, byte-exact replays, exact optimizer, black-box verifier | 3:00 Why | 30 s | Use the README *Architecture (brief)* section. |
| 21 | **Room** — "END — TABLEKEEPER-FINAL-JUDGED-05 — RUN COMPLETE: ALL FOUR STAGES ACCEPTED", 12:18:14 (20:18) [`66d0db05`] | Slow cursor to "OFFICIAL HARNESS" | Accepted SHAs, suites, harness claims | 3:30 Results | 18 s | — |
| 22 | Terminal (optional): `python -m harness run --track tablekeeper --repo <clone> --all --mode isolated` | Speed it up and label it "4 min, sped up" | "stage-1/: claims stage 1" … "stage-4/: claims stage 4" | 3:30 | 10 s | Skip it; shot 21 carries the result. |
| 23 | **Room** — the three END-ACKs, 12:18:27–12:19:32 (20:18–20:19) [`b4824f3e`, `ed8eb1d9`, `e202be0e`] | Static | The developer, verifier and product engineer acknowledge END | 3:30 | 7 s | — |
| 24 | Cover image or title card plus the repo URL | Static | TABLEKEEPER, "Reservations that survive reality", `github.com/ihatecodingaaa/tablekeeper-dark-factory` | 4:05 Close | 15 s | — |

Total: 4:20. That is 0:15 + 0:35 + 0:20 + 0:45 + 0:30 + 0:35 + 0:30 + 0:35 + 0:15, matching the script's sections.

## If a room anchor is hard to find

- Every anchor above is a `text` event. Tool-call events sit between them.
- If Band Desktop can filter or search the room, use that. Otherwise scroll by time: the anchors are in time order.
- The Band console (room ⋮ menu → *Open in Band*) has the **Event type** filter that the participant guide mentions. It is fine for finding positions. The recording itself must show **Band Desktop**.
- `room.json` lists every message with its `insertedAt` time. Use it to work out how far to scroll.
