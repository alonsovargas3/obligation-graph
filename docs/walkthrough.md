# Two-minute walkthrough: recording guide

## Names used on screen

The page and the tools use document IDs, not nicknames:

| Spoken name | ID on screen | Document |
|---|---|---|
| the base lease | `constantcontact-2011-ex1041` | 2011 Datacenter Lease, 55 Middlesex Turnpike, Bedford MA |
| the First Amendment, 1A | `constantcontact-2012-ex101` | 2012 amendment: Suite 418A expansion, new SLA table |
| the Third Amendment, 3A | `endurance-2017-ex106` | 2017 amendment: Suite 409 extended two years |
| the Carbonite lease | `carbonite-2014-ex1024` | 2014 Turn Key Datacenter Lease, Chandler AZ, heavily redacted |

## Before you record (about 3 minutes)

1. **Start the review page.**
   - In a terminal, run `cd ~/Dev/msa-mcp && make ui`. If you're asked "Run where?", choose Local.
   - Wait for `Obligation Graph UI on 127.0.0.1:8765`.
   - Leave the terminal open.
2. **Open the page.** In Chrome, open `http://127.0.0.1:8765`.
   - Zoom to 110% so text reads well on video.
   - Set the window to about 1440 px wide.
3. **Set up Claude Desktop.**
   - Open a **new chat**.
   - In Settings, then Connectors, then obligation-graph, set the 4 tools to **Always allow**. This keeps approval prompts out of the recording. You can switch them back afterwards.
4. **Open the README.** In a second Chrome tab, open the repository's README on GitHub. Or open `README.md` in your editor with Markdown preview on.
5. **Do a dry run.** Rehearse the clicks below once. Then reload the page (Cmd-R) so it starts clean.

## Recording script

### 0:00 to 0:15: The idea (README tab)

- **Show:** the top of the README, with the "The invariant" heading visible.
- **Say:** "Obligation Graph turns public data center contracts into obligations that each point to the exact clause they came from. The rule: never state a term the system cannot point to."

### 0:15 to 0:40: A redacted clause (review page, top half)

1. Switch to the review page tab. It shows a blue header, **Obligation Graph**, and a grey note: "525 pending obligations ...".
2. In the **Obligations** panel, set the filters:
   - **Agreement** (second row, left): choose `carbonite-2014-ex1024`.
   - **Status** (first row, right): choose `redacted`.

   The table shrinks to **17 rows**, each with an orange `[REDACTED]` tag.
3. Click the **second row**: payment, `$[***] per month for the period commencing on the Commencement Date ...`.
4. Point to the **Clause** panel on the right. It shows the verbatim text, **Section 8, Page 17**, the character range, the `[REDACTED]` explanation, and "Agreement site: 2121 South Price Road, Chandler, Arizona".

- **Say:** "Every row is a quoted clause with its section, page and exact character range. This lease redacts its rent. The system keeps it redacted and never guesses a number."

### 0:40 to 1:10: An amendment checked against the lease (review page, bottom half)

1. Scroll down past the obligations table to the panel titled **Change orders**.
2. Open the **Change order** dropdown, which shows "Select a change order...". Choose `endurance-2017-ex106 (amends constantcontact-2011-ex1041)`. That is the Third Amendment.
3. Read the two status lines that appear:
   - "Stored, verified report for endurance-2017-ex106 (no analysis performed)."
   - "Chain: constantcontact-2011-ex1041 (base) -> constantcontact-2012-ex101 (prior_amendment) -> endurance-2017-ex106 (change_order)".
4. Scroll past the gate table (you'll come back to it) to **Shifted dates (1)**. It shows two boxes side by side:
   - **Old clause:** "scheduled to be surrendered to Landlord on June 30, 2018".
   - **New clause:** "expiring June 30, 2020".

   Underneath: "old: 2018-06-30 new: 2020-06-30 delta: 731 days".
5. Scroll a little more to **Price changes (3)**. The first shows `$35,596.80/month` under **New clause**, "No old-side quote is stored for this finding" under **Old clause**, and the period "July 1, 2018 – December 31, 2018" under **Context**.

- **Say:** "Amendments are checked against the agreement they change. The Third Amendment moves the Suite 409 surrender date from June 30, 2018 to June 30, 2020, and both dates are cited. Its rents are new amounts with no prior rate, because the amendment they replace was never filed."

### 1:10 to 1:30: Decision gates (review page, same panel)

1. Scroll back up within **Change orders** to **Gate decisions (gated run)**. Its summary line reads "Gates: 6 questions, 4 checks ran, 2 skipped."
2. Point to the two rows with the green **check skipped** tag:
   - `touches_guarantee`: answer **no**, backend classifier / haiku.
   - `touches_sla`: answer **no**, backend classifier / haiku.
3. Point to the line under the table: "A gate may skip a check; it can never suppress a finding."

- **Say:** "Six yes or no questions decide which expensive checks run. Here the guarantee and SLA checks were skipped after three unanimous answers from a small model. A separate run with every check confirms nothing was missed."

### 1:30 to 1:50: Ask it as an agent (Claude Desktop)

1. Switch to Claude Desktop, in the new chat you prepared.
2. Type: **What do we owe the landlord at 55 Middlesex Turnpike?** and press Enter.
3. You'll see a "Used Obligation graph" or "Get obligations" line. Then the answer lists the base rent schedules and additional rent with section references, and says that every item is pending.

- **Say:** "Agents ask the same graph over MCP. The answer comes back with its clauses, and it says plainly that none of these has a computable due date yet."

### 1:50 to 2:00: Reproducible numbers (README tab)

- **Show:** switch to the README and scroll to **Results**, so the first table (Extraction) is visible.
- **Say:** "Every number here is generated from committed results, and a fresh clone reproduces them without an API key."

## After recording

- **Stop the review page:** press Ctrl-C in the terminal running `make ui`.
- **Send the link:** send the video link, for example from Loom or an unlisted YouTube upload. The coordinator replaces "link coming soon" in the README with it.

## If something looks different

- **The table is empty or shows an error:** stop `make ui`, run `git pull` in `~/Dev/msa-mcp`, and start it again. The fix for that bug is on `main`.
- **"Shifted dates" shows a garbled old clause:** you're on an older copy. Pull `main` and restart `make ui`.
- **Claude Desktop shows no obligation-graph tools:** fully quit with Cmd-Q and reopen. The server needs `~/Dev/msa-mcp/data/graph.db` to exist.
