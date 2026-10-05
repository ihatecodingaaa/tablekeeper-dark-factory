# lablab submission form — field checklist

**Source of the form fields:** the event page's "Submission form on lablab.ai" section, from the owner's screenshots taken on 5 Oct 2026. The page itself (`lablab.ai`) was blocked from the review environment, so field limits and any fields added since the screenshots could not be checked. Look at the live form before pasting.

**Formats:** lablab's *general* submission guidance, seen only as a search-engine summary and not verified, asks for:

- an MP4 video;
- a PDF slide deck;
- a 16:9 PNG or JPG cover image.

The event page does not contradict this, so prepare those formats.

**Statuses:** READY means the content exists and only needs pasting or uploading. NOT READY means it must still be made.

## Before opening the form

| Item | Source | Status | Human action |
|---|---|---|---|
| Registered on lablab.ai **and** the lablab.ai Discord, and enrolled in the event | Event page, "How to participate" | NEEDS HUMAN | Confirm. |
| Team of 1–6 people, as registered on lablab | Event page, "Teams" | NEEDS HUMAN | Confirm the team on lablab. The README says "Team: Lucas Tan"; edit that line if the team has other members. |
| The docs branch `submission-polish-cloud` is reviewed and merged, so judges see the corrected README and FACTORY | — | NEEDS HUMAN | Review, merge to `main` and push, before submitting. |

## Basic information

| Field | Ready content | Status | Human action |
|---|---|---|---|
| **Project title** | `Tablekeeper — Reservations that survive reality` (shorter: `Tablekeeper`) | READY | Paste. Use the shorter form if the field is limited. |
| **Short description** | `SUBMISSION_COPY.md` → *Short description*: 97 words, 582 characters | READY | Paste. If the field's limit is under 582 characters, use the one-sentence *Very short description* (174 characters). |
| **Long description** | `SUBMISSION_COPY.md` → *Long description*: 544 words, about 3,200 characters | READY | Paste. If there is a cap, cut from the "Limitations" paragraph's middle sentence first. Do not cut the limitations entirely. |
| **Technology & category tags** | Technology: Band Desktop, Claude Code, Anthropic Claude, Python, Docker, Playwright, pytest, JavaScript. Category: AI agents, multi-agent systems, developer tools, hospitality | READY (suggestions) | Pick the closest matches from the form's own list. Do not invent tags the form rejects. |

## Cover image and presentation

| Field | Ready content | Status | Human action |
|---|---|---|---|
| **Cover image** | Brief and prompt in `COVER_BRIEF.md` | NOT READY | Generate the image, add the title in an editor, pass the 320 × 180 thumbnail test, and export a 16:9 PNG or JPG. |
| **Video presentation** | `VIDEO_SCRIPT.md` (narration, 4:20) and `VIDEO_SHOTLIST.md` (24 shots) | NOT READY | Record the **Band Desktop room**, which is mandatory: without it the team is disqualified. Then record the app walkthrough, narrate, edit and export MP4. Upload it, or paste a link if the form asks for one. Check that it plays when signed out. |
| **Slide presentation** | `SLIDE_OUTLINE.md` (six slides) | NOT READY | Build the deck with real screenshots, export it as PDF and upload. |

## Repository

| Field | Ready content | Status | Human action |
|---|---|---|---|
| **Public GitHub repository** | `https://github.com/ihatecodingaaa/tablekeeper-dark-factory` | READY. The GitHub API reports visibility `public`, and an anonymous page fetch returns 200. | Paste. Keep the repository public until judging ends. |

## After submitting

- [ ] Save the confirmation or receipt; the participant guide's last step says to keep it.
- [ ] Open the public submission page while signed out. Check that the video plays, the PDF opens and the repository link resolves.
- [ ] Do not push anything to `stage-*/`, `mandates/` or `room.json` after submitting.
