---
name: bookmaker-injected-screenshot
description: Process MPG bookmaker-injected exact-score strategy screenshots. Use when the user pastes or attaches a bookmaker correct-score screenshot, bookmaker exact-score odds, bettor percentages, or asks for top MPG bets using the bookmaker-injected workflow. Covers transcribing the screenshot, logging the odds through bookmaker_injected_strategy.py, verifying persistence, and returning the required top-5 EV table format.
---

# Bookmaker Injected Screenshot

## Overview

Follow the repository workflow for bookmaker-injected MPG exact-score picks. The source of truth for calculation details and output format is `docs/bookmaker_injected_mpg_strategy.md`; read it before processing a screenshot.

## Workflow

1. Read `docs/bookmaker_injected_mpg_strategy.md`, especially the required output format and logging instructions.
2. Inspect the attached screenshot and transcribe every visible correct-score row:
   - `score`
   - decimal odds
   - bettor share percentage
   - home team and away team
3. Cross-check the fixture in local data:
   - `data/mpg/mpg.txt` for MPG points and team order
   - `data/processed/latest_game_probabilities.csv` for home/draw/away probabilities
4. Create a temporary CSV in the workspace with the columns expected by `bookmaker_injected_strategy.py`. Include all listed exact scores and the `Other` row if shown.
5. Run the calculator with logging enabled unless the user explicitly says not to log. Use both bettor-share variants:

```bash
.venv/bin/python bookmaker_injected_strategy.py <temporary-input.csv> --submission-id <stable-id> --logged-at-utc <timestamp> --bettor-share-transfer both
```

Use `--no-log` only when the user explicitly asks for a scratch calculation.

6. Verify the submission was appended:

```bash
.venv/bin/rg -n "<stable-id>" data/bookmaker_injected
```

7. Delete the temporary CSV after successful verification. Do not delete or revert the logged output files.
8. Return the calculator's top five rows in the exact table format from the markdown. For elimination games, return both logged variants:
   - `no_transfer`: displayed bettor shares are used as-is.
   - `transfer`: draw bettor shares are transferred to +1 extra-time winner scores before rarity tiers are calculated.

## Output Format

Return one section per processed game and bettor-share variant:

```markdown
### Home vs Away (no_transfer)

| Rank | Exact score | Outcome probability | Exact-score probability | Conditional bettor share | Bonus | Expected bonus | Base EV | Exact-score EV | Total EV |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | Home 2-0 | 00.00% | 00.00% | 00.00% | 50 pts | 00.00 pts | 00.00 | 00.00 | **00.00** |
| 2 | Draw 1-1 | 00.00% | 00.00% | 00.00% | 30 pts | 00.00 pts | 00.00 | 00.00 | **00.00** |
| 3 | Away 0-1 | 00.00% | 00.00% | 00.00% | 70 pts | 00.00 pts | 00.00 | 00.00 | **00.00** |
| 4 | Home 1-0 | 00.00% | 00.00% | 00.00% | 20 pts | 00.00 pts | 00.00 | 00.00 | **00.00** |
| 5 | Away 1-2 | 00.00% | 00.00% | 00.00% | 100 pts | 00.00 pts | 00.00 | 00.00 | **00.00** |

Best pick: <exact score>

### Home vs Away (transfer)

| Rank | Exact score | Outcome probability | Exact-score probability | Conditional bettor share | Bonus | Expected bonus | Base EV | Exact-score EV | Total EV |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | Home 2-0 | 00.00% | 00.00% | 00.00% | 50 pts | 00.00 pts | 00.00 | 00.00 | **00.00** |

Best pick: <exact score>
```

Formatting rules:

- Show percentages with two decimals.
- Show EV values with two decimals.
- Bold every `Total EV` value.
- Label home and away exact scores with the team name, and draws as `Draw X-X`.
- State `Best pick: <exact score>` after the table.
- Mention when the top candidates are separated by less than one expected point.

## Operational Notes

- Prefer `.venv/bin/python` and `.venv/bin/rg` in this repository.
- If `rg` is missing, install or use the available local equivalent, then continue.
- Use a stable submission id, such as `screenshot-home-away-YYYYMMDD`.
- Use the current timestamp or a clear monotonic timestamp for `--logged-at-utc`.
- When running `simulate_bookmaker_injected.py`, expect both `no_transfer` and `transfer` variant results and report them separately.
- If the screenshot is ambiguous, inspect the image carefully before running the calculator. Ask for clarification only when a row cannot be read with enough confidence.
- If multiple games are present and the user identifies one new game, process only that game. Otherwise produce a separate table for every game.
- Do not log duplicate rows for the same screenshot unless the user is explicitly correcting a prior transcription.

### references/
Documentation and reference material intended to be loaded into context to inform Codex's process and thinking.

**Examples from other skills:**
- Product management: `communication.md`, `context_building.md` - detailed workflow guides
- BigQuery: API reference documentation and query examples
- Finance: Schema documentation, company policies

**Appropriate for:** In-depth documentation, API references, database schemas, comprehensive guides, or any detailed information that Codex should reference while working.

### assets/
Files not intended to be loaded into context, but rather used within the output Codex produces.

**Examples from other skills:**
- Brand styling: PowerPoint template files (.pptx), logo files
- Frontend builder: HTML/React boilerplate project directories
- Typography: Font files (.ttf, .woff2)

**Appropriate for:** Templates, boilerplate code, document templates, images, icons, fonts, or any files meant to be copied or used in the final output.

---

**Not every skill requires all three types of resources.**
