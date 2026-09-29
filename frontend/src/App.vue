<script setup lang="ts">
import { CircleDollarSign, Filter, RefreshCw } from "@lucide/vue";
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref } from "vue";
import {
  ADVANCED_FILTERS, ApiError, activeFilters, chartsNeeded, collectionCutoff, DEFAULT_RUN_CONTROLS,
  downloadExport, get, loadMoreRuns, loadReport, loadRunChart, NO_RUN_FILTERS, periodOf, queryString,
  stateFromUrl, urlQuery,
  type AdvancedFilter, type CostTimeline, type DailyItem, type Freshness, type GroupItem, type Infrastructure,
  type Invocation, type JobList, type Me, type ReportState, type RunsView, type RunStatus,
  type Status, type Summary, type View,
} from "./api";
import DetailDrawer from "./components/DetailDrawer.vue";
import OverviewPanel from "./components/OverviewPanel.vue";
import ReportSidebar from "./components/ReportSidebar.vue";
import PageFilters from "./components/runs/PageFilters.vue";
import RunsPage from "./components/runs/RunsPage.vue";
import ServerPanel from "./components/ServerPanel.vue";
import StatusPanel from "./components/StatusPanel.vue";
import ToolRunsPanel from "./components/ToolRunsPanel.vue";
import ToolsPanel from "./components/ToolsPanel.vue";
import { localDate } from "./chart/axis";
import { describePeriod, PERIOD_LABELS, todayIn, type PeriodId } from "./periods";
import { formatCost, formatDateTime, PRIMARY_MEASURE, RUN_SORTS } from "./vocabulary";

const TITLES: Record<View, string> = {
  overview: "Overview",
  runs: "Workflow runs",
  "tool-runs": "Jobs",
  tools: "Tools",
  daily: "Daily cost",
  users: "Galaxy accounts",
  server: "Galaxy server",
  status: "Status",
};

const state = reactive<ReportState>(stateFromUrl(location.search));
const summary = ref<Summary | null>(null);
const jobs = ref<Pick<JobList, "items" | "undated_items" | "total" | "limit">>({
  items: [], undated_items: [], total: 0, limit: 50,
});
const freshness = ref<Freshness | null>(null);
const me = ref<Me | null>(null);
const viewData = ref<unknown>(null);
// The view the page last drew, so a refetch of the same view can keep it on screen.
const renderedView = ref<View | null>(null);
const loading = ref(true);
const error = ref("");
const detail = ref<Record<string, unknown> | null>(null);
const detailKind = ref<"runs" | "tool-runs" | null>(null);
const detailId = ref("");
const detailLoading = ref(false);
const advancedOpen = ref(false);
const drawerOpen = ref(false);
const hoverRunId = ref("");
const loadingMore = ref(false);
const loadingChart = ref(false);
// A minimum height for the page while a narrower answer would otherwise make it jump; 0 for none.
const holdHeight = ref(0);
let detailOpener: HTMLElement | null = null;
let controller: AbortController | null = null;
let timer = 0;
let firstLoad = true;
// Each load or page fetch belongs to the report it started from; a result that
// arrives after the report has changed is dropped, never mixed into the new one.
let generation = 0;
let detailToken = 0;
// Runs and jobs opened from inside the drawer, so its back button can retrace them.
const detailTrail = ref<Array<{ kind: "runs" | "tool-runs"; id: string }>>([]);

const period = computed(() => periodOf(state));
const periodLabel = computed(() => (state.period === "custom"
  ? "the selected dates"
  : PERIOD_LABELS[state.period].toLowerCase()));
const filters = computed(() => activeFilters(state));
const overviewParts = computed(() => (Array.isArray(viewData.value)
  ? viewData.value as Array<{ items?: unknown[] }>
  : []));
const days = computed(() => (state.view === "daily"
  ? ((viewData.value as { items?: DailyItem[] } | null)?.items || [])
  : []));
const costTimeline = computed(() => (state.view === "overview"
  ? (overviewParts.value[0] as unknown as CostTimeline | undefined) ?? null
  : null));
const tools = computed(() => (state.view === "overview"
  ? (overviewParts.value[1]?.items || []) as GroupItem[]
  : ((viewData.value as { items?: GroupItem[] } | null)?.items || [])));
const runs = computed(() => (state.view === "overview"
  ? (overviewParts.value[2]?.items || []) as Invocation[]
  : []));
const runsView = computed(() => (state.view === "runs" && renderedView.value === "runs" && viewData.value
  ? viewData.value as RunsView : null));
const server = computed(() => (state.view === "server"
  ? viewData.value as Infrastructure | null
  : null));
const status = computed(() => (state.view === "status" ? viewData.value as Status | null : null));
const collection = computed(() => collectionCutoff(freshness.value));
const page = computed(() => Math.floor(state.offset / 50) + 1);
const openRunId = computed(() => (detailKind.value === "runs" ? detailId.value : ""));
// Refetching the runs page keeps the last picture, dimmed, instead of a skeleton,
// so nothing on the page moves while the answer changes.
const keepPrevious = computed(() => loading.value && runsView.value !== null);
const runSortChoice = computed(() => RUN_SORTS.find(
  choice => choice.sort === state.runSort && choice.direction === state.runDirection,
)?.id ?? RUN_SORTS[0].id);

function updateUrl(push = false) {
  const query = urlQuery(state);
  const current = new URLSearchParams(location.search);
  if (current.get("detail_kind") && current.get("detail_id")) {
    query.set("detail_kind", current.get("detail_kind")!);
    query.set("detail_id", current.get("detail_id")!);
  }
  history[push ? "pushState" : "replaceState"]({}, "", `${location.pathname}?${query}`);
}

async function refresh(push = false) {
  controller?.abort();
  controller = new AbortController();
  const mine = ++generation;
  // Refetching the page being read must not move the reader.
  const scrolledTo = renderedView.value === state.view ? window.scrollY : null;
  if (scrolledTo !== null) holdHeight.value = document.getElementById("main")?.offsetHeight ?? 0;
  loading.value = true; error.value = "";
  updateUrl(push && !firstLoad);
  try {
    const result = await loadReport(state, controller.signal);
    if (mine !== generation) return;
    // The totals, the charts and the list are committed together, so a new
    // total is never shown beside the previous filter's chart.
    summary.value = result.summary; jobs.value = result.jobs;
    freshness.value = result.freshness; me.value = result.me; viewData.value = result.view;
    renderedView.value = state.view;
    firstLoad = false;
    if (scrolledTo !== null) await keepPlace(scrolledTo);
  } catch (reason) {
    if ((reason as Error).name !== "AbortError" && mine === generation) {
      error.value = reason instanceof Error ? reason.message : "Unable to load reporting data";
    }
  } finally {
    if (mine === generation) loading.value = false;
  }
}

/**
 * Put the reader back where they were after a refetch. A narrower answer makes
 * the page shorter, and a browser clamps the scroll position to the shorter
 * page, which reads as a jump towards the top. When that would happen the page
 * is held tall enough, and the hold is dropped again on the next refetch.
 */
async function keepPlace(top: number) {
  holdHeight.value = 0;
  await nextTick();
  const main = document.getElementById("main");
  const wanted = top + window.innerHeight;
  if (main && wanted > document.documentElement.scrollHeight) {
    // A page shorter than the window reports the window's height, so the first
    // guess can fall short; the second pass measures what is left.
    holdHeight.value = main.offsetHeight + (wanted - document.documentElement.scrollHeight);
    await nextTick();
    const short = wanted - document.documentElement.scrollHeight;
    if (short > 0) {
      holdHeight.value += short;
      await nextTick();
    }
  }
  window.scrollTo({ top });
}

function resetRunPage() {
  Object.assign(state, NO_RUN_FILTERS, DEFAULT_RUN_CONTROLS);
}
/** A grouped selection describes the grouping that produced it, so any other change clears it. */
function clearGrouped() {
  state.maxRunAmount = ""; state.boundaryRunId = "";
}
function changeView(view: View) {
  if (state.view !== view) resetRunPage();
  state.view = view; state.offset = 0; drawerOpen.value = false; closeDetail(false, false);
  void refresh(true);
}
function changePeriod(id: PeriodId) {
  state.period = id; state.offset = 0;
  // A focus window and a grouped selection belong to the period they were made in.
  state.focusFrom = ""; state.focusTo = ""; clearGrouped();
  if (id === "custom" && !state.fromTime) {
    state.fromTime = period.value.fromDate; state.toTime = period.value.toDate;
  }
  void refresh(true);
}
function setField(key: string, value: string) {
  (state as unknown as Record<string, unknown>)[key] = value;
  clearGrouped();
  changeFilters();
}
function changeFilters() {
  state.offset = 0;
  updateUrl(false);
  window.clearTimeout(timer);
  timer = window.setTimeout(() => void refresh(true), 300);
}
function clearFilter(key: AdvancedFilter) {
  (state as unknown as Record<string, unknown>)[key] = "";
  clearGrouped();
  void refresh(true);
}
function clearFilters() {
  for (const key of ADVANCED_FILTERS) (state as unknown as Record<string, unknown>)[key] = "";
  state.search = "";
  clearGrouped();
  void refresh(true);
}
function sort(field: string) {
  if (state.sort === field) state.direction = state.direction === "asc" ? "desc" : "asc";
  else { state.sort = field; state.direction = "asc"; }
  state.offset = 0; void refresh(true);
}
/** The calendar dates a chart block's column covers, kept inside the selected period. */
function columnDates(target: { from: string; to: string }) {
  const first = localDate(target.from, state.timezone);
  const last = localDate(new Date(Date.parse(target.to) - 1).toISOString(), state.timezone);
  const { fromDate, toDate } = period.value;
  return { from: first < fromDate ? fromDate : first, to: last > toDate ? toDate : last };
}
/** The runs block on the Overview chart opens the Workflow runs page for the column's dates. */
function openRunsWindow(target: { from: string; to: string }) {
  const dates = columnDates(target);
  Object.assign(state, { period: "custom", fromTime: dates.from, toTime: dates.to });
  changeView("runs");
}
/** The individual jobs' block opens the Jobs page for the column's dates. */
function openJobsWindow(target: { from: string; to: string }) {
  const dates = columnDates(target);
  Object.assign(state, { period: "custom", fromTime: dates.from, toTime: dates.to });
  changeView("tool-runs");
}
function showDemoPeriod() {
  const window = summary.value?.demo_period;
  if (!window) return;
  state.period = "custom";
  state.fromTime = todayIn(state.timezone, new Date(window.from));
  state.toTime = todayIn(state.timezone, new Date(window.to));
  void refresh(true);
}
async function moreUndated() {
  // Pinned to the loaded revision, so the added rows belong to the same snapshot.
  const pinned = { ...state, revision: summary.value?.revision_id || state.revision };
  try {
    const next = await get<JobList>(
      `/jobs?${queryString(pinned)}&undated_offset=${jobs.value.undated_items.length}`,
    );
    jobs.value = { ...jobs.value, undated_items: [...jobs.value.undated_items, ...next.undated_items] };
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : "Unable to load more jobs";
  }
}
function selectTool(toolId: string) {
  state.toolId = toolId; changeView("tool-runs");
}

/* The Workflow runs page. Every control below narrows the list, the totals and
   the chart together, and a filter that changes clears any grouped selection. */
function pinned(): ReportState {
  return { ...state, revision: summary.value?.revision_id || state.revision };
}
/** A page fetch that hit a superseded snapshot starts over on the latest one. */
function recoverFrom(reason: unknown, mine: number, fallback: string) {
  if (mine !== generation || (reason as Error).name === "AbortError") return;
  if (reason instanceof ApiError && reason.status === 409) void refresh(false);
  else error.value = reason instanceof Error ? reason.message : fallback;
}
function runFilterChanged() {
  clearGrouped();
  state.offset = 0;
  void refresh(true);
}
function selectWorkflow(key: string) {
  state.workflowKey = state.workflowKey === key ? "" : key;
  runFilterChanged();
}
function chooseWorkflow(key: string) {
  state.workflowKey = key;
  runFilterChanged();
}
function selectOutcome(outcome: string) {
  state.runStatus = outcome as RunStatus | "";
  runFilterChanged();
}
function changeRunSearch(text: string) {
  state.search = text;
  clearGrouped();
  changeFilters();
}
function toggleFocus(window: { from: string; to: string }) {
  const same = state.focusFrom === window.from && state.focusTo === window.to;
  state.focusFrom = same ? "" : window.from;
  state.focusTo = same ? "" : window.to;
  runFilterChanged();
}
function selectGrouped(key: string, boundary: { amount: string; runId: string } | null) {
  if (!boundary) return;
  // The other filters stay; the grouped runs are chosen within them.
  state.workflowKey = key;
  state.maxRunAmount = boundary.amount;
  state.boundaryRunId = boundary.runId;
  state.offset = 0;
  void refresh(true);
}
function clearFocus() {
  state.focusFrom = ""; state.focusTo = "";
  runFilterChanged();
}
function clearGroupedSelection() {
  clearGrouped();
  void refresh(true);
}
function clearRunFilters() {
  Object.assign(state, NO_RUN_FILTERS);
  state.search = "";
  void refresh(true);
}
async function reloadRuns(choice: string) {
  const next = RUN_SORTS.find(candidate => candidate.id === choice) ?? RUN_SORTS[0];
  state.runSort = next.sort as ReportState["runSort"];
  state.runDirection = next.direction;
  updateUrl(true);
  const current = runsView.value;
  if (!current) return;
  // Sorting reorders the list only, so the totals and charts are not fetched again.
  const mine = generation;
  try {
    const list = await loadMoreRuns(pinned(), 0);
    if (mine !== generation) return;
    viewData.value = { ...current, list };
  } catch (reason) {
    recoverFrom(reason, mine, "Unable to sort the runs");
  }
}
async function moreRuns() {
  const current = runsView.value;
  if (!current || loadingMore.value) return;
  const mine = generation;
  loadingMore.value = true;
  try {
    const next = await loadMoreRuns(pinned(), current.list.items.length);
    if (mine !== generation) return;
    viewData.value = {
      ...current, list: { ...current.list, items: [...current.list.items, ...next.items], total: next.total },
    };
  } catch (reason) {
    recoverFrom(reason, mine, "Unable to load more runs");
  } finally {
    loadingMore.value = false;
  }
}
async function chooseChart(kind: "workflow" | "time") {
  state.runChart = kind;
  updateUrl(true);
  const current = runsView.value;
  if (!current) return;
  const needed = chartsNeeded(state);
  const missing = needed.breakdown && !current.breakdown ? "breakdown"
    : needed.timeline && !current.timeline ? "timeline" : null;
  if (!missing) return;
  // The other tab loads lazily, from the same revision the page already shows.
  const mine = generation;
  loadingChart.value = true;
  try {
    const charts = await loadRunChart(pinned(), missing);
    if (mine !== generation) return;
    viewData.value = {
      ...current, breakdown: charts.breakdown ?? current.breakdown, timeline: charts.timeline ?? current.timeline,
    };
  } catch (reason) {
    recoverFrom(reason, mine, "Unable to load the chart");
  } finally {
    loadingChart.value = false;
  }
}
async function downloadRuns() {
  await download();
}

async function showDetail(
  kind: "runs" | "tool-runs", id: string, updateHistory = true, opener: HTMLElement | null = null,
  trail: "reset" | "push" | "keep" = "reset",
) {
  // Pressing the open run's own trigger closes the drawer again.
  if (detailKind.value === kind && detailId.value === id && detail.value) {
    closeDetail(true);
    return;
  }
  const swapping = detailKind.value !== null;
  if (trail === "reset") detailTrail.value = [];
  else if (trail === "push" && detailKind.value) {
    detailTrail.value = [...detailTrail.value, { kind: detailKind.value, id: detailId.value }];
  }
  // Focus goes back to whatever the person last used to open a run.
  if (!swapping || opener) detailOpener = opener ?? (document.activeElement as HTMLElement | null);
  const mine = ++detailToken;
  detailKind.value = kind;
  detailId.value = id;
  if (updateHistory) {
    const params = new URLSearchParams(location.search);
    params.set("detail_kind", kind); params.set("detail_id", id);
    // A swap replaces the entry, so Back leaves the drawer rather than stepping through runs.
    history[swapping ? "replaceState" : "pushState"]({}, "", `${location.pathname}?${params}`);
  }
  detailLoading.value = true;
  const path = kind === "runs" ? "invocations" : "jobs";
  try {
    const result = await get<Record<string, unknown>>(`/${path}/${id}?${queryString(state)}`);
    if (mine === detailToken) detail.value = result;
  } catch (reason) {
    if (mine === detailToken) error.value = reason instanceof Error ? reason.message : "Unable to load detail";
  } finally {
    if (mine === detailToken) detailLoading.value = false;
  }
}
function detailBack() {
  const previous = detailTrail.value[detailTrail.value.length - 1];
  if (!previous) return;
  detailTrail.value = detailTrail.value.slice(0, -1);
  void showDetail(previous.kind, previous.id, true, null, "keep");
}
function closeDetail(returnFocus = true, updateHistory = true) {
  detailToken += 1;
  detailTrail.value = [];
  const wasOpen = detailKind.value !== null;
  detail.value = null; detailKind.value = null; detailId.value = ""; detailLoading.value = false;
  if (updateHistory && wasOpen) {
    const params = new URLSearchParams(location.search);
    params.delete("detail_kind"); params.delete("detail_id");
    history.pushState({}, "", `${location.pathname}?${params}`);
  }
  // A press outside moves focus where the person pointed, so only Escape and
  // the close button send it back to the opener.
  if (returnFocus && wasOpen) detailOpener?.focus();
  detailOpener = null;
}
function refreshLatest() { void refresh(true); }
async function download() {
  try { await downloadExport(state); }
  catch (reason) { error.value = reason instanceof Error ? reason.message : "Unable to export report"; }
}
function onPopState() {
  const params = new URLSearchParams(location.search);
  const kind = params.get("detail_kind"); const id = params.get("detail_id");
  Object.assign(state, stateFromUrl(location.search)); void refresh(false);
  if ((kind === "runs" || kind === "tool-runs") && id) void showDetail(kind, id, false);
  else closeDetail(false, false);
}
function onKey(event: KeyboardEvent) {
  // The detail drawer closes itself on Escape; this closes the filters panel on narrow screens.
  if (event.key === "Escape" && !detailKind.value) drawerOpen.value = false;
}

onMounted(() => {
  window.addEventListener("popstate", onPopState);
  window.addEventListener("keydown", onKey);
  void refresh();
  const params = new URLSearchParams(location.search);
  const kind = params.get("detail_kind"); const id = params.get("detail_id");
  if ((kind === "runs" || kind === "tool-runs") && id) void showDetail(kind, id, false);
});
onBeforeUnmount(() => {
  controller?.abort();
  window.removeEventListener("popstate", onPopState);
  window.removeEventListener("keydown", onKey);
});
</script>

<template>
  <header class="masthead">
    <div class="masthead-inner">
      <div class="brand"><CircleDollarSign :size="28" aria-hidden="true" /><span>Rainstone</span></div>
      <span v-if="summary?.demo" class="demo-badge">Demo data · synthetic scenarios included</span>
      <span v-else-if="summary?.imported_snapshot" class="demo-badge">
        Imported snapshot{{ summary.imported_snapshot.captured_at
          ? ` · captured ${formatDateTime(summary.imported_snapshot.captured_at, state.timezone)}`
          : "" }}
      </span>
      <span v-else-if="me?.attribution" class="demo-badge">{{ me.attribution }}</span>
    </div>
  </header>

  <div class="shell">
    <button class="drawer-toggle" :aria-expanded="drawerOpen" @click="drawerOpen = !drawerOpen">
      <Filter :size="18" aria-hidden="true" /> Filters
      <span v-if="filters.length" class="count">{{ filters.length }}</span>
    </button>
    <div class="sidebar-wrap" :data-open="drawerOpen">
      <ReportSidebar
        :state="state"
        :can-view-server="Boolean(me?.capabilities.infrastructure)"
        :can-view-users="Boolean(me?.capabilities.users)"
        :advanced-open="advancedOpen"
        @view="changeView"
        @period="changePeriod"
        @set="setField"
        @toggle-advanced="advancedOpen = !advancedOpen"
        @clear-filter="clearFilter"
        @clear="clearFilters"
      >
        <template v-if="state.view === 'runs'" #page-filters>
          <PageFilters
            :state="state" :options="runsView?.list.filter_options ?? null"
            @workflow="chooseWorkflow" @outcome="selectOutcome" @search="changeRunSearch"
            @clear-focus="clearFocus" @clear-grouped="clearGroupedSelection" @clear="clearRunFilters"
          />
        </template>
      </ReportSidebar>
    </div>

    <main id="main" class="page" :style="{ minHeight: holdHeight ? `${holdHeight}px` : undefined }">
      <h1 class="page-title">{{ TITLES[state.view] }}</h1>
      <div v-if="error" class="error" role="alert">
        <strong>Reporting data unavailable.</strong> {{ error }}
      </div>
      <div v-if="loading && !keepPrevious" class="loading" aria-live="polite">
        <RefreshCw class="spin" :size="18" /> Loading…
      </div>

      <div
        v-if="summary && (!loading || keepPrevious)" :class="{ refetching: keepPrevious }"
        :aria-busy="keepPrevious"
      >
        <OverviewPanel
          v-if="state.view === 'overview' && costTimeline"
          :state="state" :summary="summary" :timeline="costTimeline" :tools="tools" :runs="runs"
          @view="changeView" @run="(id, opener) => showDetail('runs', id, true, opener)"
          @runs="openRunsWindow" @jobs="openJobsWindow"
          @demo-period="showDemoPeriod"
        />

        <RunsPage
          v-else-if="state.view === 'runs' && runsView"
          :state="state" :view="runsView" :sort="runSortChoice" :open-run-id="openRunId"
          :hover-run-id="hoverRunId" :loading-more="loadingMore" :loading-chart="loadingChart"
          :as-of="summary.as_of"
          @chart="chooseChart" @workflow="selectWorkflow"
          @run="(id, opener) => showDetail('runs', id, true, opener)"
          @grouped="selectGrouped" @column="toggleFocus" @hover="hoverRunId = $event ?? ''"
          @sort="reloadRuns" @more="moreRuns" @clear="clearRunFilters" @export="downloadRuns"
        />

        <ToolRunsPanel
          v-else-if="state.view === 'tool-runs'"
          :jobs="jobs.items" :undated-jobs="jobs.undated_items" :total="jobs.total"
          :undated="summary.undated" :period-label="periodLabel" :timezone="state.timezone"
          @detail="(id, opener) => showDetail('tool-runs', id, true, opener)" @sort="sort" @export="download"
          @more-undated="moreUndated"
        />

        <ToolsPanel
          v-else-if="state.view === 'tools'"
          :tools="tools" :period-label="periodLabel" @select="selectTool"
        />

        <ServerPanel v-else-if="state.view === 'server'" :server="server" :timezone="state.timezone" />

        <StatusPanel
          v-else-if="state.view === 'status'"
          :status="status" :freshness="freshness" :timezone="state.timezone"
        />

        <section v-else-if="state.view === 'daily'" class="panel">
          <div class="panel-heading">
            <div><h2>Daily cost</h2>
              <p>Cost accrued each day in {{ periodLabel }}, in {{ state.timezone }}.</p></div>
          </div>
          <div class="table-wrap">
            <table>
              <thead><tr><th>Date</th><th>Cost</th><th>Jobs</th><th>Coverage</th></tr></thead>
              <tbody>
                <tr v-for="day in days" :key="day.date">
                  <td>{{ day.date }}</td>
                  <td>{{ formatCost(day.amount) }}</td>
                  <td>{{ day.job_count }}</td>
                  <td>
                    {{ day.incomplete_count ? `${day.incomplete_count} still need cost data` : "Complete" }}
                    <span v-if="day.provisional">· still running</span>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>

        <section v-else-if="state.view === 'users'" class="panel">
          <div class="panel-heading">
            <div><h2>Galaxy accounts</h2><p>Cost by Galaxy account in {{ periodLabel }}.</p></div>
          </div>
          <div class="table-wrap">
            <table>
              <thead><tr><th>Account</th><th>Jobs</th><th>Cost</th></tr></thead>
              <tbody>
                <tr v-for="group in tools" :key="group.owner_id">
                  <td>{{ group.label }}</td><td>{{ group.job_count }}</td>
                  <td>{{ formatCost(group.amount) }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>

        <nav
          v-if="state.view === 'tool-runs' && jobs.total > jobs.limit" class="pagination"
          aria-label="Pages"
        >
          <button
            :disabled="state.offset === 0"
            @click="state.offset = Math.max(0, state.offset - jobs.limit); refresh(true)"
          >Previous</button>
          <span>Page {{ page }} · {{ jobs.total }} jobs</span>
          <button
            :disabled="state.offset + jobs.limit >= jobs.total"
            @click="state.offset += jobs.limit; refresh(true)"
          >Next</button>
        </nav>

        <div v-if="state.view !== 'status'" class="snapshot">
          {{ PRIMARY_MEASURE }} · {{ describePeriod(period, state.timezone) }} ·
          <span :class="{ stale: collection.stale }">
            {{ collection.cutoff
              ? `Collected through ${formatDateTime(collection.cutoff, state.timezone)}`
              : "Collection time unknown" }}{{ collection.stale ? " (stale)" : "" }}
          </span> ·
          Calculated {{ summary.as_of ? formatDateTime(summary.as_of, state.timezone) : "unavailable" }}
          <button class="link-button" @click="refreshLatest">Refresh</button>
          <details class="inline-details">
            <summary>Technical details</summary>
            <p class="mono">Snapshot {{ summary.revision_id }} · {{ summary.calculation_version }}</p>
            <p>
              {{ summary.observation_window.semantics }} interval in
              {{ summary.observation_window.timezone }}. Amounts are estimates in USD covering
              compute only, at Google Cloud's published on-demand prices; disks, network,
              discounts, credits and taxes are excluded.
            </p>
            <p v-if="summary.price_list">
              Price list updated {{ formatDateTime(summary.price_list.observed_at, state.timezone) }}.
              <a v-if="summary.price_list.url" :href="summary.price_list.url" target="_blank" rel="noopener">
                Price list used for these estimates</a>
            </p>
          </details>
        </div>
      </div>
    </main>
  </div>

  <DetailDrawer
    :kind="detailKind" :detail="detail" :loading="detailLoading" :period-label="periodLabel"
    :timezone="state.timezone" :back-label="detailTrail.length ? (detailTrail[detailTrail.length - 1].kind === 'runs' ? 'Back to workflow run' : 'Back to job') : ''"
    @close="closeDetail(true)" @dismiss="closeDetail(false)" @back="detailBack"
    @open="(kind, id) => showDetail(kind, id, true, null, 'push')"
  />
</template>
