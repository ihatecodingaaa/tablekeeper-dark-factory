# Tablekeeper — Reservations that survive reality

Track: `tablekeeper` (Dark Factory, WeAreDevelopers hackathon).

This repository is the output of an autonomous four-seat agent factory working in one Band
room. Each `stage-N/` folder is a complete, buildable service for that stage. It is the
previous stage carried forward and widened to the next official specification.

| Path | Holds |
|---|---|
| `mandates/` | One generic mandate per seat, each naming its harness and model |
| `FACTORY.md` | How the factory runs: seats, handoffs, gates, evidence |
| `stage-1/` … `stage-4/` | One service per stage, each with its `Dockerfile` and `RUN.md` |
| `room.json` | The full Band room session, added at the end of the run |

The stage folders are added as each stage passes its independent verification gate.
