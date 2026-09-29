<script setup lang="ts">
import { computed } from "vue";
import type { ReportState, RunsView } from "../../api";
import { offsetBoundary, periodOf } from "../../api";
import { describePeriod, exclusiveEnd, monthEnd, PERIOD_LABELS, shiftDays } from "../../periods";
import RunFigures from "./RunFigures.vue";
import RunList from "./RunList.vue";
import RunsChart from "./RunsChart.vue";

const props = defineProps<{
  state: ReportState;
  view: RunsView;
  sort: string;
  openRunId: string;
  hoverRunId: string;
  loadingMore: boolean;
  loadingChart: boolean;
  asOf: string | null;
}>();
const emit = defineEmits<{
  chart: [kind: "workflow" | "time"];
  workflow: [key: string];
  run: [id: string, opener: HTMLElement | null];
  grouped: [key: string, boundary: { amount: string; runId: string } | null];
  column: [window: { from: string; to: string }];
  hover: [id: string | null];
  sort: [id: string];
  more: [];
  clear: [];
  export: [];
}>();

const period = computed(() => periodOf(props.state));
const periodLabel = computed(() => (props.state.period === "custom"
  ? "the selected dates" : PERIOD_LABELS[props.state.period].toLowerCase()));
const workflowName = computed(() => {
  if (!props.state.workflowKey) return "";
  return props.view.list.filter_options.workflows
    .find(option => option.key === props.state.workflowKey)?.name ?? props.state.workflowKey;
});
// Anything other than the workflow choice that narrows the runs.
const narrowed = computed(() => Boolean(
  props.state.runStatus || props.state.search || props.state.focusFrom || props.state.boundaryRunId,
));
const periodFrom = computed(() => offsetBoundary(period.value.fromDate, props.state.timezone));
const periodTo = computed(() => offsetBoundary(exclusiveEnd(period.value), props.state.timezone));
// A week or month still in progress is drawn whole, its coming days empty.
const axisEnd = computed(() => {
  const { id, fromDate } = period.value;
  const lastDay = id === "this-week" ? shiftDays(fromDate, 6) : id === "this-month" ? monthEnd(fromDate) : null;
  return lastDay ? offsetBoundary(shiftDays(lastDay, 1), props.state.timezone) : periodTo.value;
});
const undatedJobs = computed(() => props.view.list.meta.undated?.job_count ?? 0);
</script>

<template>
  <RunFigures
    :totals="view.list.totals"
    :period-text="describePeriod(period, state.timezone)"
    :workflow-name="workflowName"
    :narrowed="narrowed"
  />
  <RunsChart
    :view="view"
    :totals="view.list.totals"
    :chart="state.runChart"
    :workflow-key="state.workflowKey"
    :focus-from="state.focusFrom"
    :focus-to="state.focusTo"
    :period-from="periodFrom"
    :period-to="periodTo"
    :axis-end="axisEnd"
    :period-label="periodLabel"
    :open-run-id="openRunId"
    :hover-run-id="hoverRunId"
    :timezone="state.timezone"
    :as-of="asOf"
    :undated-jobs="undatedJobs"
    :loading-chart="loadingChart"
    @chart="emit('chart', $event)"
    @workflow="emit('workflow', $event)"
    @run="id => emit('run', id, null)"
    @grouped="(key, boundary) => emit('grouped', key, boundary)"
    @column="emit('column', $event)"
    @hover="emit('hover', $event)"
  />
  <RunList
    :runs="view.list.items"
    :total="view.list.total"
    :sort="sort"
    :period-label="periodLabel"
    :timezone="state.timezone"
    :open-run-id="openRunId"
    :hover-run-id="hoverRunId"
    :loading-more="loadingMore"
    @open="(id, opener) => emit('run', id, opener)"
    @sort="emit('sort', $event)"
    @more="emit('more')"
    @clear="emit('clear')"
    @export="emit('export')"
    @hover="emit('hover', $event)"
  />
</template>
