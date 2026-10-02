# Walkthrough: recording guide

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

Read the quoted lines aloud. The numbered steps are what to click and point to. The narration is about 520 words, roughly three and a half minutes at a relaxed pace; the final beat is optional.

### 1. Opening: what the system does (about 20 seconds)

1. Show the top of the README, with the "The invariant" heading visible.
2. Switch to the review page tab.

> "Contracts contain commitments that people need to track. Obligation Graph turns those commitments into structured records, while keeping each one attached to the exact contract language that supports it.
>
> The rule is simple: never state a term the system cannot point to."

### 2. Obligations and redacted rent (about 40 seconds)

1. Show the obligations table. The grey note above it starts "520 pending obligations ...".

> "Here's our list of obligations, 525 in this build. The graph connects them to their agreements and supporting clauses, so we can explore those relationships or ask an agent to retrieve them.
>
> Let's look at the Carbonite lease and filter to the redacted items."

2. In the **Obligations** panel, set **Agreement** (second row, left) to `carbonite-2014-ex1024` and **Status** (first row, right) to `redacted`. The table shrinks to **17 rows**, each with an orange `[REDACTED]` tag.
3. Click the **second row**: payment, `$[***] per month for the period commencing on the Commencement Date ...`.
4. Point to the **Clause** panel on the right: the verbatim text, **Section 8, Page 17**, and the `[REDACTED]` explanation.

> "Here's a payment obligation. When I click it, you can see the exact passage where that information came from. Notice that the rent amount is hidden in the original document. The system keeps it redacted rather than guessing a number."

Pause so the audience can read the source text. If you want a timing beat here, point to the row's **Due / timing** tag, `unresolved: recurring_schedule`, without adding a line.

### 3. Amendments: what changed (about 50 seconds)

1. Scroll down past the obligations table to the panel titled **Change orders**.
2. Open the **Change order** dropdown ("Select a change order...") and choose `endurance-2017-ex106 (amends constantcontact-2011-ex1041)`. Two status lines appear: "Stored, verified report for endurance-2017-ex106 (no analysis performed)." and the chain base -> First Amendment -> Third Amendment.

> "Now that you've seen how we get the information and where it comes from, let's look at what happens when an agreement changes.
>
> This is the Third Amendment. We're viewing a stored, verified report comparing it with the base lease and the earlier amendment available in the graph."

3. Scroll past the gate table (you'll come back to it) to **Shifted dates (1)**. Point to **Old clause** ("scheduled to be surrendered to Landlord on June 30, 2018"), then **New clause** ("expiring June 30, 2020").

> "Here's the old text, and here's the new text. The Suite 409 surrender date moves from June 30, 2018, to June 30, 2020. You can see the contract language supporting both dates."

4. Scroll to **Price changes (3)** and point to the first one: `$35,596.80/month` under **New clause**, "No old-side quote is stored for this finding" under **Old clause**.

> "Here's a new rent amount: $35,596.80 per month for July through December 2018.
>
> There's no prior rate shown because the referenced amendment containing that information wasn't filed. The system makes that gap visible rather than filling it in."

5. Scroll to **New obligations without a supersession (7)**: the surrender obligation and the Suite 409 rent lines, each with its quoted clause.

> "So you can see exactly what changed, and here are the updated obligations that result."

### 4. Gates: deciding which checks to run (about 35 seconds)

1. Scroll back up to **Gate decisions (gated run)**. Its summary reads "Gates: 6 questions, 4 checks ran, 2 skipped."
2. Point to the two rows tagged **check skipped**: `touches_guarantee` and `touches_sla`, both answered **no** by the classifier (haiku).

> "Here you can see which detailed checks ran and which were skipped. These gates help us decide which checks this amendment needs.
>
> Simple rules run first. Where those don't decide, a small model answers three times. We skip a check only after three unanimous 'no' answers. If there's disagreement, an error, or a timeout, we run the check anyway.
>
> For this amendment, the guarantee and SLA checks were skipped. We also tested it with every check turned on, and both runs produced the same findings."

Pause. The point to leave with the viewer: when in doubt, run the check.

### 5. Ask the agent (about 35 seconds)

1. Switch to Claude Desktop and open a **new chat**. In a reused chat Claude may answer from earlier results instead of calling the tool.
2. Type **What does the tenant owe the landlord under the 55 Middlesex Turnpike lease?** and press Enter. Use this third-person wording, not "What do we owe...": a question with "we" makes Claude Desktop check your personal context instead of answering about the lease.
3. Let the "Obligation graph: Get obligations" line and the answer appear before you speak.

> "Now I'm asking a question in plain English. The agent queries the same obligation graph we were just exploring.
>
> It can tell us what the contract requires, but it can't tell us a current balance, because it doesn't know what has been paid.
>
> Here are the rent obligations, and here are the contract references supporting them."

4. Point to one base-rent line and its section reference (for example "Prepaid rent ... (§10)").
5. Scroll to **Additional rent** and point to "Generator fuel: due within 30 days of each invoice (§3.5.4)".

> "Where the contract ties a payment to an event, like thirty days after an invoice, the agent shows that trigger from the lease. Where the documents don't give a computable date, it says so. Pending doesn't mean overdue."

Pause without reading the amounts aloud.

### 6. Closing (about 10 seconds)

> "Whether you click through the graph or ask in plain English, the obligations come back with the contract text supporting them. When information is missing, the system makes that visible."

### Optional final beat: reproducibility (about 10 seconds)

Switch to the README and scroll to **Results**, so the Extraction table is visible.

> "The numbers here come from committed evaluation results. A fresh clone can replay the recorded model calls and reproduce those results without an API key."

## Presenter reminders

- Show one example, point to its source, then pause.
- The change-order view retrieves a stored report; selecting it does not run fresh analysis.
- A skipped check was not performed. It does not mean the check ran and passed.
- "Both runs produced the same findings for this amendment" is the supported claim. Avoid "nothing was missed."
- Grounded citations verify source support; they do not guarantee complete extraction or perfect interpretation.
- Keep the due-date explanation general. Since wave 5, 5 obligations have a computed date bound, 132 are contingent on a quoted event, 132 are unresolved with a reason, and 256 state no deadline. Don't attribute a missing date to the Commencement Date without checking the clause.
- Claude may flag the base rent table ("Suite A drops by about 60% at month 25", identical figures from month 37) as a possible extraction error. Don't comment on it on camera. Section 8 of the filed lease states exactly those figures.
- Claude may label the suites "A/B/C". The lease names them Suite 1.5, 1.5.1, 1.5.2 and 1.14A; don't read the labels out.
- If you stumble, stop and restart the section instead of correcting yourself on camera.

## After recording

- **Stop the review page:** press Ctrl-C in the terminal running `make ui`.
- **Send the link:** send the video link, for example from Loom or an unlisted YouTube upload. The coordinator replaces "link coming soon" in the README with it.

## If something looks different

- **The table is empty or shows an error:** stop `make ui`, run `git pull` in `~/Dev/msa-mcp`, and start it again. The fix for that bug is on `main`.
- **"Shifted dates" shows a garbled old clause:** you're on an older copy. Pull `main` and restart `make ui`.
- **Claude Desktop shows no obligation-graph tools:** fully quit with Cmd-Q and reopen. The server needs `~/Dev/msa-mcp/data/graph.db` to exist.
