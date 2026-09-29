<script setup lang="ts">
import { computed } from "vue";
import type { CostTimeline, GroupItem, Invocation, Summary } from "../api";
import { offsetBoundary, periodOf, type ReportState } from "../api";
import { periodAxisEnd } from "../chart/axis";
import { describePeriod, exclusiveEnd } from "../periods";
import OverviewCostChart from "./overview/OverviewCostChart.vue";
import OverviewFigures from "./overview/OverviewFigures.vue";
import ServerLaunchFigures from "./ServerLaunchFigures.vue";
import {
  formatCost, formatDate, pluralize, runStatusLabel, SERVER_EXPLANATION,
  undatedSentence,
} from "../vocabulary";

const props = defineProps<{
  state: ReportState;
  summary: Summary;
  timeline: CostTimeline;
  tools: GroupItem[];
  runs: Invocation[];
}>();
const emit = defineEmits<{
  view: [view: "runs" | "tool-runs" | "tools" | "daily" | "server"];
  run: [id: string, opener: HTMLElement];
  runs: [target: { from: string; to: string }];
  jobs: [target: { from: string; to: string }];
  "demo-period": [];
}>();

const period = computed(() => periodOf(props.state));
const periodFrom = computed(() => offsetBoundary(period.value.fromDate, props.state.timezone));
const periodTo = computed(() => offsetBoundary(exclusiveEnd(period.value), props.state.timezone));
const axisEnd = computed(() => periodAxisEnd(period.value, props.state.timezone));
const hasNotices = computed(() => Boolean(
  (!props.summary.job_count && props.summary.demo_period) || props.summary.undated?.job_count
));
// The server ranks the period's runs by cost, so the top four are the period's, not a page's.
const topRuns = computed(() => props.runs.slice(0, 4));
const topTools = computed(() =>
  [...props.tools]
    .sort((a, b) => Number(b.amount || 0) - Number(a.amount || 0))
    .slice(0, 4));
</script>

<template>
  <OverviewFigures
    :summary="summary"
    :workload="timeline.totals"
    :period-text="describePeriod(period, state.timezone)"
  />
  <div
    v-if="hasNotices"
    class="overview-notes"
  >
    <p v-if="!summary.job_count && summary.demo_period">
      {{ summary.imported_snapshot ? "This imported snapshot's data was recorded" : "This demonstration's data was recorded" }}
      {{ formatDate(summary.demo_period.from, state.timezone) }} –
      {{ formatDate(summary.demo_period.to, state.timezone) }}.
      <button
        class="link-button"
        @click="emit('demo-period')"
      >
        Show that period
      </button>
    </p>
    <p v-if="summary.undated?.job_count">
      {{ undatedSentence(summary.undated.job_count) }}
      <button
        class="link-button"
        @click="emit('view', 'tool-runs')"
      >
        See them
      </button>
    </p>
  </div>

  <OverviewCostChart
    :timeline="timeline"
    :timezone="state.timezone"
    :as-of="summary.as_of"
    :period-from="periodFrom"
    :period-to="periodTo"
    :axis-end="axisEnd"
    @runs="emit('runs', $event)"
    @jobs="emit('jobs', $event)"
    @daily="emit('view', 'daily')"
  />

  <div class="overview-columns">
    <section class="panel">
      <div class="panel-heading">
        <div><h2>Workflow runs</h2><p>Your most expensive runs in this period.</p></div>
        <button
          class="link-button"
          @click="emit('view', 'runs')"
        >
          See all runs
        </button>
      </div>
      <div
        v-if="!topRuns.length"
        class="empty"
      >
        No workflow runs in this period.
      </div>
      <button
        v-for="run in topRuns"
        :key="run.id"
        class="rank-row"
        data-detail-trigger
        @click="emit('run', run.id, $event.currentTarget as HTMLElement)"
      >
        <span>
          <strong>{{ run.workflow_name }}</strong>
          <small>{{ formatDate(run.started_at, state.timezone) }} · {{ runStatusLabel(run.run_status) }}</small>
        </span>
        <span class="rank-amount">{{ formatCost(run.amount) }}</span>
      </button>
    </section>

    <section class="panel">
      <div class="panel-heading">
        <div><h2>Tools</h2><p>Where most of that cost came from.</p></div>
        <button
          class="link-button"
          @click="emit('view', 'tools')"
        >
          See all tools
        </button>
      </div>
      <div
        v-if="!topTools.length"
        class="empty"
      >
        No jobs in this period.
      </div>
      <button
        v-for="tool in topTools"
        :key="`${tool.tool_id}@${tool.tool_version}`"
        class="rank-row"
        @click="emit('view', 'tools')"
      >
        <span>
          <strong>{{ tool.tool_name || tool.tool_id }}</strong>
          <small>{{ tool.tool_version || "Unversioned" }} · {{ pluralize(tool.job_count, "job") }}</small>
        </span>
        <span class="rank-amount">{{ formatCost(tool.amount) }}</span>
      </button>
    </section>
  </div>

  <section
    v-if="summary.can_view_infrastructure"
    class="panel quiet"
  >
    <div class="panel-heading">
      <div><h2>Galaxy server compute cost</h2><p>{{ SERVER_EXPLANATION }}</p></div>
      <button
        class="link-button"
        @click="emit('view', 'server')"
      >
        Server details
      </button>
    </div>
    <ServerLaunchFigures
      :launch="summary.current_launch"
      :timezone="state.timezone"
    />
  </section>
</template>
