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

Navigation is **Overview**, **Workflow runs**, **Jobs** and **Tools**, with
**Galaxy accounts** (administrator only), **Galaxy server** (when authorized)
and **Status** in a secondary group. Status carries no report controls.

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
run from their start to now and say "(so far)". The resolved dates are always
printed under the buttons, so a label is never ambiguous.

Users pick an inclusive last day; the API boundary is exclusive and the
conversion happens internally. Period amounts use cost accrued *within* the
period, including failed attempts and running work — never a completed-job
total substituted for "what did I spend yesterday".

## Words and money

| Internal value | What the user reads |
| --- | --- |
| `additional` basis | Estimated run compute cost, with "Compute started for your tool and workflow runs. Your already-running Galaxy server is shown separately." |
| `allocated` basis | Resource allocation estimate, with its own explanation; unavailable by design for work on the Galaxy server |
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
then the tool steps, child workflows counted once, reused outputs and any steps
still missing cost data. A job's detail leads with its own cost, an
explanation in ordinary language, the resource it used (with a retry's shared
charge stated once), and its attempts. Galaxy's record of an execution a
provider also observed is not listed as a second attempt. The jobs table
calls a job's creation time **Submitted**, because Galaxy creates a job before
it starts running.

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
start, duration and workflow jobs, then steps and child workflows. It does not
cover the page: any press outside it closes it, a press on another run swaps
it, and Escape or the close button returns focus to where it was opened.
A job opened from a step uses the same drawer. Workflow version and Galaxy
history are not shown.
