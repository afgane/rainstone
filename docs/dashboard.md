# Dashboard experience

The dashboard is built around three questions a scientist actually asks: what
did my work cost in a period, what did this workflow run cost, and which tools
account for most of it. Everything needed to answer them is on screen by
default; advanced reporting stays available but out of the way.

## Layout

One left sidebar carries navigation and the few controls a normal answer needs:
period buttons, one search box worded for the current page, and a collapsed
**More filters** section. There is no filter panel above the results and no cost
basis selector in the content area. A page that has filters of its own shows
them in a tinted section under Period, apart from these app-wide controls
(see [Workflow runs](#workflow-runs)). The sidebar scrolls on its own when it is
taller than the window.

Navigation is **Overview**, **Workflow runs** and **Jobs**, with **Galaxy
accounts** (administrator only), **Galaxy server** (when authorized) and
**Status** in a secondary group. Status carries no report controls. The former
Tools page is the Jobs page's By tool chart; `view=tools` links open it.

Advanced filters that are active remain visible as removable chips while the
section is collapsed, so a hidden selection can never quietly change an easy
answer. Below 1000px the sidebar becomes a drawer behind a Filters button that
shows the active filter count. Report state stays in the URL, so a link
reproduces a view, and browser history, keyboard operation and focus
restoration all work.

## Periods

Period buttons are calendar periods in the reporting timezone, not rolling
windows: yesterday is the preceding calendar day, last week the previous Monday
to Sunday, last month the previous calendar month. "This week" and "this month"
run from their start to now. The resolved dates are always
printed under the buttons, so a label is never ambiguous.

Users pick an inclusive last day; the API boundary is exclusive and the
conversion happens internally. Period amounts use cost accrued *within* the
period, including failed attempts and running work — never a completed-job
total substituted for "what did I spend yesterday".

## Words and money

| Internal value | What the user reads |
| --- | --- |
| `additional` basis | Estimated run compute cost, with "Compute started for your tool and workflow runs. Your already-running Galaxy server is shown separately." |
| `allocated` basis | Not offered in the UI. It differs from run compute cost only for work on the Galaxy server, where it is unavailable by design; the API still accepts it |
| `current_launch` | Galaxy server compute cost: $X/hour while running and total since launched, with launch time and cutoff, in a quieter section |
| `known_zero` | $0 extra compute · Used your Galaxy server |
| `partial` / `unpriced` | Cost incomplete / Price unavailable, each with a reason |
| `in_progress` | Still running, only for queued or running work |
| `unavailable` | Cost data unavailable, for finished work whose evidence was not collected |
| `not_started` | Not run yet, for new or paused work |
| root invocation | Workflow run |
| `ok` / `error` / scheduling states | Completed, Failed, and a run status derived from the run's executions |
| `gcp_batch` / `kubernetes` | Dedicated cloud compute / Your Galaxy server, only where the resource relationship is established |
| full Tool Shed identifier | Tool name and version, with the full identity in details |

Amounts render to two decimals, show "less than $0.01" rather than rounding a
real cost to zero, and keep "Not available" distinct from `$0.00`. Exact decimal
values remain in details and CSV. Galaxy's database stores tool IDs rather than
display names, so the readable name is derived from the identity and the full
identity always travels with it; two tools with similar names stay
distinguishable.

## Runs versus periods

A workflow run's headline is its **run total**: the whole run, whatever period
is selected. When the selected period covers only part of it, the period share
is shown beside it rather than replacing it. The period selector scopes which
runs are listed: the runs that used compute inside it. Jobs whose cost evidence
has no usable timing are left out of every period's totals, counts and
rankings; the overview says how many there are and the jobs page lists them in
a separate, collapsed section. A run whose jobs all lack timing therefore stays
out of a dated period.

Opening a run leads with the run total and its completion and coverage status,
then where its cost went, the jobs, child workflows counted once, reused
outputs and any steps still missing cost data. Galaxy's record of an execution
a provider also observed is not listed as a second attempt. The jobs table
calls a job's creation time **Submitted**, because Galaxy creates a job before
it starts running.

## Job details

A job opens in the same drawer as a run, with the same shell, scrolling, Back
link and restoration. It leads with the tool's name and its state in words, and
the whole job's estimated compute cost as the largest figure. When the selected
period holds only part of the job, that share is said in a sentence beside it,
never added to it. A complete estimate needs no further sentence; a missing,
partial or provisional cost keeps its reason next to the figure, and work on
your Galaxy server says it added no compute charge.

In order, the drawer then shows:

- **Timing**: when the job was submitted, how long it waited to start
  (*Waited to start*) and how long the tool ran (*Ran for*). The wait is
  everything between submission and the tool starting, so it holds queueing,
  setup or both; nothing says which. A running job is timed up to the snapshot
  ("so far"), a job that has not started shows none, and an unavailable
  duration is a dash, never zero. A failed job adds its recorded exit code.
- **Timeline**: a shallow line from submission to start to finish, drawn at
  real relative times, with every event and its time listed beneath it as the
  text alternative. Several runs, or times that contradict each other, are
  listed without a span.
- **Compute**: where it ran (the verified environment), the machine and how it
  was bought, the machine's own size (vCPUs, memory and any GPUs it comes
  with, for the machine types we have published specifications for, kept
  apart from what the job asked for), and whether its runs shared it. For a
  machine with GPUs, the cost estimate says its price includes them.
- **Resource use**: two flat bars, each a measurement against what was
  requested, with the numbers beside them. *Average CPU use* is the CPU time
  the run used over how long the tool ran; *Peak memory use* is the most memory
  it held at once. Neither is an efficiency score, and there is no peak CPU or
  history, because none is collected. A request is a reference, not a limit: use
  above it stretches that row's bar and marks the request, and shows the real
  percentage. A bar is drawn only when the job's counters and its request
  describe the same run. A retried job, a running job, a job on your
  Galaxy server, a request that may cover more than the tool, or a missing
  request each say so instead, and a measurement that was not recorded is never
  shown as zero.
- **Runs**, only when there is more than one: retries, or parallel work, each
  opened in place for its exact times, exit code and machine. A summary says
  how the job ended after how many runs, or that they ran in parallel. Opening
  one changes nothing above it.
- **How this cost was estimated** and **Technical details**, both closed. The
  first explains the method and what compute-only leaves out, and each
  machine's share when there were several (parts of the cost above, not more
  cost). For one machine it also lines up the tool's run against the machine's
  lifetime on one scale; the machine can be held before and after the tool
  runs. The second holds identifiers, the recorded metrics with their units, and
  the cost lines' own wording.

## Jobs

The Jobs page reports every job in the period, in a workflow or run on its
own, so its total is the Overview headline for the same filters. Two cards
give the period's cost (recorded so far, with how many jobs still need cost
data) and its workload: jobs by status, and how many tools ran. The sidebar's
search is "Find a job", searching by tool.

**By tool.** One row per tool, every version of it together: a Tool Shed
tool's versions share a row, and any other tool keeps its exact identity, so
two tools with the same readable name stay apart (their identity is shown
under the name). The twelve costliest tools are shown, with the rest summed in
one box, and "Show 12 more tools" and "Show all" reveal them without changing
the scale. "Find a tool" finds a row anywhere in the ranking; it is not a
report filter and changes neither the totals nor the list. Tools that added
$0 on the Galaxy server, tools whose jobs recorded no cost, and tools with no
cost data yet sit in collapsed sections below, counted.

**Over time.** Columns follow the shared rule: hours for one day, days up to
92 days, weeks beyond. There is no interval selector. Every column of the
period is drawn, a week or month in progress included; a column not reached
yet cannot be opened. A column whose jobs have no known cost shows a dashed
outline at the baseline rather than a $0 bar.

**Status.** Both charts stack each tool's or column's cost by the job's
recorded status: completed solid, still running and failed with the run
chart's textures, any other status cross-hatched. A piece's size is cost, not a
count of jobs; tooltips and the table alternative give both. The colours are
each job's status in this report, not its status at that time.

**Drawers.** Selecting a tool opens its drawer: its cost in the period, its
jobs by status and its versions, and the five jobs contributing most to its
cost, chosen from every matching job. Jobs with incomplete cost data are not
ranked and are counted beside the ranking. A server-only tool lists recent
jobs instead, and a tool with no complete costs says why it has no ranking.
"Show N jobs" under the list is the one action that filters the page: it
closes the drawer and narrows the figures, charts, list and export to that
tool. Selecting a column opens that interval's jobs, highest cost in the
interval first, a page at a time, without filtering anything. Rows show only
the job's cost inside the drawer's scope beside its whole run's duration, and
no job numbers. A job opened from either drawer leads back to it, also after
a reload, and its details name the interval when it came from one.

**The list.** Costliest first by default; each row gives the tool, the
workflow run that holds the job ("Part of RNA-seq QC", "and 1 other run" when
several do; "Individual tool job", or "Workflow link not recorded" when the
record cannot say), when it was submitted, its status, how long it ran, and its
cost in the period with where it ran. Server jobs read "$0 extra". The run's
name opens that run; anywhere else on the row opens the job.

## Time and freshness

Every date and time is shown in the report's timezone, not the browser's, so a
run always appears under the day it is counted in. Report pages end with when
collection last reached every source ("Collected through", marked stale when
any source is) and, separately, when costs were calculated. The Galaxy server
section shows when the server was actually observed, or says that no server
observations are available; it never presents the selected period as observed
coverage. An imported snapshot is labelled as such in the masthead, not as demo
data.

## Workflow runs

The page answers "what did my workflow runs cost?" with two figures, one chart
and one list, all describing the same runs.

**Figures.** The first card is the period's cost of every workflow run,
computed on the server. It is never a sum of the rows loaded so far, so
"Show more" cannot change it. It says which workflow it covers ("All
workflows", the chosen one, or "Matching workflows" when other filters apply),
says "recorded so far" when some runs still need cost data, and says when jobs
shared by runs are counted once. The second card counts the runs, splits them
by outcome and says how many workflows they span, or how many runs the period
holds when a filter narrows them. Both cards keep the same lines in every
state, so choosing something never moves the page.

**Why the total is lower than Overview.** People also run individual tools,
and only Overview counts those. With the same period and no page filters,
Overview equals this total plus the cost of jobs run outside a workflow. That
difference is not a discrepancy.

**Filters for this page.** Workflow, Outcome (with counts), search, and
removable chips for a chosen time window and for a group of smaller runs. Every
one of them narrows the figures, the chart and the list together: what does not
match is removed, not dimmed. The choices in the sidebar always show what each
would select if its own selection were cleared, so an option is never lost by
choosing another. Nothing outside this section is a page filter; the period
above applies everywhere.

**Chart.** *By workflow* draws a bar per workflow, made of one block per run
and sized by cost. *Over time* draws a column per hour (one day), day
(up to 92 days) or week (Monday start), with a block per run. A block that
would be smaller than a few pixels joins one grouped segment; selecting it
picks exactly those runs. Failed runs are striped one way and running runs the
other, so colour is never the only signal. Below the chart, a strip shows the
chosen workflow's runs at their own scale with the range of their whole-run
totals, and says how many runs the range leaves out (still running, or missing
cost data). Blocks are pointer shortcuts; the workflow labels, columns and
grouped segments are buttons, the run list is the accessible path, and "Show
this chart as a table" lists the same figures.

A job shared by several runs is drawn under one of them, so the chart adds up
to the card. A run's own cost and whole-run total still count every job it
contains; those figures do not add up across runs that overlap.

**List.** One row per run: start time, duration, outcome, job count and the
run total ("Cost so far" while running), with the period share beside it when
it differs. Sort by newest, oldest, cost or duration. "Show more" appends the
next runs.

**Run details.** Selecting a block or a row opens a drawer at the right: status,
start, duration and workflow jobs, then the cost breakdown, the jobs and child
workflows. It does not cover the page: any press outside it closes it, a press
on another run swaps it, and Escape or the close button returns focus to where
it was opened. A job opened from the drawer uses the same drawer, and Back
returns to the run as it was left. Workflow version and Galaxy history are not
shown.

**Cost breakdown by tool.** One hundred squares, twenty across, show where the
run's whole cost went; each square is about 1% of the cost shown. Repeated jobs
of one tool are one part ("wig_to_bigWig ×3"), the parts that matter are named,
and the rest are pooled as *Other*, which always lists everything it holds. The
squares are flat, equal and rounded, and a small diamond takes the place of one
square between two tools, so the grid stays aligned and the gap looks
intentional. The squares are the whole picture: nothing is listed under them.
Until one is chosen, a hint holds the place where its details will open, so the
chart never moves. Choosing a square opens that tool's cost and jobs there and
nowhere else. A part too small to have a square of its own is listed under the
chart so it can still be chosen. For the keyboard and screen readers each part
is also a button, hidden from view; focusing one lights its squares. A hover
shows a tooltip that follows the pointer above it, and Escape dismisses the
tooltip before it closes the drawer. Colour marks where the work ran, never
which tool. Shares are of the cost known, and say "so far" or "recorded" when
the run is running or missing cost data. Work with no known cost never gets a
share, and a run whose jobs added nothing shows no squares. The open part is in
the address (`detail_part`, and `detail_member` for a member of *Other*),
replaces rather than adds a history entry, and is cleared with a notice if the
run no longer has it. The drawer scrolls without showing a scrollbar, so its
content does not shift when one would appear.

**Jobs.** Every job of the whole run, once, grouped by where it ran: Dedicated
cloud compute, Your Galaxy server, other verified places, several places, then
Not established. A group's heading carries its cost on the same line, and says
beneath it what that cost leaves out. Each row is one button with the tool, a
state icon, the duration (seconds kept) and, where the group states one, the
cost. The server's jobs are said once to have added no compute charge and carry
no cost column. Repeated tools stay separate rows.

## Overview

Two cards sit at the top, the same shape as on Workflow runs. The left is the
cost summary: the period's estimated compute cost, "recorded so far" when some
jobs still need cost data, and what the measure covers. The right is the
workload, in two shaded blocks side by side: the jobs that ran, with their
outcomes (completed, failed, running), and the workflow runs, with how many
workflows they belong to. The job count covers every job, whether it ran in a
workflow or on its own. Notices that need a word or an action (jobs with no
usable timing) sit under the cards.

The cost chart below is dated like the Workflow runs Over time chart: one
column per hour (one day), day (up to 92 days) or week, every day of the period
named with its month, and a week or month still in progress drawn whole with
its coming days empty. Each column has at most two blocks: one for all the
workflow runs together, and one dotted block for jobs that ran outside any
workflow. Grouping the runs keeps a busy period readable; the Workflow runs page
splits them by workflow. The columns add up to the total on the left. Hovering
a block or a column says what it holds: cost, runs and jobs, and how many jobs
failed or are still running. Selecting the runs block opens the Workflow runs
page for that column's dates; selecting the individual jobs' block opens the
Jobs page for those dates. The columns themselves do nothing when pressed. The
chart's table alternative, collapsed under it, lists the same blocks with a
button to open each, and "View daily details" still leads to the per-day table.
