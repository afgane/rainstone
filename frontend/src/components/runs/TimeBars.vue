<script setup lang="ts">
import { computed, watch, watchEffect } from "vue";
import type { Timeline, TimelineBucket } from "../../api";
import { periodSlots, type AxisSlot } from "../../chart/axis";
import {
  bucketLabel, layoutSegments, MINIMUM_VERTICAL, niceScale, PLOT_HEIGHT, type Segment,
} from "../../chart/layout";
import { formatCost, pluralize } from "../../vocabulary";
import TimeFrame from "../chart/TimeFrame.vue";
import { groupedTooltip, runTooltip } from "./tooltips";
import type { TooltipContent } from "./useChartTooltip";

const props = defineProps<{
  timeline: Timeline;
  focusFrom: string;
  focusTo: string;
  /** The period's ends, which a partial first or last bucket is clamped to. */
  periodFrom: string;
  periodTo: string;
  /** Where the axis ends when a still-open week or month should be drawn whole. */
  axisEnd: string;
  openRunId: string;
  hoverRunId: string;
  timezone: string;
  asOf: string | null;
}>();
const emit = defineEmits<{
  column: [window: { from: string; to: string }];
  run: [id: string];
  hover: [id: string | null];
  tip: [content: TooltipContent | null, x: number, y: number];
  more: [present: boolean];
}>();

const unit = computed(() => props.timeline.bucket);
// The axis spans the whole period, so a day without cost still has its column.
const slots = computed<AxisSlot[]>(() => periodSlots(unit.value, props.timeline.axis, {
  from: props.periodFrom, to: props.periodTo, axisEnd: props.axisEnd,
}, props.timezone));
const byStart = computed(() => new Map(
  props.timeline.buckets.map(bucket => [Date.parse(bucket.from), bucket] as const)));
const maxAmount = computed(() =>
  Math.max(0, ...props.timeline.buckets.map(bucket => Number(bucket.amount) || 0)));
const scale = computed(() => niceScale(maxAmount.value));

const periodStart = computed(() => Date.parse(props.periodFrom));
const periodEnd = computed(() => Date.parse(props.periodTo));
// A partial first or last bucket selects only the part inside the period.
function windowOf(slot: AxisSlot) {
  return { from: Math.max(slot.from, periodStart.value), to: Math.min(slot.to, periodEnd.value) };
}
function isSelected(slot: AxisSlot): boolean {
  if (!props.focusFrom) return false;
  const window = windowOf(slot);
  return window.from === Date.parse(props.focusFrom) && window.to === Date.parse(props.focusTo);
}

const columns = computed(() => slots.value.map(slot => {
  const bucket = byStart.value.get(slot.from) ?? null;
  const total = bucket ? Number(bucket.amount) || 0 : 0;
  const segments: Segment[] = bucket ? layoutSegments(
    bucket.pieces.map(piece => ({
      id: piece.id, drawn: Number(piece.amount), amount: piece.amount, status: piece.status,
    })),
    bucket.remainder, total / scale.value.max * PLOT_HEIGHT, MINIMUM_VERTICAL,
    { selectableBoundary: false },
  ) : [];
  const label = bucketLabel(unit.value, slot.from, slot.to, props.timezone);
  return { slot, bucket, segments, label, selected: isSelected(slot) };
}));


function pieceTip(event: PointerEvent, bucket: TimelineBucket, id: string) {
  const piece = bucket.pieces.find(candidate => candidate.id === id);
  const run = props.timeline.runs[id];
  if (!piece || !run) return;
  emit("hover", id);
  emit("tip", runTooltip({
    workflow_name: run.workflow_name, started_at: run.started_at,
    duration_seconds: run.duration_seconds, status: piece.status, amount: run.amount,
    run_total: run.run_total, shared_job_count: run.shared_job_count,
  }, props.timezone, piece.amount), event.clientX, event.clientY);
}

function columnTip(x: number, y: number, column: (typeof columns.value)[number]) {
  const bucket = column.bucket;
  if (!bucket) return;
  emit("tip", {
    value: formatCost(bucket.amount),
    lines: [
      column.label, pluralize(bucket.run_count, "run"),
      column.selected ? "Select again to clear" : "Select to filter the list",
    ],
  }, x, y);
}

function groupedTip(event: PointerEvent, segment: Extract<Segment, { kind: "more" }>) {
  emit("tip", groupedTooltip(
    segment.count, segment.drawn, segment.failed, segment.running, "Select to filter the list",
  ), event.clientX, event.clientY);
}

function leave() {
  emit("hover", null);
  emit("tip", null, 0, 0);
}

function focusColumn(event: FocusEvent, column: (typeof columns.value)[number]) {
  const box = (event.target as HTMLElement).getBoundingClientRect();
  columnTip(box.left, box.bottom - 18, column);
}

watch(() => props.timeline, leave);
watchEffect(() => emit("more", columns.value.some(column => column.segments.some(segment => segment.kind === "more"))));
</script>

<template>
  <div class="time-bars">
    <TimeFrame
      :slots="slots" :unit="unit" :timezone="timezone" :as-of="asOf" :scale="scale"
      :empty="timeline.buckets.length ? '' : 'No cost was recorded for these runs.'"
    >
      <component
        :is="column.bucket ? 'button' : 'div'"
        v-for="column in columns"
        :key="column.slot.from"
        class="col"
        :class="{ empty: !column.bucket }"
        :type="column.bucket ? 'button' : undefined"
        :aria-pressed="column.bucket ? column.selected : undefined"
        :aria-label="column.bucket
          ? `${column.label}: ${formatCost(column.bucket.amount)}, ${pluralize(column.bucket.run_count, 'run')}. Select to filter the list.`
          : undefined"
        @click="column.bucket && emit('column', {
          from: new Date(windowOf(column.slot).from).toISOString(),
          to: new Date(windowOf(column.slot).to).toISOString(),
        })"
        @pointermove="column.bucket && columnTip($event.clientX, $event.clientY, column)"
        @pointerleave="leave"
        @focus="column.bucket && focusColumn($event, column)"
        @blur="leave"
      >
        <span class="stack">
          <template
            v-for="segment in column.segments"
            :key="segment.kind === 'run' ? segment.run.id : 'more'"
          >
            <span
              v-if="segment.kind === 'run'"
              class="blk"
              aria-hidden="true"
              data-detail-trigger
              :data-run-id="segment.run.id"
              :data-status="segment.run.status"
              :class="{ hl: hoverRunId === segment.run.id, sel: openRunId === segment.run.id }"
              :style="{ height: `${segment.size}px` }"
              @click.stop="emit('run', segment.run.id)"
              @pointermove.stop="column.bucket && pieceTip($event, column.bucket, segment.run.id)"
            />
            <span
              v-else
              class="blk more"
              aria-hidden="true"
              :style="{ height: `${segment.size}px` }"
              @pointermove.stop="groupedTip($event, segment)"
            />
          </template>
        </span>
      </component>
    </TimeFrame>
  </div>
</template>
