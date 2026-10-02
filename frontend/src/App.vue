<script setup lang="ts">
import { CalendarRange, CircleDollarSign, Filter, RefreshCw } from "@lucide/vue";
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from "vue";
import {
  ADVANCED_FILTERS, ApiError, activeFilters, chartsNeeded, collectionCutoff, DEFAULT_RANKING,
  DEFAULT_RUN_CONTROLS, downloadExport, figuresDiffer, get, loadJobCharts, loadJobPage, loadMoreRuns,
  loadReport, loadRunChart, loadToolRanking, NO_RUN_FILTERS, periodOf, queryString, stateFromUrl,
  urlQuery, WINDOW_PAGE_SIZE,
  type AdvancedFilter, type CostPiece, type CostTimeline, type DailyItem, type DrawerKind, type Freshness,
  type GroupItem, type Infrastructure, type JobCharts, type JobList, type JobsChart, type Me,
  type ReportState, type RunsView, type RunStatus, type Status, type Summary, type ToolRanking, type View,
} from "./api";
import DetailDrawer from "./components/DetailDrawer.vue";
import JobsPage from "./components/jobs/JobsPage.vue";
import OverviewPanel from "./components/OverviewPanel.vue";
import ReportSidebar from "./components/ReportSidebar.vue";
import PageFilters from "./components/runs/PageFilters.vue";
import RunsPage from "./components/runs/RunsPage.vue";
import ServerPanel from "./components/ServerPanel.vue";
import StatusPanel from "./components/StatusPanel.vue";
import { parseWindowId, windowId, windowLabel, type JobWindow } from "./jobsView";
import {
  intervalNoun, intervalTitle, overviewId, overviewParams, parseOverviewId,
} from "./overviewDetail";
import { describePeriod, PERIOD_LABELS, periodRange, todayIn, type PeriodId } from "./periods";
import { formatCost, formatDate, formatDateTime, PRIMARY_MEASURE, RUN_SORTS } from "./vocabulary";

const TITLES: Record<View, string> = {
  overview: "Overview",
  runs: "Workflow runs",
  "tool-runs": "Jobs",
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
const welcomeDismissed = ref(false);
const overviewHelp = ref<HTMLButtonElement | null>(null);
const welcomeKey = computed(() => me.value?.source_id
  ? `rainstone:overview-welcome:v1:${encodeURIComponent(location.pathname)}:${encodeURIComponent(me.value.source_id)}`
  : null);
watch(welcomeKey, key => {
  try { welcomeDismissed.value = Boolean(key && localStorage.getItem(key) === "dismissed"); }
  catch { welcomeDismissed.value = false; }
});
const viewData = ref<unknown>(null);
// The view the page last drew, so a refetch of the same view can keep it on screen.
const renderedView = ref<View | null>(null);
const loading = ref(true);
const error = ref("");
const detail = ref<Record<string, unknown> | null>(null);
const detailKind = ref<DrawerKind | null>(null);
const detailId = ref("");
// Which page of an interval's jobs is open, and whether another is being fetched.
const detailOffset = ref(0);
const detailPaging = ref(false);
const detailLoading = ref(false);
const detailError = ref("");
// The part of a run's cost that is open in the drawer, and a member of a pooled part inside it.
const detailPart = ref("");
const detailMember = ref("");
// Where a run was left when a job was opened from it, applied once the run is back.
const detailRestore = ref<{ scrollTop: number; focusId: string } | null>(null);
const advancedOpen = ref(false);
const drawerOpen = ref(false);
const hoverRunId = ref("");
const loadingMore = ref(false);
const loadingChart = ref(false);
// How much of the Jobs page's tool ranking is shown, and the tool search inside it.
const toolRanking = ref<ToolRanking>({ ...DEFAULT_RANKING });
const loadingRanking = ref(false);
const loadingList = ref(false);
// A minimum height for the page while a narrower answer would otherwise make it jump; 0 for none.
const holdHeight = ref(0);
// A revision with figures that differ from the ones shown, found while the reader stayed on the page.
const newerFigures = ref(false);
// A refetch that keeps the previous figures on screen until the new ones arrive.
const updating = ref(false);
// Rows added to the page since it loaded, which a refetch would drop.
let extended = false;
let checkedRevision = "";
let checking = false;
let checkTimer = 0;
let detailOpener: HTMLElement | null = null;
let controller: AbortController | null = null;
let timer = 0;
let firstLoad = true;
// Each load or page fetch belongs to the report it started from; a result that
// arrives after the report has changed is dropped, never mixed into the new one.
let generation = 0;
let detailToken = 0;
// Runs, jobs, tools and intervals opened from inside the drawer, so its back button can retrace them.
interface TrailStop {
  kind: DrawerKind; id: string; part: string; member: string; offset: number;
  scrollTop: number; focusId: string;
}
const detailTrail = ref<TrailStop[]>([]);
// The scroll position and row of whatever the drawer is about to open from itself.
let leaving = { scrollTop: 0, focusId: "" };
// The drawer's place in the address, and the one it was opened from, so a reload can go back to it.
const DETAIL_PARAMS = [
  "detail_kind", "detail_id", "detail_part", "detail_member", "detail_offset",
  "detail_parent_kind", "detail_parent_id", "detail_parent_offset",
] as const;
const DRAWER_KINDS: DrawerKind[] = ["runs", "tool-runs", "tool", "window", "overview", "guide"];
const BACK_LABELS: Record<DrawerKind, string> = {
  runs: "Back to workflow run", "tool-runs": "Back to job", tool: "Back to tool", window: "", overview: "", guide: "",
};

const period = computed(() => periodOf(state));
const periodLabel = computed(() => (state.period === "custom"
  ? "the selected dates"
  : PERIOD_LABELS[state.period].toLowerCase()));
const filters = computed(() => activeFilters(state));
// Fixture and imported data have fixed dates; an empty period offers to jump to them.
const recordedDates = computed(() => {
  const window = summary.value?.demo_period;
  if (!window || summary.value?.job_count || ["server", "status"].includes(state.view)) return "";
  const from = formatDate(window.from, state.timezone);
  const to = formatDate(window.to, state.timezone);
  return from === to ? from : `${from} – ${to}`;
});
const days = computed(() => (state.view === "daily"
  ? ((viewData.value as { items?: DailyItem[] } | null)?.items || [])
  : []));
const costTimeline = computed(() => (
  state.view === "overview" && renderedView.value === "overview" && viewData.value
    ? viewData.value as CostTimeline : null));
const accounts = computed(() => ((viewData.value as { items?: GroupItem[] } | null)?.items || []));
const runsView = computed(() => (state.view === "runs" && renderedView.value === "runs" && viewData.value
  ? viewData.value as RunsView : null));
const jobCharts = computed(() => (
  state.view === "tool-runs" && renderedView.value === "tool-runs" && viewData.value
    ? viewData.value as JobCharts : null));
const server = computed(() => (state.view === "server"
  ? viewData.value as Infrastructure | null
  : null));
const status = computed(() => (state.view === "status" ? viewData.value as Status | null : null));
const collection = computed(() => collectionCutoff(freshness.value));
const openRunId = computed(() => (detailKind.value === "runs" ? detailId.value : ""));
/** The drawer, or the drawer a job was opened from, of the given kind; its ID or empty. */
function openOrParent(kind: DrawerKind): string {
  if (detailKind.value === kind) return detailId.value;
  const parent = detailTrail.value[detailTrail.value.length - 1];
  return detailKind.value && parent?.kind === kind ? parent.id : "";
}
const openToolKey = computed(() => openOrParent("tool"));
const openWindowFrom = computed(() => parseWindowId(openOrParent("window"))?.from ?? "");
const openJobId = computed(() => (detailKind.value === "tool-runs" && !detailTrail.value.length ? detailId.value : ""));
/** The chart interval a drawer stop describes: a Jobs chart column, or an Overview block. */
function stopWindow(stop: Pick<TrailStop, "kind" | "id"> | undefined): JobWindow | null {
  if (stop?.kind === "window") return parseWindowId(stop.id);
  const descriptor = stop?.kind === "overview" ? parseOverviewId(stop.id) : null;
  return descriptor?.scope === "interval" ? descriptor.window : null;
}
// A job or run opened from an interval describes its share of that interval, not of the period.
const parentWindow = computed<JobWindow | null>(() => {
  const parent = detailTrail.value[detailTrail.value.length - 1];
  return detailKind.value === "tool-runs" || detailKind.value === "runs" ? stopWindow(parent) : null;
});
const openWindow = computed(() => (detailKind.value === "window" ? parseWindowId(detailId.value) : null));
const openOverview = computed(() => (detailKind.value === "overview" ? parseOverviewId(detailId.value) : null));
// The Overview block whose drawer is open, or that the open run or job came from.
const openBlock = computed(() => {
  const descriptor = parseOverviewId(openOrParent("overview"));
  return descriptor?.scope === "interval" ? `${descriptor.window.from}|${descriptor.category}` : "";
});
const drawerPeriodLabel = computed(() => (parentWindow.value
  ? windowLabel(parentWindow.value, state.timezone) : periodLabel.value));
const drawerTitle = computed(() => {
  if (openWindow.value) return windowLabel(openWindow.value, state.timezone);
  const descriptor = openOverview.value;
  if (!descriptor) return "";
  if (descriptor.scope === "interval") return intervalTitle(descriptor, state.timezone);
  return state.period === "custom" ? periodRange(period.value) : PERIOD_LABELS[state.period];
});
const drawerNoun = computed(() => {
  if (openWindow.value) return `this ${openWindow.value.unit}`;
  return openOverview.value?.scope === "interval" ? intervalNoun(openOverview.value) : "";
});
const backLabel = computed(() => {
  const parent = detailTrail.value[detailTrail.value.length - 1];
  if (!parent) return "";
  if (parent.kind === "overview" && parseOverviewId(parent.id)?.scope === "period") return "Back to this period";
  const window = stopWindow(parent);
  return window ? `Back to selected ${window.unit}` : BACK_LABELS[parent.kind];
});
// Refetching the runs or jobs page keeps the last picture, dimmed, instead of a
// skeleton, so nothing on the page moves while the answer changes.
const keepPrevious = computed(() => loading.value
  && (updating.value || runsView.value !== null || jobCharts.value !== null));
const runSortChoice = computed(() => RUN_SORTS.find(
  choice => choice.sort === state.runSort && choice.direction === state.runDirection,
)?.id ?? RUN_SORTS[0].id);

function updateUrl(push = false) {
  const query = urlQuery(state);
  const current = new URLSearchParams(location.search);
  if (current.get("detail_kind") && current.get("detail_id")) {
    for (const name of DETAIL_PARAMS) {
      const value = current.get(name);
      if (value) query.set(name, value);
    }
  }
  history[push ? "pushState" : "replaceState"]({}, "", `${location.pathname}?${query}`);
}

async function refresh(push = false, quiet = false) {
  controller?.abort();
  controller = new AbortController();
  const mine = ++generation;
  updating.value = quiet && summary.value !== null;
  // Refetching the page being read must not move the reader.
  const scrolledTo = renderedView.value === state.view ? window.scrollY : null;
  if (scrolledTo !== null) holdHeight.value = document.getElementById("main")?.offsetHeight ?? 0;
  loading.value = true; error.value = "";
  updateUrl(push && !firstLoad);
  try {
    const result = await loadReport(state, controller.signal, toolRanking.value);
    if (mine !== generation) return;
    // The totals, the charts and the list are committed together, so a new
    // total is never shown beside the previous filter's chart.
    summary.value = result.summary; jobs.value = result.jobs;
    freshness.value = result.freshness; me.value = result.me; viewData.value = result.view;
    renderedView.value = state.view;
    firstLoad = false; extended = false; newerFigures.value = false;
    if (scrolledTo !== null) await keepPlace(scrolledTo);
  } catch (reason) {
    if ((reason as Error).name !== "AbortError" && mine === generation) {
      error.value = reason instanceof Error ? reason.message : "Unable to load reporting data";
    }
  } finally {
    if (mine === generation) { loading.value = false; updating.value = false; }
  }
}

const CHECK_INTERVAL_MS = 60_000;

/** Whether a refetch would leave everything the reader opened or loaded as it was. */
function undisturbed(): boolean {
  return !extended && !detailKind.value && !loadingMore.value && !loadingChart.value
    && !loadingRanking.value && !loadingList.value;
}

/**
 * Look for figures newer than the ones shown. Figures the reader is looking at
 * are only replaced when they asked or could not have been reading them: on
 * coming back to a hidden tab, or when the page has no jobs to read.
 */
async function checkForNewer(returning = false) {
  const shown = summary.value;
  if (checking || loading.value || error.value || !shown || state.view === "status"
    || document.visibilityState !== "visible") return;
  checking = true;
  const mine = generation;
  try {
    if (!newerFigures.value) {
      const latest = (await get<Freshness>("/freshness")).revision_id;
      if (!latest || latest === shown.revision_id || latest === checkedRevision) return;
      const candidate = await get<Summary>(`/summary?${queryString(state)}`);
      if (mine !== generation) return;
      checkedRevision = latest;
      newerFigures.value = figuresDiffer(shown, candidate);
    }
    if (newerFigures.value && (returning || shown.job_count === 0) && undisturbed()) {
      void refresh(false, true);
    }
  } catch {
    // A failed check changes nothing on the page; the next one tries again.
  } finally {
    checking = false;
  }
}
function onVisibility() {
  if (document.visibilityState === "visible") void checkForNewer(true);
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
  if (detailKind.value === "guide") {
    closeDetail(false, false);
    const params = new URLSearchParams(location.search);
    for (const name of DETAIL_PARAMS) params.delete(name);
    history.replaceState({}, "", `${location.pathname}?${params}`);
  }
  if (state.view !== view) {
    resetRunPage();
    toolRanking.value = { ...DEFAULT_RANKING };
  }
  state.view = view; state.offset = 0; drawerOpen.value = false; closeDetail(false, false);
  void refresh(true);
}
/**
 * An Overview drawer explains the report it was opened from, so a change to
 * the report's dates or filters closes it rather than leave it describing
 * another report. The entry it was open in is rewritten without it.
 */
function closeReportDetail() {
  if (detailKind.value !== "overview" && !detailTrail.value.some(stop => stop.kind === "overview")) return;
  closeDetail(false, false);
  const params = new URLSearchParams(location.search);
  for (const name of DETAIL_PARAMS) params.delete(name);
  history.replaceState({}, "", `${location.pathname}?${params}`);
}
function changePeriod(id: PeriodId) {
  closeReportDetail();
  state.period = id; state.offset = 0;
  // A focus window and a grouped selection belong to the period they were made in.
  state.focusFrom = ""; state.focusTo = ""; clearGrouped();
  if (id === "custom" && !state.fromTime) {
    state.fromTime = period.value.fromDate; state.toTime = period.value.toDate;
  }
  void refresh(true);
}
function setField(key: string, value: string) {
  closeReportDetail();
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
  closeReportDetail();
  (state as unknown as Record<string, unknown>)[key] = "";
  clearGrouped();
  void refresh(true);
}
function clearFilters() {
  closeReportDetail();
  for (const key of ADVANCED_FILTERS) (state as unknown as Record<string, unknown>)[key] = "";
  state.search = "";
  clearGrouped();
  void refresh(true);
}
/** A block of the Overview chart opens what ran in its exact interval, over the page. */
function openBlockDrawer(category: CostPiece["kind"], window: JobWindow, opener: HTMLElement) {
  void showDetail("overview", overviewId({ scope: "interval", category, window }), true, opener);
}
function explorePeriod(opener: HTMLElement) {
  void showDetail("overview", overviewId({ scope: "period", category: "runs" }), true, opener);
}
/** The period drawer's tabs replace each other in place; neither is a step in the history. */
function switchOverviewTab(category: "runs" | "tools") {
  void showDetail("overview", overviewId({ scope: "period", category }), true, null, "keep",
    { part: "", member: "" }, { scrollTop: 0, focusId: category });
}
/** The explicit way from a period ranking to the page that lists every run or tool. */
function seeAll(category: "runs" | "tools") {
  if (category === "tools") openTools();
  else changeView("runs");
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
    extended = true;
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : "Unable to load more jobs";
  }
}
/** Overview's tools lead to the Jobs page's By tool chart, which replaced the Tools page. */
function openTools() {
  state.jobsChart = "tool";
  changeView("tool-runs");
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
    extended = true;
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

/* The Jobs page. Its chart tab, ranking size and tool search are presentation:
   only the list's page and order, and an explicit "Show N jobs", touch the report. */
async function chooseJobsChart(kind: JobsChart) {
  state.jobsChart = kind;
  updateUrl(true);
  const current = jobCharts.value;
  if (!current || (kind === "tool" ? current.breakdown : current.timeline)) return;
  // The other tab loads lazily, from the same revision the page already shows.
  const mine = generation;
  loadingChart.value = true;
  try {
    const charts = await loadJobCharts(pinned(), kind, toolRanking.value);
    if (mine !== generation) return;
    viewData.value = {
      breakdown: charts.breakdown ?? current.breakdown, timeline: charts.timeline ?? current.timeline,
    };
  } catch (reason) {
    recoverFrom(reason, mine, "Unable to load the chart");
  } finally {
    if (mine === generation) loadingChart.value = false;
  }
}
let rankingToken = 0;
async function rankTools(next: ToolRanking) {
  toolRanking.value = next;
  const current = jobCharts.value;
  if (!current?.breakdown) return;
  const mine = generation;
  const asked = ++rankingToken;
  loadingRanking.value = true;
  try {
    const breakdown = await loadToolRanking(pinned(), next);
    if (mine !== generation || asked !== rankingToken) return;
    viewData.value = { ...(jobCharts.value ?? current), breakdown };
  } catch (reason) {
    recoverFrom(reason, mine, "Unable to load the tools");
  } finally {
    if (asked === rankingToken) loadingRanking.value = false;
  }
}
function searchTools(text: string) {
  void rankTools({ ...toolRanking.value, search: text });
}
function showTools(count: number) {
  void rankTools({ ...toolRanking.value, limit: count });
}
/** Another page or order of the job list; the figures and charts do not change, so they are kept. */
async function reloadJobs() {
  updateUrl(true);
  const mine = generation;
  loadingList.value = true;
  try {
    const list = await loadJobPage(pinned());
    if (mine !== generation) return;
    jobs.value = list;
  } catch (reason) {
    recoverFrom(reason, mine, "Unable to load the jobs");
  } finally {
    if (mine === generation) loadingList.value = false;
  }
}
function pageJobs(offset: number) {
  state.offset = offset;
  void reloadJobs();
}
function sortJobs(sort: string, direction: "asc" | "desc") {
  state.sort = sort; state.direction = direction; state.offset = 0;
  void reloadJobs();
}
function openWindowDrawer(window: JobWindow, opener: HTMLElement) {
  void showDetail("window", windowId(window), true, opener);
}
/** The tool drawer's one action that changes the report: list that tool's jobs on the Jobs page. */
function showToolJobs(key: string) {
  closeDetail(false);
  state.toolKey = key; state.offset = 0;
  clearGrouped();
  const listed = () => document.getElementById("job-list-title")?.scrollIntoView({ block: "start" });
  if (state.view === "tool-runs") void refresh(true).then(listed);
  else {
    resetRunPage();
    toolRanking.value = { ...DEFAULT_RANKING };
    state.view = "tool-runs"; state.jobsChart = "tool"; drawerOpen.value = false;
    void refresh(true).then(listed);
  }
}

/** The drawer's place in the address: what is open, which part of it, and what it was opened from. */
function detailParams(
  params: URLSearchParams, stop: Pick<TrailStop, "kind" | "id" | "part" | "member" | "offset">,
  parent: TrailStop | undefined,
) {
  params.set("detail_kind", stop.kind); params.set("detail_id", stop.id);
  const values: Array<[string, string]> = [
    ["detail_part", stop.part], ["detail_member", stop.member],
    ["detail_offset", stop.offset ? String(stop.offset) : ""],
    ["detail_parent_kind", parent?.kind ?? ""], ["detail_parent_id", parent?.id ?? ""],
    ["detail_parent_offset", parent?.offset ? String(parent.offset) : ""],
  ];
  for (const [name, value] of values) {
    if (value) params.set(name, value); else params.delete(name);
  }
}
/** Where a drawer's details come from, under the page's filters at its pinned revision. */
function detailPath(kind: DrawerKind, id: string, offset: number, parent: TrailStop | undefined): string | null {
  if (kind === "guide") return null;
  const query = new URLSearchParams(queryString(pinned()));
  // A run or job opened from an interval is asked for that interval, so its share there is exact.
  const window = stopWindow(parent);
  if (window && (kind === "runs" || kind === "tool-runs")) {
    query.set("from", window.from); query.set("to", window.to);
  }
  if (kind === "runs") return `/invocations/${encodeURIComponent(id)}?${query}`;
  if (kind === "tool") {
    query.set("tool_key", id);
    return `/jobs/tool-detail?${query}`;
  }
  if (kind === "window") {
    const interval = parseWindowId(id);
    if (!interval) return null;
    query.set("window_from", interval.from); query.set("window_to", interval.to);
    query.set("limit", String(WINDOW_PAGE_SIZE)); query.set("offset", String(offset));
    return `/jobs/window-detail?${query}`;
  }
  if (kind === "overview") {
    const descriptor = parseOverviewId(id);
    if (!descriptor) return null;
    for (const [name, value] of overviewParams(descriptor, offset, WINDOW_PAGE_SIZE)) query.set(name, value);
    return `/overview/details?${query}`;
  }
  return `/jobs/${encodeURIComponent(id)}?${query}`;
}
async function showDetail(
  kind: DrawerKind, id: string, updateHistory = true, opener: HTMLElement | null = null,
  trail: "reset" | "push" | "keep" = "reset",
  selection: { part: string; member: string } = { part: "", member: "" },
  restore: { scrollTop: number; focusId: string } | null = null,
  offset = 0,
) {
  // Pressing the open run's own trigger closes the drawer again.
  if (detailKind.value === kind && detailId.value === id && detail.value) {
    closeDetail(true);
    return;
  }
  const swapping = detailKind.value !== null;
  if (trail === "reset") detailTrail.value = [];
  else if (trail === "push" && detailKind.value) {
    detailTrail.value = [...detailTrail.value, {
      kind: detailKind.value, id: detailId.value, part: detailPart.value, member: detailMember.value,
      offset: detailOffset.value, ...leaving,
    }];
  }
  // Focus goes back to whatever the person last used to open a run.
  if (!swapping || opener) detailOpener = opener ?? (kind === "guide"
    ? overviewHelp.value : document.activeElement as HTMLElement | null);
  const mine = ++detailToken;
  detailKind.value = kind;
  detailId.value = id;
  detailPart.value = selection.part; detailMember.value = selection.member;
  detailOffset.value = offset;
  detailRestore.value = restore;
  detailError.value = "";
  const parent = detailTrail.value[detailTrail.value.length - 1];
  if (updateHistory) {
    const params = new URLSearchParams(location.search);
    detailParams(params, { kind, id, offset, ...selection }, parent);
    // A swap replaces the entry, so Back leaves the drawer rather than stepping through runs.
    history[swapping ? "replaceState" : "pushState"]({}, "", `${location.pathname}?${params}`);
  }
  detailLoading.value = true;
  if (kind === "guide") {
    detail.value = { guide: true };
    detailLoading.value = false;
    return;
  }
  const path = detailPath(kind, id, offset, parent);
  try {
    if (!path) throw new Error("This link does not name an interval of the chart.");
    const result = await get<Record<string, unknown>>(path);
    if (mine === detailToken) detail.value = result;
  } catch (reason) {
    if (mine !== detailToken) return;
    // A superseded snapshot reloads the page, then this drawer from the new one.
    if (reason instanceof ApiError && reason.status === 409) {
      detailLoading.value = false;
      await refresh(false);
      if (mine === detailToken) void showDetail(kind, id, false, null, "keep", selection, restore, offset);
      return;
    }
    detailError.value = reason instanceof Error ? reason.message : "Unable to load detail";
  } finally {
    if (mine === detailToken) detailLoading.value = false;
  }
}
/** Another page of an interval's jobs or runs, inside its drawer; its totals and the page stay as they are. */
async function pageWindow(offset: number, scrollTop: number) {
  const kind = detailKind.value;
  if (kind !== "window" && kind !== "overview") return;
  const mine = detailToken;
  const parent = detailTrail.value[detailTrail.value.length - 1];
  const path = detailPath(kind, detailId.value, offset, parent);
  if (!path) return;
  detailPaging.value = true;
  try {
    const result = await get<{ items: Array<{ id: string }> }>(path);
    if (mine !== detailToken) return;
    detailOffset.value = offset;
    detailRestore.value = { scrollTop, focusId: result.items[0]?.id ?? "" };
    detail.value = result as unknown as Record<string, unknown>;
    const params = new URLSearchParams(location.search);
    detailParams(params, { kind, id: detailId.value, part: "", member: "", offset }, parent);
    history.replaceState({}, "", `${location.pathname}?${params}`);
  } catch (reason) {
    if (mine === detailToken) detailError.value = reason instanceof Error ? reason.message : "Unable to load these jobs";
  } finally {
    if (mine === detailToken) detailPaging.value = false;
  }
}
/** A run, job or tool opened from inside the drawer, remembering where the reader was. */
function openFromDrawer(kind: "runs" | "tool-runs" | "tool", id: string, scrollTop: number) {
  leaving = { scrollTop, focusId: id };
  void showDetail(kind, id, true, null, "push");
}
function retryDetail() {
  if (!detailKind.value) return;
  void showDetail(detailKind.value, detailId.value, false, null, "keep", {
    part: detailPart.value, member: detailMember.value,
  }, null, detailOffset.value);
}
/** Choosing a part of a run's cost is part of the address, but not a step in the history. */
function selectPart(part: string, member: string) {
  detailPart.value = part; detailMember.value = member;
  if (!detailKind.value) return;
  const params = new URLSearchParams(location.search);
  detailParams(params, {
    kind: detailKind.value, id: detailId.value, part, member, offset: detailOffset.value,
  }, detailTrail.value[detailTrail.value.length - 1]);
  history.replaceState({}, "", `${location.pathname}?${params}`);
}
function detailBack() {
  const previous = detailTrail.value[detailTrail.value.length - 1];
  if (!previous) return;
  detailTrail.value = detailTrail.value.slice(0, -1);
  void showDetail(previous.kind, previous.id, true, null, "keep",
    { part: previous.part, member: previous.member },
    { scrollTop: previous.scrollTop, focusId: previous.focusId }, previous.offset);
}
function closeDetail(returnFocus = true, updateHistory = true) {
  detailToken += 1;
  detailTrail.value = [];
  const wasOpen = detailKind.value !== null;
  detail.value = null; detailKind.value = null; detailId.value = ""; detailLoading.value = false;
  detailError.value = ""; detailPart.value = ""; detailMember.value = ""; detailRestore.value = null;
  detailOffset.value = 0; detailPaging.value = false;
  if (updateHistory && wasOpen) {
    const params = new URLSearchParams(location.search);
    for (const name of DETAIL_PARAMS) params.delete(name);
    history.pushState({}, "", `${location.pathname}?${params}`);
  }
  // A press outside moves focus where the person pointed, so only Escape and
  // the close button send it back to the opener.
  if (returnFocus && wasOpen) {
    if (detailOpener?.isConnected) detailOpener.focus();
    else overviewHelp.value?.focus();
  }
  detailOpener = null;
}
function openOverviewGuide(opener: HTMLElement) {
  void showDetail("guide", "overview", true, opener);
}
async function dismissOverviewWelcome() {
  welcomeDismissed.value = true;
  try { if (welcomeKey.value) localStorage.setItem(welcomeKey.value, "dismissed"); }
  catch { /* The strip can still be dismissed for this visit when storage is unavailable. */ }
  await nextTick();
  overviewHelp.value?.focus();
}
function refreshLatest() { void refresh(false, true); }
async function download() {
  try { await downloadExport(state); }
  catch (reason) { error.value = reason instanceof Error ? reason.message : "Unable to export report"; }
}
/**
 * The drawer an address describes. A drawer opened from another keeps that one
 * as the place its back button returns to, so a reloaded link still leads back.
 */
/** Whether an address's drawer can be shown on this page; a malformed Overview scope never is. */
function usableStop(kind: DrawerKind | null, id: string | null): kind is DrawerKind {
  if (!kind || !DRAWER_KINDS.includes(kind) || !id) return false;
  if (kind === "guide") return state.view === "overview" && id === "overview";
  return kind !== "overview" || (state.view === "overview" && parseOverviewId(id) !== null);
}
function detailFromUrl(): boolean {
  const params = new URLSearchParams(location.search);
  const kind = params.get("detail_kind") as DrawerKind | null;
  const id = params.get("detail_id");
  if (!usableStop(kind, id) || !id) {
    if (kind) {
      for (const name of DETAIL_PARAMS) params.delete(name);
      history.replaceState({}, "", `${location.pathname}?${params}`);
    }
    return false;
  }
  const parentKind = params.get("detail_parent_kind") as DrawerKind | null;
  const parentId = params.get("detail_parent_id");
  detailKind.value = null;
  detailTrail.value = usableStop(parentKind, parentId) && parentId ? [{
    kind: parentKind, id: parentId, part: "", member: "",
    offset: Number(params.get("detail_parent_offset")) || 0, scrollTop: 0, focusId: id,
  }] : [];
  void showDetail(kind, id, false, null, "keep", {
    part: params.get("detail_part") ?? "", member: params.get("detail_member") ?? "",
  }, null, Number(params.get("detail_offset")) || 0);
  return true;
}
function onPopState() {
  Object.assign(state, stateFromUrl(location.search)); void refresh(false);
  if (!detailFromUrl()) closeDetail(false, false);
}
function onKey(event: KeyboardEvent) {
  // The detail drawer closes itself on Escape; this closes the filters panel on narrow screens.
  if (event.key === "Escape" && !detailKind.value) drawerOpen.value = false;
}

onMounted(() => {
  window.addEventListener("popstate", onPopState);
  window.addEventListener("keydown", onKey);
  document.addEventListener("visibilitychange", onVisibility);
  checkTimer = window.setInterval(() => void checkForNewer(), CHECK_INTERVAL_MS);
  void refresh();
  detailFromUrl();
});
onBeforeUnmount(() => {
  controller?.abort();
  window.clearInterval(checkTimer);
  window.removeEventListener("popstate", onPopState);
  window.removeEventListener("keydown", onKey);
  document.removeEventListener("visibilitychange", onVisibility);
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
      <Filter :size="18" aria-hidden="true" /> {{ state.view === 'server' ? 'Navigation' : 'Filters' }}
      <span v-if="filters.length && state.view !== 'server'" class="count">{{ filters.length }}</span>
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
      <div class="page-title-row" :class="{ 'overview-title-row': state.view === 'overview' }">
        <h1 class="page-title">{{ TITLES[state.view] }}</h1>
        <button
          v-if="state.view === 'overview'" ref="overviewHelp" type="button"
          class="link-button overview-help" data-detail-trigger
          :aria-expanded="detailKind === 'guide'" aria-controls="detail-drawer"
          @click="openOverviewGuide($event.currentTarget as HTMLElement)"
        >How to read this page</button>
        <button
          v-if="recordedDates" type="button" class="secondary recorded-dates"
          @click="showDemoPeriod"
        >
          <CalendarRange :size="16" aria-hidden="true" />
          Show {{ recordedDates }}, when this {{ summary?.imported_snapshot ? "snapshot" : "demonstration" }} was recorded
        </button>
        <div class="newer-figures">
          <span aria-live="polite">{{ newerFigures ? "Newer figures available" : "" }}</span>
          <button v-if="newerFigures" type="button" class="secondary" @click="refreshLatest">
            <RefreshCw :size="16" aria-hidden="true" /> Update
          </button>
        </div>
      </div>
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
          :state="state" :summary="summary" :timeline="costTimeline" :open-block="openBlock"
          :welcome="Boolean(welcomeKey) && !welcomeDismissed" :guide-open="detailKind === 'guide'"
          @view="changeView" @block="openBlockDrawer" @explore="explorePeriod"
          @guide="openOverviewGuide" @dismiss-welcome="dismissOverviewWelcome"
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

        <JobsPage
          v-else-if="state.view === 'tool-runs' && jobCharts"
          :state="state" :summary="summary" :charts="jobCharts" :list="jobs"
          :tool-search="toolRanking.search" :loading-chart="loadingChart" :loading-ranking="loadingRanking"
          :loading-list="loadingList" :open-key="openToolKey" :open-window-from="openWindowFrom"
          :open-job-id="openJobId"
          @chart="chooseJobsChart" @tool="(key, opener) => showDetail('tool', key, true, opener)"
          @window="openWindowDrawer" @search="searchTools" @limit="showTools"
          @job="(id, opener) => showDetail('tool-runs', id, true, opener)"
          @run="(id, opener) => showDetail('runs', id, true, opener)"
          @sort="sortJobs" @page="pageJobs" @export="download" @more-undated="moreUndated"
        />

        <ServerPanel
          v-else-if="state.view === 'server'" :server="server" :timezone="state.timezone"
          :imported="Boolean(summary.imported_snapshot)" @refresh="refreshLatest"
        />

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
                <tr v-for="group in accounts" :key="group.owner_id">
                  <td>{{ group.label }}</td><td>{{ group.job_count }}</td>
                  <td>{{ formatCost(group.amount) }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>


        <div v-if="!['status', 'server'].includes(state.view)" class="snapshot">
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
    :kind="detailKind" :detail="detail" :loading="detailLoading" :period-label="drawerPeriodLabel"
    :timezone="state.timezone" :back-label="backLabel"
    :part="detailPart" :member="detailMember" :restore="detailRestore" :error="detailError"
    :window-title="drawerTitle" :window-noun="drawerNoun" :paging="detailPaging"
    :overview="openOverview" :interval-share="detailKind === 'runs' && parentWindow !== null"
    :can-view-server="Boolean(summary?.can_view_infrastructure)"
    @close="closeDetail(true)" @dismiss="closeDetail(false)" @back="detailBack"
    @open="openFromDrawer" @select="selectPart" @restored="detailRestore = null" @retry="retryDetail"
    @show-jobs="showToolJobs" @page="pageWindow" @tab="switchOverviewTab" @all="seeAll"
  />
</template>
