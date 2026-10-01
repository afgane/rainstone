<script setup lang="ts">
import { computed, watch } from "vue";
import type { JobTimeline } from "../../api";
import { periodSlots, type AxisSlot } from "../../chart/axis";
import { bucketLabel, MINIMUM_VERTICAL, niceScale, PLOT_HEIGHT } from "../../chart/layout";
import { costShares, type JobWindow } from "../../jobsView";
import { formatCost, needsCostData, pluralize, statusLine } from "../../vocabulary";
import TimeFrame from "../chart/TimeFrame.vue";
import type { TooltipContent } from "../runs/useChartTooltip";

// Columns stack their status pieces with a hairline between them.
const STATUS_GAP = 1;

const props = defineProps<{
  timeline: JobTimeline;
  /** The period's ends, which a partial first or last bucket is clipped to. */
  periodFrom: string;
  periodTo: string;
  /** Where the axis ends when a still-open week or month should be drawn whole. */
  axisEnd: string;
  /** The start of the interval whose drawer is open, so its column reads as selected. */
  openFrom: string;
  timezone: string;
  asOf: string | null;
}>();
const emit = defineEmits<{
  window: [window: JobWindow, opener: HTMLElement];
  tip: [content: TooltipContent | null, x: number, y: number];
}>();

const unit = computed(() => props.timeline.bucket);
const slots = computed<AxisSlot[]>(() => periodSlots(unit.value, props.timeline.axis, {
  from: props.periodFrom, to: props.periodTo, axisEnd: props.axisEnd,
}, props.timezone));
const byStart = computed(() => new Map(
  props.timeline.buckets.map(bucket => [Date.parse(bucket.from), bucket] as const)));
const scale = computed(() => niceScale(
  Math.max(0, ...props.timeline.buckets.map(bucket => Number(bucket.amount) || 0))));
const periodStart = computed(() => Date.parse(props.periodFrom));
const periodEnd = computed(() => Date.parse(props.periodTo));
const asOfTime = computed(() => (props.asOf ? Date.parse(props.asOf) : Infinity));

/**
 * A column's state decides what it says and whether it can be opened. An
 * interval after the period, or after the report's snapshot, has not happened
 * as far as this report knows, so it is neither $0 nor openable.
 */
type ColumnState = "cost" | "zero" | "unavailable" | "empty" | "future";

const columns = computed(() => slots.value.map(slot => {
  const bucket = byStart.value.get(slot.from) ?? null;
  const state: ColumnState = slot.from >= periodEnd.value || slot.from >= asOfTime.value ? "future"
    : !bucket ? "empty" : bucket.amount === null ? "unavailable" : Number(bucket.amount) > 0 ? "cost" : "zero";
  const height = state === "cost"
    ? Math.max(MINIMUM_VERTICAL, Number(bucket!.amount) / scale.value.max * PLOT_HEIGHT) : 0;
  const shares = bucket ? costShares(bucket.by_status) : [];
  const drawable = Math.max(0, height - STATUS_GAP * (shares.length - 1));
  const window: JobWindow = {
    unit: unit.value,
    from: new Date(Math.max(slot.from, periodStart.value)).toISOString(),
    to: new Date(Math.min(slot.to, periodEnd.value)).toISOString(),
  };
  return {
    slot, bucket, state, window,
    label: bucketLabel(unit.value, slot.from, slot.to, props.timezone),
    segments: shares.map(({ piece, share }) => ({ piece, size: drawable * share })),
    open: props.openFrom !== "" && Date.parse(props.openFrom) === Date.parse(window.from),
  };
}));
type Column = (typeof columns.value)[number];

function summary(column: Column): string {
  const bucket = column.bucket;
  if (column.state === "future") return `${column.label}: not reached yet`;
  if (!bucket) return `${column.label}: no jobs had compute`;
  const lines = [
    `${column.label}: ${formatCost(bucket.amount)}`, pluralize(bucket.job_count, "job"),
    ...bucket.by_status.map(statusLine),
    bucket.incomplete_job_count ? needsCostData(bucket.incomplete_job_count, "job") : "",
  ];
  return lines.filter(Boolean).join(". ");
}

function tipFor(column: Column): TooltipContent {
  const bucket = column.bucket;
  if (column.state === "future") return { value: column.label, lines: ["Not reached yet"] };
  if (!bucket) return { value: formatCost(null), lines: [column.label, "No jobs had compute", "Select to open"] };
  return {
    value: formatCost(bucket.amount),
    lines: [
      column.label, pluralize(bucket.job_count, "job"), ...bucket.by_status.map(statusLine),
      ...(bucket.incomplete_job_count ? [needsCostData(bucket.incomplete_job_count, "job")] : []),
      ...(bucket.provisional ? ["Includes work still running"] : []),
      "Select to see these jobs",
    ],
  };
}

function point(event: PointerEvent, column: Column) {
  emit("tip", tipFor(column), event.clientX, event.clientY);
}
function focusColumn(event: FocusEvent, column: Column) {
  const box = (event.target as HTMLElement).getBoundingClientRect();
  emit("tip", tipFor(column), box.left, box.bottom - 18);
}
function leave() {
  emit("tip", null, 0, 0);
}
function open(event: MouseEvent, column: Column) {
  if (column.state !== "future") emit("window", column.window, event.currentTarget as HTMLElement);
}
watch(() => props.timeline, leave);
</script>

<template>
  <div class="time-bars">
    <TimeFrame
      :slots="slots" :unit="unit" :timezone="timezone" :as-of="asOf" :scale="scale"
      :empty="timeline.buckets.length ? '' : 'No job had compute in this period.'"
    >
      <component
        :is="column.state === 'future' ? 'div' : 'button'"
        v-for="column in columns" :key="column.slot.from"
        class="col job-col" :class="{ empty: column.state === 'empty', future: column.state === 'future' }"
        :type="column.state === 'future' ? undefined : 'button'"
        :data-detail-trigger="column.state === 'future' ? undefined : ''"
        :data-window-from="column.window.from"
        :aria-current="column.open ? 'true' : undefined"
        :aria-label="column.state === 'future' ? undefined : `${summary(column)}. Select to see these jobs.`"
        :aria-hidden="column.state === 'future' ? 'true' : undefined"
        @click="open($event, column)"
        @pointermove="point($event, column)" @pointerleave="leave"
        @focus="focusColumn($event, column)" @blur="leave"
      >
        <span class="stack status-stack" aria-hidden="true">
          <span
            v-for="segment in column.segments" :key="segment.piece.status" class="blk"
            :data-status="segment.piece.status" :style="{ height: `${segment.size}px` }"
          />
          <span v-if="column.state === 'unavailable'" class="cost-missing" />
        </span>
      </component>
    </TimeFrame>
  </div>
</template>
