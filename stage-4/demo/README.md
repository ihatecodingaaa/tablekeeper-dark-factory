# Tablekeeper demo world

A short, honest walkthrough of "Reservations that survive reality". Every
booking, policy and deposit below is created through the real API by
`seed_demo.py`; nothing is mocked or invented.

## 1. Start the service

From `stage-4/`:

```sh
docker build -t tablekeeper .
docker run --rm -e PORT=8080 -p 8080:8080 tablekeeper
```

Wait for `GET http://localhost:8080/health` to answer `{"status": "ok"}`.

## 2. Seed the demo world

In another terminal, from `stage-4/` (Python 3.10+ standard library only; the
seeder talks to nothing but `--base`):

```sh
python3 demo/seed_demo.py --base http://localhost:8080
```

Every run starts with `POST /_test/reset`, so you can run it again at any time
to get a fresh world. The seeder prints the accounts and booking references.

| Account | Email | Role |
|---|---|---|
| Mara | `manager@tablekeeper.demo` | Manager of both restaurants |
| Ada | `ada@tablekeeper.demo` | Diner |
| Ben | `ben@tablekeeper.demo` | Diner |
| Cleo | `cleo@tablekeeper.demo` | Diner |

All four use the **demo-only** password `tablekeeper-demo`. It is published on
purpose and is not a real credential.

What gets created:

- **Linden Kitchen** (Europe/Berlin): Window 2, Booth 4, Terrace 6 and Corner 4, with
  the pairs Window 2 + Booth 4 and Booth 4 + Terrace 6. It is closed on Mondays. A
  published policy from the fifth open day on lengthens a sitting to 120 minutes.
- **Harbor & Vine** (America/New_York): Bar 2, Booth 4 and Garden 6, with the pair
  Bar 2 + Booth 4. It is closed on Mondays.
- **Bookings** over the next open days:
  - tonight in Booth 4 (Ada) and Window 2 (Ben);
  - a pair for eight on Booth 4 + Terrace 6 (Cleo);
  - an amended booking (Ada, now three guests at 18:30);
  - a cancelled booking (Ben);
  - a booking under the new policy (Cleo);
  - a pair at Harbor & Vine (Ben);
  - a weekly series of four evenings at Harbor & Vine (Ada).
- **Guarantees** held on Ada's booth tonight and on Ben's Harbor pair (EUR 15.00 per
  guest by default).
- **Preferences** on two bookings: an allergy and an anniversary, and step-free access.

## 3. Walk the product

Open `http://localhost:8080/` in a browser.

1. **Sign in as Ada** and open her booth booking for tonight from *Look up* or the
   confirmation link to reach **My Evening** (`/evening/<reference>`). It shows:
   - the tables;
   - the calm status line;
   - the Guarantee card, answering "What happened to my money?";
   - "Add to calendar" (a Google link plus an `.ics` download);
   - her preferences ("we'll do our best");
   - the notification history.
2. **Sign in as Mara** and open the **Control Room** (`/control-room`). Choose Linden
   Kitchen and tonight's date. It shows:
   - the reservations with their guarantee state and preference flags;
   - the seat pressure per slot;
   - the policy in force;
   - recent changes;
   - the guarantee settlement;
   - the outbox.
3. **Recovery Simulator** (`/simulator`, as Mara):
   - Pick Linden Kitchen, **Booth 4**, and a window covering tonight's service, for
     example 17:00 to 23:00 local time.
   - The simulator runs the official `POST /restaurants/r_linden/replans` preview. It
     stores only a plan and changes nothing.
   - Read the BEFORE → disruption → repair → AFTER view. Ada's party of three moves to
     a table that fits under her own accepted terms, and the messages that would be
     sent are listed.
   - **Apply plan** is a separate, explicit button. It calls the official apply, after
     which availability, confirmation, lookup and My Evening all show the new table.
4. **Guarantee capture after start.** Once tonight's booth booking has started, Mara
   can record a no-show in the Control Room's settlement. That calls the manager
   *capture* action, which is allowed only at or after the start. A capture can then
   be *refunded* in full. Ada sees each step in her Guarantee card timeline. A second
   capture or refund is refused (`409 invalid_transition`), and retrying the same
   request replays it safely.

## 4. Useful API calls

```sh
TOKEN=$(curl -s localhost:8080/auth/login -H 'Content-Type: application/json' \
  -d '{"email":"ada@tablekeeper.demo","password":"tablekeeper-demo"}' | python3 -c 'import json,sys; print(json.load(sys.stdin)["token"])')
curl -s localhost:8080/reservations -H "Authorization: Bearer $TOKEN"
curl -s "localhost:8080/x/best-times?restaurant_id=r_linden&date=$(date +%F)&party_size=2"
```
