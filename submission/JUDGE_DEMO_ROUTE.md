# Judge demo route — about 6 minutes, deterministic

This is the shortest path through the strongest moments. Every label and value below was observed in a post-run walk through a container built from the public repository.

---

## Starting state (2 minutes, once)

```sh
git clone https://github.com/ihatecodingaaa/tablekeeper-dark-factory
cd tablekeeper-dark-factory/stage-4
docker build -t tablekeeper .
docker run --rm -e PORT=8080 -p 8080:8080 tablekeeper
```

In a second terminal, from `stage-4/` (Python 3.10+, standard library only):

```sh
python3 demo/seed_demo.py --base http://localhost:8080
```

- The seeder prints the accounts and the booking references. **Copy the `tonight_booth` reference.**
- All accounts use the published demo-only password `tablekeeper-demo`.
- **"Tonight" is the next open evening in Berlin.** The demo restaurants are closed on Mondays, so any run before the submission deadline (Tuesday 6 Oct, 08:59 Berlin time) seeds **Tuesday 6 October 2026**.
- Run the seeder again at any time to reset the world. Every run starts with a reset, so references change.

Open `http://localhost:8080/` at 1280 px wide.

---

## 1. Guest books (≈ 60 s)

**Click sequence:**

1. Click **Sign in** and enter `ada@tablekeeper.demo` / `tablekeeper-demo`.
2. Go to **Search**. Choose Restaurant *Linden Kitchen*, Date *Tue 6 Oct 2026* and Guests *2*, then click **Search tables**.
3. In the Window 2 column, click **+ Free** at **17:00**, then click **Confirm booking**.

**Expected UI:**

- The header shows **Ada**, and the navigation reads *Search · Look up · My evenings · Messages*.
- **Best times for 2 guests** lists 17:00 and 17:30 ("4 tables free · 2 joined options too · quietest: 0 bookings overlapping"), then 20:30, 21:00 and 21:30.
- The grid has columns *Window 2 · Booth 4 · Terrace 6 · Corner 4 · Joined tables*. Booth 4 shows **− Booked** for start times 18:00 to 20:00; that is Ada's seeded 19:00 booking, which lasts 90 minutes.
- The panel shows "Book this table — Window 2 · seats 2". After you confirm, it shows **Booking confirmed — YOUR REFERENCE …** with *Manage booking · Open your evening*. Window 2 at 17:00–18:00 now reads **Yours**.

**Talking point:** "A retry of this request can never create a second booking, and if the response is lost, retrying shows the original reference. That is stage 1 and stage 2 of the spec, checked by the official suite."

**Fallback:** if a cell is taken, click any other **+ Free** cell. The form keeps your input and the grid refreshes; this is itself a stage 2 behaviour.

## 2. My Evening and the Guarantee (≈ 60 s)

**Click sequence:** go to `http://localhost:8080/evening/<tonight_booth>`. This is Ada's seeded 19:00 booking for three guests.

**Expected UI:**

- **Your evening at Linden Kitchen**: Tuesday, 6 October 2026 at 19:00 · 3 guests · Booth 4 · *Confirmed*.
- **Guarantee — Held — €45.00**: "€45.00 is held for your party of 3. Nothing has been charged."
- **What happened to my money?** shows *Held · €45.00 · 3 guests × €15.00*.
- **Keep it handy**: *Google Calendar*, *Download .ics* (a valid calendar file named `tablekeeper-<ref>.ics`) and *Share*.
- **Make it yours**: allergy *shellfish*, occasion *Anniversary*, "a quiet corner if possible", and the line "We'll do our best. The restaurant sees these wishes, but they can't be guaranteed."
- **Messages about this evening**: *Deposit held* and *Table confirmed*, each marked "Delivered here".

**Talking point:** "The guarantee is a simulated deposit kept to payment rules: whole cents, idempotent steps, an append-only ledger, released automatically on cancellation. It is not card processing."

**Fallback:** if you lost the reference, open **Look up**, or **My evenings** and the 19:00 Linden Kitchen card.

> **Avoid:** the *Guarantees* section lower down **My evenings**. It shows `€45.00 · [object Object]`, a known display defect listed in the README.

## 3. Operator: Control Room (≈ 30 s)

**Click sequence:**

1. Click **Sign out**, then sign in as `manager@tablekeeper.demo`. The navigation gains *Control room · Simulator*.
2. Open **Control room**. Choose Restaurant *Linden Kitchen* and Service date *Tue 6 Oct 2026*, then click **Show service**.

**Expected UI:**

- The top row reads **3 · Bookings confirmed**, **7 · Guests expected**, **31% · Busiest at 18:00** and **€45.00 · Guarantees held**. These counts include step 1's booking; without it, they are lower.
- **Bookings on Tuesday, 6 October 2026** lists each booking's time, guest, party, tables, status, wishes and guarantee.
- **How full each slot is** and **Rules in force** follow, and further down **Messages to guests** ("Email and Telegram are simulated unless credentials are configured on the server").

**Talking point:** "The service day, the pressure per slot and the money held, in one place."

> **Avoid:** the **Guarantees** table. Its *Last event* column shows `[object Object]`.

## 4. Operator: Recovery Simulator, the strongest product moment (≈ 90 s)

**Click sequence:**

1. Open **Simulator**. Choose *Linden Kitchen* and *Tue 6 Oct 2026*, then click **Show service**.
2. Set **Table that becomes unavailable** to **Booth 4 · seats 4**. The default is Window 2, so change it.
3. Set **From** to *17:00* and **Until** to *23:00*, then click **Preview repair**.
4. Click **Apply plan**. In the "Apply this repair?" dialog, click **Apply plan** again.

**Expected UI:**

- Four steps run across the top: *1. Healthy service · 2. Disruption · 3. Repair preview · 4. Applied*.
- The page note reads: "The preview runs the real seating planner but changes nothing; only 'Apply plan' moves bookings, and it asks first."
- **Proposed repair** shows "1 booking would move · 1 unused seat". In Ada's card, **BEFORE** Booth 4 · 19:00 · Ada, **DISRUPTION** Booth 4 closed 17:00–23:00, **AFTER** **Corner 4**, *Guest is told*. It explains: "Fits the party of 3 under the terms this booking accepted, with no clash with other bookings or closed tables. Time, party and terms stay the same." The other bookings show *Stays*.
- **Messages guests would get** lists the message to Ada.
- After applying: **Repair applied**, "Bookings moved — Guests have been told about their new tables." **Messages sent** reads: "Your table at Linden Kitchen on Tuesday, 6 October 2026 at 19:00 changes from Booth 4 to Corner 4. Your time, party size and booking terms stay the same."

**Talking point:** "The planner is exact. It moves the fewest bookings, then leaves the fewest empty seats, then follows a fixed preference order. It was checked against brute force on 640 seeded cases. The preview and the apply are the official stage 4 API, and the apply is atomic."

**Fallback:**

- The time inputs may display as 12-hour (*06:00 PM*) depending on the OS locale. Leaving the default 18:00–23:00 gives the same repair.
- If **Apply plan** fails, stop at the preview. It is the decision point, and it changes nothing.

> **Avoid lingering on:** the "Already closed: Booth 4 (…)" line that appears under *Service now* after applying. It prints the window in your browser's time zone, not Berlin time.

## 5. The guest sees the change (≈ 20 s)

**Click sequence:** sign out, sign in as Ada, and open `/evening/<tonight_booth>` again.

**Expected UI:** the tables now read **Corner 4**. Under *What has happened* there are two entries: *Booked*, then **Moved by the restaurant · Table changed**.

**Talking point:** "Protect the evening, recover the night: one change, applied once, and every screen tells the guest what happened."

## 6. The factory proof (≈ 60 s)

**Click sequence:** in Band Desktop, open the judged room and go to **"S2-VERDICT C1 REVISED … REJECT (supersedes my ACCEPT e15f88ed)"** at 10:25:43 UTC (18:25 at UTC+8). Then open the coordinator's **"gate held open for C2"** message at 10:24:07, just before it.

- **Without Band Desktop:** open `FACTORY.md` → *What the factory caught*. Or search `room.json` for `19715d9f`.

**Talking point:** "The verifier first accepted this build. The coordinator wouldn't freeze the stage, the verifier reproduced the overflow, withdrew its ACCEPT and rejected the build, and the fix was accepted 25 minutes after the problem was raised. No human was involved."

---

## If something goes wrong

| Problem | Do this |
|---|---|
| `docker build` cannot reach PyPI | It needs network only at build time, for `tzdata`. Retry on a normal network. The running container needs no network. |
| The seeder prints "seeding failed" | Check that the container is up (`curl -s localhost:8080/health` returns `{"status":"ok"}`), then re-run the seeder. |
| The page looks empty after sign-in | Search with *Linden Kitchen* and the seeded Tuesday. Monday is a closed day. |
| A screen errors mid-demo | Reload. State lives in the container's memory, so a re-seed restores the whole world in seconds. |
