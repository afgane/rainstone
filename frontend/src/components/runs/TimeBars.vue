<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch, watchEffect } from "vue";
import type { Timeline, TimelineBucket } from "../../api";
import { axisSlots, axisText, type AxisSlot } from "../../chart/axis";
import {
  axisLabelStep, bucketLabel, layoutSegments, MINIMUM_VERTICAL, niceScale, type Segment,
} from "../../chart/layout";
import { formatAxisCost, formatCost, pluralize } from "../../vocabulary";
import { groupedTooltip, runTooltip } from "./tooltips";
import type { TooltipContent } from "./useChartTooltip";

const PLOT_HEIGHT = 200;
// The y axis and the plot's own padding leave this much of the chart unusable.
const AXIS_WIDTH = 48;

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

const width = ref(0);
let observed: HTMLElement | null = null;
const observer = new ResizeObserver(entries => {
  width.value = Math.round(entries[0].contentRect.width);
});
function measure(element: unknown) {
  const target = element instanceof HTMLElement ? element : null;
  if (target === observed) return;
  if (observed) observer.unobserve(observed);
  observed = target;
  if (target) observer.observe(target);
}
onBeforeUnmount(() => observer.disconnect());

const unit = computed(() => props.timeline.bucket);
// The axis spans the whole period, so a day without cost still has its column.
const slots = computed<AxisSlot[]>(() => {
  const found = props.timeline.axis ?? { from: props.periodFrom, to: props.periodTo };
  const end = Date.parse(props.axisEnd) > Date.parse(found.to) ? props.axisEnd : found.to;
  return axisSlots(unit.value, { from: found.from, to: end }, props.timezone);
});
const byStart = computed(() => new Map(
  props.timeline.buckets.map(bucket => [Date.parse(bucket.from), bucket] as const)));
const maxAmount = computed(() =>
  Math.max(0, ...props.timeline.buckets.map(bucket => Number(bucket.amount) || 0)));
const scale = computed(() => niceScale(maxAmount.value));
const ticks = computed(() => {
  const found: number[] = [];
  for (let value = 0; value <= scale.value.max + 1e-9; value += scale.value.step) found.push(value);
  return found;
});

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

const slotWidth = computed(() => Math.max(1, (width.value - AXIS_WIDTH - 40) / Math.max(1, slots.value.length)));
const labelStep = computed(() => axisLabelStep(unit.value, slotWidth.value));
const asOfTime = computed(() => (props.asOf ? Date.parse(props.asOf) : Infinity));

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
    <div class="tplot">
      <div class="yaxis">
        <span
          v-for="tick in ticks"
          :key="tick"
          class="ytick"
          :style="{ bottom: `${tick / scale.max * 100}%` }"
        >{{ formatAxisCost(tick) }}</span>
      </div>
      <div
        :ref="measure"
        class="plot"
      >
        <p
          v-if="!timeline.buckets.length"
          class="plot-empty"
        >
          No cost was recorded for these runs.
        </p>
        <div
          v-for="tick in ticks.slice(1)"
          :key="`grid-${tick}`"
          class="grid"
          :style="{ bottom: `${tick / scale.max * 100}%` }"
        />
        <div class="cols">
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
        </div>
      </div>
      <div class="xaxis">
        <div
          v-for="(column, index) in columns"
          :key="column.slot.from"
          class="xl"
          :class="{ future: column.slot.from >= asOfTime }"
        >
          <span v-if="index % labelStep === 0">{{ axisText(unit, column.slot.from, timezone) }}</span>
        </div>
      </div>
    </div>
  </div>
</template>
