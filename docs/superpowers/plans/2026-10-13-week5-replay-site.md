# Week 5: Replay Website Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Front-end tasks also REQUIRE the `frontend-design:frontend-design` skill.

**Goal:** A static website, servable from GitHub Pages, that replays every recorded incident. It shows the alert, each step the agent took with what each tool showed it, the verdict, the cited evidence with grounded/distinctive badges, the heuristic's answer next to it, and the correct answer. Failures are shown as plainly as wins.

**Architecture:**
- `rootcause/site.py` turns run records, scenario truth and the report figures into `site/data/*.json`.
- A hand-written static front end (`site/index.html`, `site/incident.html`, `site/assets/{style.css,app.js}`) renders that JSON in the browser. There is no build step, no framework and no bundler.
- `python -m rootcause site` regenerates the data whenever more runs land.

**Tech Stack:** Python 3.11 for the data builder, plain HTML/CSS/JS (ES modules), and Google Fonts. Inline SVG draws the sparklines and nothing else.

**Spec:** `docs/superpowers/specs/2026-09-25-rootcause-design.md` §11: the replay website is the project's showpiece, it includes failures, and it is static. The data comes from `data/runs/<solver>/*.json` (records with `report`, `score`, `evidence_check` where present, `transcript`, `messages`, usage), `snapshot.load_truth`, and `scenarios/*.yaml`.

## Global Constraints

- **The site is post-hoc, so it may show ground truth.** It must never be served to an agent or the MCP server, and nothing in `rootcause/` other than `site.py` may import it.
- **No secrets.** The data builder copies only record fields from an allow-list. It never copies `.env`, file paths, or the raw `messages` (system prompts are fine to show, but are not copied; keep the payload small).
- **Size.** Tool outputs are truncated to 3,000 characters per step in the site data. A note says when truncation happened. Total `site/data` stays under 15 MB.
- **Static only.** The pages must work from `python -m http.server` in `site/` and on GitHub Pages under a sub-path. All URLs are relative, with no absolute `/` paths.
- **Accessibility floor.** The site is responsive down to 360 px wide, with visible keyboard focus. It respects `prefers-reduced-motion`, keeps text contrast at or above WCAG AA, never encodes correct/wrong by colour alone (an icon or word goes with every colour), and has semantic headings and tables.
- Commit messages end with: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`

## Design direction (decided; implementers follow it)

**Subject and job:** a flight-recorder replay of an AI agent's incident investigation, for engineers and recruiters. Its job is to show honestly where the reasoning found the cause and where it didn't.

**Palette.** Cool and instrument-like, deliberately avoiding cream/terracotta, black/acid-green and the SaaS card kit.

| Token | Hex | Use |
|---|---|---|
| `--paper` | `#EDF0F2` | page background (cool instrument grey) |
| `--ink` | `#16263A` | text and rules (navy ink, not near-black) |
| `--muted` | `#5B6B7D` | secondary text |
| `--cause` | `#2350C8` | the true cause and cause markers (cobalt) |
| `--hit` | `#0B7A62` | correct (teal), always with a ✓ glyph or the word |
| `--miss` | `#B0283F` | wrong (carmine), always with a ✗ glyph or the word |
| `--trace` | `#C47A12` | sparklines and the "after the alert" region (amber, used sparingly) |

**Type.** Archivo for display (headings, scoreboard numbers, using its width axis: condensed for dense tables, normal for headings). Atkinson Hyperlegible for body text. Tabular numerals in the tables. Sentence case everywhere. **No ALL-CAPS eyebrow labels, no middle-dot meta strings, no "→" on links.**

**Layout.**
- **Index:**
  1. The headline question, in Archivo at about 3.2 rem: "Can an LLM agent find what broke, better than a one-line rule?"
  2. One plain sentence on what this is.
  3. The scoreboard as the hero: a table of 20 incident rows × solver columns. Each cell holds a hit/miss glyph for every run (e.g. ✓✓✗✓✓), with the per-category accuracy in a footer row. Held-out rows are marked with "held out" in text. Each row links to its incident page.
  4. The two report figures.
  5. A short "how it works" list.
  6. Honest limits.
- **Incident page, two columns on desktop:**
  - **Left (reading width ≤ 72ch):** the alert as a pull quote, then the investigation as an ordered list of steps (the steps really are a sequence, so step numbers are appropriate). Each step shows the tool name and arguments in a compact line, and a rendering of the output: `top_changes` and `service_health` as small tables, `service_map` as a caller → callee table with stopped edges marked, and `get_metric` as an inline SVG sparkline with the alert at t=0 drawn as a vertical rule and the after-alert region tinted `--trace`. Traces and logs render as compact text blocks.
  - **Right (sticky):** the verdict panel showing the agent's ranked causes against the true cause (cobalt), the hit/miss word, confidence, and the heuristic's answer. Below it, the evidence list with "grounded" and "distinctive" badges.
  - **Above the columns:** a run picker (run 1–5) and a solver picker (v0, v1, ablations that have records).
- **The one motion moment:** a "Replay" button reveals the steps one at a time, about 600 ms apart, ending by revealing the verdict. With `prefers-reduced-motion`, everything shows at once. There are no other entrance animations.
- **Alignment:** left-aligned text. Tables are left-aligned, apart from numbers, which are right-aligned.

**Principle:** the data is the decoration. The only bold element is the scoreboard. Everything else is quiet: thin navy rules, generous whitespace, no shadows, and border-radius only on the run and solver pickers.

## File Structure

```
rootcause/site.py          build(out_dir=ROOT/"site", runs_dir=RUNS_DIR) -> Path; CLI `site`
rootcause/cli.py           + `site` command
site/index.html            scoreboard page (static shell; JS fills it from data/index.json)
site/incident.html         replay page (?id=<scenario>&solver=<name>&run=<k>)
site/assets/style.css      tokens + components (the design direction above)
site/assets/app.js         ES module: load JSON, render index / incident, replay control, sparklines
site/data/index.json, site/data/incidents/<id>.json, site/figures/*.png   (generated)
tests/test_site.py
```

---

### Task 1: Site data builder

**Files:** Create `rootcause/site.py` and `tests/test_site.py`. Modify `rootcause/cli.py`.

**Interfaces:**
- `site.build(out_dir=config.ROOT / "site", runs_dir=evaluate.RUNS_DIR, solvers=report.SOLVER_ORDER) -> Path` writes:
  - **`data/index.json`:** `{"generated": ISO date, "solvers": [names with records], "categories": [...], "incidents": [...]}`.
    - Each incident is `{"id", "category", "heldout": bool, "alert", "truth": [{"accept": [...], "fault_type"}], "results": {solver: [correct per run, ordered by run]}}`.
    - The file also holds `{"summary": {solver: [summarise rows for split "all"]}}`.
  - **`data/incidents/<id>.json`:** `{"id", "category", "heldout", "alert", "truth", "runs": {solver: [run...]}}`. Each run is:
    ```
    {"run", "verdict", "causes", "confidence", "score", "evidence": [{"item": <evidence item>, "grounded", "distinctive"}],
     "steps": [{"tool", "args": <parsed dict or raw string>, "output": <parsed JSON or text>, "truncated": bool}],
     "requests", "prompt_tokens", "completion_tokens", "parse_error", "error"}
    ```
    - Heuristic runs have no steps.
    - Evidence pairs `report.evidence[i]` with `evidence_check.items[i]` when present; otherwise grounded and distinctive are null.
  - **`figures/`:** copies of `docs/results/figures/*.png` if they exist.
- Truncation: any step output longer than 3,000 characters is cut to 3,000 and marked `truncated: true` (and is then always a string).
- CLI: `python -m rootcause site` prints the output path.

- [ ] **Step 1: Write the failing tests** (`tests/test_site.py`). Build from a tmp `runs_dir`:
  - a heuristic record;
  - two agent-v1 records for one scenario (one with a huge tool output and evidence_check);
  - a monkeypatched `scenarios.load_all` and `config.HELDOUT`;
  - a fake truth via a monkeypatched `snapshot.latest_rows` / `snapshot.load_truth`, or tmp snapshot dirs with `truth.json`.

  Assert:
  - the index has the incident with `results["agent-v1"] == [1.0, 0.0]` in run order, and `heldout` is set correctly;
  - the incident file has steps with a parsed `args` dict;
  - the huge output is truncated to 3,000 characters with `truncated: true`;
  - evidence is paired with grounded and distinctive;
  - no key named `messages`, `path` or `code` appears anywhere in the written JSON (walk it recursively);
  - building twice gives byte-identical files apart from `generated`.
- [ ] **Step 2: Run them to verify they fail** (`ModuleNotFoundError: rootcause.site`).
- [ ] **Step 3: Implement `rootcause/site.py`.**
  - Reuse `evaluate.load_records`, `evaluate.summarise`, `scenarios.load_all`, `snapshot.latest_rows`, `snapshot.load_truth`, `config.HELDOUT` and `report.SOLVER_ORDER`.
  - Read the truth from each scenario's latest snapshot. If a scenario has no snapshot, fall back to the YAML `truth`.
  - Write JSON with `sort_keys=True, indent=None, separators=(",", ":")`.
  - About 120 lines.
- [ ] **Step 4: Wire the CLI** and add `site/data/` and `site/figures/` to `.gitignore`. They are generated; publishing copies them in (Task 4).
- [ ] **Step 5: Run the full suite** with `-W error`, then commit with the message "Add replay-site data builder (index + per-incident JSON from run records, truncated, allow-listed)".

---

### Task 2: Index page (scoreboard)

**Files:** Create `site/index.html`, `site/assets/style.css` and `site/assets/app.js` (the index part).

**Acceptance (checked by the controller in the in-app browser at 1280 px and 375 px):**
- The page loads `data/index.json` with a relative fetch and renders:
  - the headline and the one-sentence intro;
  - the scoreboard table (rows are incidents grouped by category in the order easy, cross-service, silent, noisy, two-fault, control; columns are solvers with records). Each cell is a run strip of ✓/✗ glyphs with an accessible label ("agent-v1: 3 of 5 runs correct"). Held-out rows show "held out" as text;
  - a per-category accuracy footer from `summary`;
  - both figures with alt text;
  - "How it works" (4–5 short items) and "Honest limits" (3 items, matching the README).
- Each incident row links to `incident.html?id=<id>`.
- **Empty and failed loads:**
  - If `index.json` is missing, show "No results yet. Run `python -m rootcause site` to generate them." as plain text.
  - A solver with no records doesn't get a column.
- **Design:** it follows the Design direction section exactly (tokens, fonts, no listed tells). At 375 px the scoreboard scrolls horizontally inside its own container with the first column sticky, and the page never overflows horizontally.
- **Commit:** "Add replay-site scoreboard page".

---

### Task 3: Incident replay page

**Files:** Create `site/incident.html`. Extend `site/assets/app.js` and `style.css`.

**Acceptance (checked by the controller in the browser):**
- **Query and pickers:** the page reads `?id=&solver=&run=`, defaulting to the first agent solver with records and run 1. Changing the solver or run picker updates the URL with `history.replaceState` and re-renders without reloading.
- **Rendering:** the alert is shown as a pull quote. The steps are an ordered list, with per-tool renderers:
  - `top_changes`, `service_health`: a table (service, signal, before, after, change);
  - `service_map`: a caller → callee table, with stopped edges marked "stopped" in text;
  - `get_metric`: an inline SVG sparkline (width 100%, about 48 px high) with a vertical rule at t=0 and the t ≥ 0 region tinted `--trace`, plus min/max labels;
  - `search_traces`, `search_logs`, `get_trace`, `list_services`: compact definition lists or pre blocks;
  - unknown tools and truncated outputs: a pre block plus a "truncated" note.
- **Verdict panel (sticky on desktop):**
  - the agent's causes (ranked) with ✓ against the accepted set, and the true cause in cobalt;
  - "correct", "partly correct" (two-fault 0.5) or "wrong", in words and colour;
  - confidence;
  - the heuristic's answer for the same incident;
  - the evidence list with grounded/distinctive badges (words, not colour alone), with "not checked" for null.
- **Replay button:** reveals the steps one by one, about 600 ms apart, then the verdict. "Show all" reveals everything at once. Under `prefers-reduced-motion` the button just shows everything.
- **Failure cases:**
  - an unknown id shows "No incident called <id>. Back to the scoreboard." with a link;
  - a solver with no runs for this incident shows "This solver has no recorded runs for this incident yet.";
  - a `parse_error` or `error` run is shown with that message, not hidden.
- **Commit:** "Add incident replay page with per-tool renderers, sparklines and verdict panel".

---

### Task 4: Publish and document (controller)

- [ ] Run `python -m rootcause report`, then `python -m rootcause site`, then serve with `python -m http.server -d site 8000`. Check every page in the in-app browser at 1280 px and 375 px, with keyboard tab order, reduced motion, and an unknown id. Fix anything with a test or a commit.
- [ ] README: add a "Replay site" section with a screenshot and how to publish. GitHub Pages can serve `site/` from a `gh-pages` branch: build, copy `site/` (including the generated data) into the branch, and push. Publishing waits until the user creates the GitHub repo; ask before pushing anywhere.
- [ ] Commit.

**Week 5 is done when** the site regenerates from records with one command, shows every incident × solver × run including failures, meets the accessibility floor, and the README explains it with a screenshot.
