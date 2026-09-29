<script setup lang="ts">
import { computed, ref } from "vue";
import type { RunsView, RunTotals } from "../../api";
import {
  formatCost, RUN_CHART_HINT, STRAGGLE_NOTE, SHARED_JOBS_NOTE, undatedSentence, unplacedSentence,
} from "../../vocabulary";
import TimeBars from "./TimeBars.vue";
import { bucketLabel } from "../../chart/layout";
import { useChartTooltip, type TooltipContent } from "./useChartTooltip";
import WorkflowBars from "./WorkflowBars.vue";
import WorkflowStrip from "./WorkflowStrip.vue";

const props = defineProps<{
  view: RunsView;
  totals: RunTotals;
  chart: "workflow" | "time";
  workflowKey: string;
  focusFrom: string;
  focusTo: string;
  periodFrom: string;
  periodTo: string;
  axisEnd: string;
  periodLabel: string;
  openRunId: string;
  hoverRunId: string;
  timezone: string;
  asOf: string | null;
  undatedJobs: number;
  /** True while the other tab's data is still being fetched. */
  loadingChart: boolean;
}>();
const emit = defineEmits<{
  chart: [kind: "workflow" | "time"];
  workflow: [key: string];
  run: [id: string];
  grouped: [key: string, boundary: { amount: string; runId: string } | null];
  column: [window: { from: string; to: string }];
  hover: [id: string | null];
}>();

const tooltipElement = ref<HTMLElement | null>(null);
const tooltip = useChartTooltip(tooltipElement);
function tip(content: TooltipContent | null, x: number, y: number) {
  if (content) void tooltip.show(content, x, y);
  else tooltip.hide();
}

const hasNotes = computed(() => props.totals.shared_job_count > 0 || straddles.value
  || Boolean(timeline.value?.unplaced) || props.undatedJobs > 0);
const moreInBars = ref(false);
const moreInStrip = ref(false);
const breakdown = computed(() => props.view.breakdown);
const timeline = computed(() => props.view.timeline);
const chosenGroup = computed(() =>
  props.view.strip?.groups.find(group => group.key === props.workflowKey) ?? null);

const heading = computed(() => (props.chart === "workflow"
  ? `Cost in ${props.periodLabel}. Each block is one run; the wider it is, the more it cost.`
  : `Cost by ${timeline.value?.bucket ?? "day"}. Each block is one run; the taller it is, the more it cost.`));
// The time axis is drawn for the whole period even when nothing cost anything in it.
const hasData = computed(() => (props.chart === "workflow"
  ? Boolean(breakdown.value?.groups.length) : Boolean(timeline.value)));
const loaded = computed(() => (props.chart === "workflow" ? Boolean(breakdown.value) : Boolean(timeline.value)));

const statuses = computed(() => {
  const found = new Set<string>();
  if (props.chart === "workflow") {
    for (const group of breakdown.value?.groups ?? []) {
      for (const [status, count] of Object.entries(group.by_status)) if (count) found.add(status);
    }
  } else {
    for (const bucket of timeline.value?.buckets ?? []) {
      for (const [status, count] of Object.entries(bucket.by_status)) if (count) found.add(status);
    }
  }
  return found;
});
const straddles = computed(() => (breakdown.value?.groups ?? []).some(group =>
  group.runs.some(run => run.amount !== run.run_total)));

interface TableRow { name: string; runs: number; cost: string | null; outcomes: string }
const outcomeText = (counts: Record<string, number>) => [
  counts.failed ? `${counts.failed} failed` : "", counts.running ? `${counts.running} still running` : "",
].filter(Boolean).join(", ") || "None failed or running";
const rows = computed<TableRow[]>(() => (props.chart === "workflow"
  ? (breakdown.value?.groups ?? []).map(group => ({
    name: group.name, runs: group.run_count, cost: group.amount, outcomes: outcomeText(group.by_status),
  }))
  : (timeline.value?.buckets ?? []).map(bucket => ({
    name: bucketLabel(
      timeline.value!.bucket, Date.parse(bucket.from), Date.parse(bucket.to), props.timezone,
    ),
    runs: bucket.run_count, cost: bucket.amount, outcomes: outcomeText(bucket.by_status),
  }))));
const tableColumn = computed(() => (props.chart === "workflow" ? "Workflow" : timeline.value?.bucket === "hour" ? "Hour" : timeline.value?.bucket === "week" ? "Week" : "Day"));
const tableCaption = computed(() => (props.chart === "workflow"
  ? "Cost in this period by workflow" : "Cost in this period over time"));

function moveTab(event: KeyboardEvent) {
  if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
  emit("chart", props.chart === "workflow" ? "time" : "workflow");
}
</script>

<template>
  <section
    class="panel chart-panel"
    aria-labelledby="chart-title"
  >
    <div class="panel-heading">
      <div>
        <h2 id="chart-title">
          Where the cost went
        </h2><p>{{ heading }}</p>
      </div>
      <div
        class="tabs"
        role="tablist"
        aria-label="Chart view"
      >
        <button
          id="tab-workflow"
          role="tab"
          type="button"
          aria-controls="chart-body"
          :aria-selected="chart === 'workflow'"
          :tabindex="chart === 'workflow' ? 0 : -1"
          @click="emit('chart', 'workflow')"
          @keydown="moveTab"
        >
          By workflow
        </button>
        <button
          id="tab-time"
          role="tab"
          type="button"
          aria-controls="chart-body"
          :aria-selected="chart === 'time'"
          :tabindex="chart === 'time' ? 0 : -1"
          @click="emit('chart', 'time')"
          @keydown="moveTab"
        >
          Over time
        </button>
      </div>
    </div>

    <div
      id="chart-body"
      class="chart"
      role="tabpanel"
      :aria-labelledby="`tab-${chart}`"
      aria-describedby="chart-hint"
    >
      <div class="chart-region">
        <div
          v-if="!loaded || loadingChart"
          class="chart-empty"
        >
          Loading…
        </div>
        <div
          v-else-if="!hasData"
          class="chart-empty"
        >
          No cost was recorded for these runs.
        </div>
        <WorkflowBars
          v-else-if="chart === 'workflow' && breakdown"
          :groups="breakdown.groups"
          :selected-key="workflowKey"
          :open-run-id="openRunId"
          :hover-run-id="hoverRunId"
          :timezone="timezone"
          @workflow="emit('workflow', $event)"
          @run="emit('run', $event)"
          @grouped="(key, boundary) => emit('grouped', key, boundary)"
          @hover="emit('hover', $event)"
          @tip="tip"
          @more="moreInBars = $event"
        />
        <TimeBars
          v-else-if="chart === 'time' && timeline"
          :timeline="timeline"
          :focus-from="focusFrom"
          :focus-to="focusTo"
          :period-from="periodFrom"
          :period-to="periodTo"
          :axis-end="axisEnd"
          :open-run-id="openRunId"
          :hover-run-id="hoverRunId"
          :timezone="timezone"
          :as-of="asOf"
          @column="emit('column', $event)"
          @run="emit('run', $event)"
          @hover="emit('hover', $event)"
          @tip="tip"
          @more="moreInBars = $event"
        />
      </div>
      <WorkflowStrip
        :group="chosenGroup"
        :open-run-id="openRunId"
        :hover-run-id="hoverRunId"
        :timezone="timezone"
        @run="emit('run', $event)"
        @grouped="(key, boundary) => emit('grouped', key, boundary)"
        @hover="emit('hover', $event)"
        @tip="tip"
        @more="moreInStrip = $event"
      />
    </div>
    <p
      id="chart-hint"
      class="sr-only"
    >
      {{ RUN_CHART_HINT }}
    </p>

    <div class="chart-foot">
      <span class="key"><i
        class="sw"
        data-status="completed"
      />Completed run</span>
      <span
        v-if="statuses.has('failed')"
        class="key"
      ><i
        class="sw"
        data-status="failed"
      />Failed run</span>
      <span
        v-if="statuses.has('running')"
        class="key"
      >
        <i
          class="sw"
          data-status="running"
        />Still running, cost so far
      </span>
      <span
        v-if="moreInBars || moreInStrip"
        class="key"
      ><i class="sw more" />Smaller runs, grouped</span>
      <span>Select a block to open a run.</span>
    </div>
    <div v-if="hasNotes" class="chart-notes">
      <p v-if="totals.shared_job_count > 0">
        {{ SHARED_JOBS_NOTE }}.
      </p>
      <p v-if="straddles">
        {{ STRAGGLE_NOTE }}
      </p>
      <p v-if="timeline?.unplaced">
        {{ unplacedSentence(timeline.unplaced.job_count, timeline.unplaced.amount) }}
      </p>
      <p v-if="undatedJobs">
        {{ undatedSentence(undatedJobs) }}
      </p>
    </div>

    <details class="inline-details">
      <summary>Show this chart as a table</summary>
      <div class="table-wrap">
        <table v-if="rows.length">
          <caption class="sr-only">
            {{ tableCaption }}
          </caption>
          <thead>
            <tr>
              <th>{{ tableColumn }}</th><th class="num">
                Runs
              </th><th class="num">
                Cost
              </th><th>Outcomes</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="row in rows"
              :key="row.name"
            >
              <td>{{ row.name }}</td><td class="num">
                {{ row.runs }}
              </td>
              <td class="num">
                {{ formatCost(row.cost) }}
              </td><td>{{ row.outcomes }}</td>
            </tr>
          </tbody>
        </table>
        <p
          v-else
          class="empty"
        >
          Nothing to show for these filters.
        </p>
        <p
          v-if="totals.shared_job_count > 0"
          class="table-note"
        >
          {{ SHARED_JOBS_NOTE }}.
        </p>
      </div>
    </details>

    <div
      v-show="tooltip.content.value"
      ref="tooltipElement"
      class="chart-tip"
      role="tooltip"
      :style="{ left: `${tooltip.position.value.left}px`, top: `${tooltip.position.value.top}px` }"
    >
      <template v-if="tooltip.content.value">
        <div class="tip-value">
          {{ tooltip.content.value.value }}
        </div>
        <div
          v-for="line in tooltip.content.value.lines"
          :key="line"
          class="tip-line"
        >
          {{ line }}
        </div>
      </template>
    </div>
  </section>
</template>
