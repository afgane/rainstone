<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from "vue";
import type { ServerActivity, ServerJobInterval, ServerJobStep } from "../api";
import { jobMarks } from "../serverActivity";
import { formatDateTime, formatDuration, pluralize } from "../vocabulary";

const props = defineProps<{
  activity: ServerActivity | null;
  startedAt: string | null;
  recordedThrough: string | null;
  timezone: string;
  duration: string;
}>();
const tableOpen = ref(false);
function toggleTable(event: Event) {
  tableOpen.value = (event.target as HTMLDetailsElement).open;
}
const width = ref(800);
let observed: HTMLElement | null = null;
const observer = new ResizeObserver(entries => {
  width.value = Math.max(100, entries[0].contentRect.width);
});
function measure(element: unknown) {
  const target = element instanceof HTMLElement ? element : null;
  if (observed === target) return;
  if (observed) observer.unobserve(observed);
  observed = target;
  if (observed) observer.observe(observed);
}
onBeforeUnmount(() => observer.disconnect());

const marks = computed(() => jobMarks(props.activity, width.value));
const lanes = computed(() => marks.value.reduce((maximum, mark) => Math.max(maximum, mark.lane + 1), 0));
const stepped = computed(() => props.activity?.kind === "steps" || lanes.value > 10);
const height = computed(() => stepped.value ? 140 : Math.max(60, lanes.value * 12 + 20));
const baseline = computed(() => height.value - 8);
const maximum = computed(() => Math.max(0, ...(props.activity?.steps.map(step => step.count) ?? [])));
const points = computed(() => {
  const activity = props.activity;
  if (!activity || !stepped.value) return "";
  const start = Date.parse(activity.from), span = Date.parse(activity.to) - start;
  if (span <= 0) return "";
  return activity.steps.flatMap(step => {
    const y = baseline.value - step.count / Math.max(1, maximum.value) * 100;
    return [step.from, step.to].map(instant => `${4 + (Date.parse(instant) - start) / span * (width.value - 8)},${y}`);
  }).join(" ");
});
const tableSteps = computed(() => props.activity?.steps.filter(step => step.count > 0) ?? []);
function recordedDuration(interval: ServerJobInterval): string {
  const seconds = (Date.parse(interval.to) - Date.parse(interval.from)) / 1000;
  return seconds < 60 ? `${Number(seconds.toFixed(1))} sec` : formatDuration(seconds);
}
function jobLabel(interval: ServerJobInterval): string {
  return `Job ${interval.source_id}: ${formatDateTime(interval.from, props.timezone)} to ${formatDateTime(interval.to, props.timezone)} · ${recordedDuration(interval)}${interval.running ? " (through the last observation)" : ""}`;
}
function stepLabel(step: ServerJobStep): string {
  return `${pluralize(step.count, "job")} running: ${formatDateTime(step.from, props.timezone)} to ${formatDateTime(step.to, props.timezone)}`;
}
</script>

<template>
  <div class="server-activity" :data-kind="activity?.kind === 'hidden' ? 'hidden' : stepped ? 'steps' : 'dots'">
    <div v-if="activity" class="activity-caption">
      <span>{{ pluralize(activity.job_count, 'recorded job') }}</span>
      <span v-if="stepped">Jobs running · peak {{ maximum }}</span>
    </div>
    <div :ref="measure">
      <svg class="server-activity-svg" :viewBox="`0 0 ${width} ${height}`" :height="height" aria-hidden="true">
        <template v-if="stepped && points">
          <polygon :points="`4,${baseline} ${points} ${width - 4},${baseline}`" class="activity-area" />
          <polyline :points="points" class="activity-step" />
        </template>
        <template v-else-if="activity?.kind === 'dots'">
          <rect
            v-for="(mark, index) in marks" :key="index" class="activity-dot"
            :x="mark.x" :y="baseline - 15 - mark.lane * 12" :width="mark.width" height="7" rx="3.5"
          ><title>{{ jobLabel(mark.interval) }}</title></rect>
        </template>
        <line x1="4" :x2="width - 4" :y1="baseline" :y2="baseline" class="activity-baseline" />
        <circle cx="4" :cy="baseline" r="4" class="activity-endpoint" />
        <circle :cx="width - 4" :cy="baseline" r="4" class="activity-endpoint" />
      </svg>
    </div>
    <ol class="session-timeline" aria-label="Recorded server session">
      <li>
        <span>Started</span>
        <strong>{{ startedAt ? formatDateTime(startedAt, timezone) : 'Start time unavailable' }}</strong>
      </li>
      <li class="session-duration">
        <p class="server-duration"><span>Time running</span><strong>{{ duration }}</strong></p>
      </li>
      <li>
        <span>Recorded through</span>
        <strong>{{ recordedThrough ? formatDateTime(recordedThrough, timezone) : 'No observation available' }}</strong>
      </li>
    </ol>
    <p v-if="activity?.kind === 'hidden'" class="activity-scale-note">Job activity is not plotted at this scale.</p>
    <details v-else-if="activity?.job_count" class="inline-details activity-table" @toggle="toggleTable">
      <summary>Show job activity as a table</summary>
      <div v-if="tableOpen" class="table-wrap" tabindex="0" role="region" :aria-label="stepped ? 'Concurrent recorded jobs' : 'Recorded jobs'">
        <table v-if="!stepped">
          <caption class="sr-only">Recorded job execution within this server session</caption>
          <thead><tr><th>Job</th><th>From</th><th>Through</th><th>Recorded duration</th></tr></thead>
          <tbody>
            <tr v-for="(interval, index) in activity.intervals" :key="index">
              <td>Job {{ interval.source_id }}</td>
              <td>{{ formatDateTime(interval.from, timezone) }}</td>
              <td>{{ formatDateTime(interval.to, timezone) }}<small v-if="interval.running">Through the last observation</small></td>
              <td>{{ recordedDuration(interval) }}</td>
            </tr>
          </tbody>
        </table>
        <table v-else>
          <caption class="sr-only">Concurrent recorded jobs within this server session</caption>
          <thead><tr><th>From</th><th>Through</th><th>Jobs running</th></tr></thead>
          <tbody>
            <tr v-for="(step, index) in tableSteps" :key="index" :title="stepLabel(step)">
              <td>{{ formatDateTime(step.from, timezone) }}</td>
              <td>{{ formatDateTime(step.to, timezone) }}</td><td>{{ step.count }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </details>
  </div>
</template>
