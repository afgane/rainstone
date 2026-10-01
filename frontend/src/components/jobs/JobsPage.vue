<script setup lang="ts">
import { computed } from "vue";
import type { JobCharts, JobList as JobListData, JobsChart as ChartKind, ReportState, Summary } from "../../api";
import { offsetBoundary, periodOf } from "../../api";
import { periodAxisEnd } from "../../chart/axis";
import type { JobWindow } from "../../jobsView";
import { describePeriod, exclusiveEnd, PERIOD_LABELS } from "../../periods";
import JobFigures from "./JobFigures.vue";
import JobList from "./JobList.vue";
import JobsChart from "./JobsChart.vue";

const props = defineProps<{
  state: ReportState;
  summary: Summary;
  charts: JobCharts;
  list: Pick<JobListData, "items" | "undated_items" | "total" | "limit">;
  toolSearch: string;
  loadingChart: boolean;
  loadingRanking: boolean;
  loadingList: boolean;
  openKey: string;
  openWindowFrom: string;
  openJobId: string;
}>();
const emit = defineEmits<{
  chart: [kind: ChartKind];
  tool: [key: string, opener: HTMLElement];
  window: [window: JobWindow, opener: HTMLElement];
  search: [text: string];
  limit: [count: number];
  job: [id: string, opener: HTMLElement];
  run: [id: string, opener: HTMLElement];
  sort: [sort: string, direction: "asc" | "desc"];
  page: [offset: number];
  export: [];
  "more-undated": [];
}>();

const period = computed(() => periodOf(props.state));
const periodLabel = computed(() => (props.state.period === "custom"
  ? "the selected dates" : PERIOD_LABELS[props.state.period].toLowerCase()));
const periodFrom = computed(() => offsetBoundary(period.value.fromDate, props.state.timezone));
const periodTo = computed(() => offsetBoundary(exclusiveEnd(period.value), props.state.timezone));
const axisEnd = computed(() => periodAxisEnd(period.value, props.state.timezone));
// Both charts describe the whole matching set, so either one's totals serve the figures.
const totals = computed(() => props.charts.breakdown?.totals ?? props.charts.timeline?.totals ?? null);
const toolName = computed(() => {
  if (!props.state.toolKey) return "";
  const breakdown = props.charts.breakdown;
  const groups = breakdown ? [
    ...breakdown.groups, ...breakdown.server.groups, ...breakdown.zero.groups, ...breakdown.unavailable.groups,
  ] : [];
  return groups.find(group => group.key === props.state.toolKey)?.name
    ?? props.list.items[0]?.tool_name ?? props.state.toolKey;
});
const narrowed = computed(() => Boolean(
  props.state.search || props.state.state || props.state.runner || props.state.destination
  || props.state.capacity || props.state.quality || props.state.toolId || props.state.toolVersion
  || props.state.workflowId || props.state.invocationId || props.state.minCost || props.state.maxCost
  || props.state.owner,
));
</script>

<template>
  <JobFigures
    :summary="summary" :totals="totals" :period-text="describePeriod(period, state.timezone)"
    :tool-name="toolName" :narrowed="narrowed"
  />
  <JobsChart
    :chart="state.jobsChart" :breakdown="charts.breakdown" :timeline="charts.timeline" :totals="totals"
    :loading-chart="loadingChart" :loading-ranking="loadingRanking" :tool-search="toolSearch"
    :open-key="openKey" :open-window-from="openWindowFrom"
    :period-from="periodFrom" :period-to="periodTo" :axis-end="axisEnd" :period-label="periodLabel"
    :timezone="state.timezone" :as-of="summary.as_of" :undated-jobs="summary.undated?.job_count ?? 0"
    @chart="emit('chart', $event)" @tool="(key, opener) => emit('tool', key, opener)"
    @window="(window, opener) => emit('window', window, opener)"
    @search="emit('search', $event)" @limit="emit('limit', $event)"
  />
  <JobList
    :jobs="list.items" :undated-jobs="list.undated_items" :undated="summary.undated" :total="list.total"
    :offset="state.offset" :limit="list.limit" :sort="state.sort" :direction="state.direction"
    :period-label="periodLabel" :timezone="state.timezone" :open-job-id="openJobId" :loading="loadingList"
    @detail="(id, opener) => emit('job', id, opener)" @run="(id, opener) => emit('run', id, opener)" @sort="(sort, direction) => emit('sort', sort, direction)"
    @page="emit('page', $event)" @export="emit('export')" @more-undated="emit('more-undated')"
  />
</template>
