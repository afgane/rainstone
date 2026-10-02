<script setup lang="ts">
import { computed, ref } from "vue";
import type { JobBreakdown, JobsChart, JobTimeline, JobTotals } from "../../api";
import { bucketLabel } from "../../chart/layout";
import { STATUS_ORDER, type JobWindow } from "../../jobsView";
import {
  formatCost, JOBS_CHART_HINT, pluralize, RECORDED_ONLY_NOTE, STATUS_NOTE, statusLine, statusPieceLabel,
  unplacedSentence,
} from "../../vocabulary";
import { useChartTooltip, type TooltipContent } from "../runs/useChartTooltip";
import JobTimeBars from "./JobTimeBars.vue";
import ToolBars from "./ToolBars.vue";

const props = defineProps<{
  chart: JobsChart;
  breakdown: JobBreakdown | null;
  timeline: JobTimeline | null;
  totals: JobTotals | null;
  /** True while the other tab's data is still being fetched. */
  loadingChart: boolean;
  /** True while a larger batch of tools or a tool search is being fetched. */
  loadingRanking: boolean;
  toolSearch: string;
  openKey: string;
  openWindowFrom: string;
  periodFrom: string;
  periodTo: string;
  axisEnd: string;
  periodLabel: string;
  timezone: string;
  asOf: string | null;
}>();
const emit = defineEmits<{
  chart: [kind: JobsChart];
  tool: [key: string, opener: HTMLElement];
  window: [window: JobWindow, opener: HTMLElement];
  search: [text: string];
  limit: [count: number];
}>();

const tooltipElement = ref<HTMLElement | null>(null);
const tooltip = useChartTooltip(tooltipElement);
function tip(content: TooltipContent | null, x: number, y: number) {
  if (content) void tooltip.show(content, x, y);
  else tooltip.hide();
}

const loaded = computed(() => (props.chart === "tool" ? props.breakdown : props.timeline) !== null);
const heading = computed(() => (props.chart === "tool"
  ? `Recorded cost of each tool in ${props.periodLabel}, across all its matching jobs.`
  : `Cost by ${props.timeline?.bucket ?? "day"}, from when the compute was used.`));
// The statuses that occur, so the key names only what the chart can show.
const statuses = computed(() => {
  const found = new Set(props.totals?.by_status.map(piece => piece.status) ?? []);
  return STATUS_ORDER.filter(status => found.has(status));
});

interface TableRow { key: string; name: string; jobs: number; cost: string | null; statuses: string }
const statusText = (pieces: Array<{ status: string; amount: string | null; job_count: number }>) =>
  pieces.map(statusLine).join("; ") || "—";
const rows = computed<TableRow[]>(() => {
  if (props.chart === "tool") {
    const breakdown = props.breakdown;
    if (!breakdown) return [];
    const ranked = breakdown.groups.map(group => ({
      key: group.key, name: group.name, jobs: group.job_count, cost: group.amount, statuses: statusText(group.by_status),
    }));
    const rest = breakdown.remainder.tool_count ? [{
      key: "remainder", name: `${pluralize(breakdown.remainder.tool_count, "more tool")} with recorded cost`,
      jobs: breakdown.remainder.job_count, cost: breakdown.remainder.amount, statuses: "—",
    }] : [];
    const sections = ([
      ["server", breakdown.server, "Tools that added $0 extra compute"],
      ["zero", breakdown.zero, "Tools that recorded no compute cost"],
      ["unavailable", breakdown.unavailable, "Tools with no cost data yet"],
    ] as const).filter(([, section]) => section.tool_count).map(([key, section, name]) => ({
      key, name: `${name} (${section.tool_count})`, jobs: section.job_count,
      cost: key === "unavailable" ? null : "0", statuses: "—",
    }));
    return [...ranked, ...rest, ...sections];
  }
  const timeline = props.timeline;
  return (timeline?.buckets ?? []).map(bucket => ({
    key: bucket.from,
    name: bucketLabel(timeline!.bucket, Date.parse(bucket.from), Date.parse(bucket.to), props.timezone),
    jobs: bucket.job_count, cost: bucket.amount, statuses: statusText(bucket.by_status),
  }));
});
const tableColumn = computed(() => (props.chart === "tool" ? "Tool"
  : props.timeline?.bucket === "hour" ? "Hour" : props.timeline?.bucket === "week" ? "Week" : "Day"));

function moveTab(event: KeyboardEvent) {
  if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
  emit("chart", props.chart === "tool" ? "time" : "tool");
}
</script>

<template>
  <section class="panel chart-panel" aria-labelledby="jobs-chart-title">
    <div class="panel-heading">
      <div>
        <h2 id="jobs-chart-title">How the cost adds up</h2>
        <p>{{ heading }}</p>
      </div>
      <div class="tabs" role="tablist" aria-label="Chart view">
        <button
          id="tab-tool" role="tab" type="button" aria-controls="jobs-chart-body"
          :aria-selected="chart === 'tool'" :tabindex="chart === 'tool' ? 0 : -1"
          @click="emit('chart', 'tool')" @keydown="moveTab"
        >By tool</button>
        <button
          id="tab-time" role="tab" type="button" aria-controls="jobs-chart-body"
          :aria-selected="chart === 'time'" :tabindex="chart === 'time' ? 0 : -1"
          @click="emit('chart', 'time')" @keydown="moveTab"
        >Over time</button>
      </div>
    </div>

    <div
      id="jobs-chart-body" class="chart" role="tabpanel" :aria-labelledby="`tab-${chart}`"
      aria-describedby="jobs-chart-hint"
    >
      <div class="chart-region" :class="{ 'tool-region': chart === 'tool' && loaded && !loadingChart }">
        <div v-if="!loaded || loadingChart" class="chart-empty">Loading…</div>
        <ToolBars
          v-else-if="chart === 'tool' && breakdown"
          :breakdown="breakdown" :open-key="openKey" :search="toolSearch" :loading="loadingRanking"
          @open="(key, opener) => emit('tool', key, opener)" @search="emit('search', $event)"
          @limit="emit('limit', $event)" @tip="tip"
        />
        <JobTimeBars
          v-else-if="chart === 'time' && timeline"
          :timeline="timeline" :period-from="periodFrom" :period-to="periodTo" :axis-end="axisEnd"
          :open-from="openWindowFrom" :timezone="timezone" :as-of="asOf"
          @window="(window, opener) => emit('window', window, opener)" @tip="tip"
        />
      </div>
    </div>
    <p id="jobs-chart-hint" class="sr-only">{{ JOBS_CHART_HINT }}</p>

    <div class="chart-foot">
      <span v-for="status in statuses" :key="status" class="key">
        <i class="sw" :data-status="status" />{{ statusPieceLabel(status) }}
      </span>
      <span>{{ chart === "tool" ? "Select a tool to see its jobs." : "Select a column to see its jobs." }}</span>
    </div>
    <div class="chart-notes">
      <p>{{ STATUS_NOTE }}</p>
      <p v-if="totals?.incomplete_job_count">{{ RECORDED_ONLY_NOTE }}</p>
      <p v-if="chart === 'time' && timeline?.unplaced">
        {{ unplacedSentence(timeline.unplaced.job_count, timeline.unplaced.amount) }}
      </p>
    </div>

    <details class="inline-details">
      <summary>Show this chart as a table</summary>
      <div class="table-wrap">
        <table v-if="rows.length">
          <caption class="sr-only">
            {{ chart === "tool" ? "Cost in this period by tool" : "Cost in this period over time" }}
          </caption>
          <thead>
            <tr>
              <th>{{ tableColumn }}</th><th class="num">Jobs</th><th class="num">Cost</th><th>By status</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in rows" :key="row.key">
              <td>{{ row.name }}</td><td class="num">{{ row.jobs }}</td>
              <td class="num">{{ formatCost(row.cost) }}</td><td>{{ row.statuses }}</td>
            </tr>
          </tbody>
        </table>
        <p v-else class="empty">Nothing to show for these filters.</p>
      </div>
    </details>

    <div
      v-show="tooltip.content.value" ref="tooltipElement" class="chart-tip" role="tooltip"
      :style="{ left: `${tooltip.position.value.left}px`, top: `${tooltip.position.value.top}px` }"
    >
      <template v-if="tooltip.content.value">
        <div class="tip-value">{{ tooltip.content.value.value }}</div>
        <div v-for="line in tooltip.content.value.lines" :key="line" class="tip-line">{{ line }}</div>
      </template>
    </div>
  </section>
</template>
