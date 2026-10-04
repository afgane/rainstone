<script setup lang="ts">
import { computed, ref, watch } from "vue";
import type { CostBucket, CostPiece, CostTimeline } from "../../api";
import { periodSlots, type AxisSlot } from "../../chart/axis";
import { bucketLabel, MINIMUM_VERTICAL, niceScale, PLOT_HEIGHT } from "../../chart/layout";
import TimeFrame from "../chart/TimeFrame.vue";
import { useChartTooltip, type TooltipContent } from "../runs/useChartTooltip";
import type { JobWindow } from "../../jobsView";
import {
  EXPLORE_PERIOD, formatCost, INDIVIDUAL_BLOCK, jobOutcomes, OVERVIEW_CHART_HINT, OVERVIEW_CHART_SCOPE,
  OVERVIEW_CHART_TITLE, pieceCounts, unplacedSentence, WORKFLOW_BLOCK,
} from "../../vocabulary";

const props = defineProps<{
  timeline: CostTimeline;
  timezone: string;
  asOf: string | null;
  periodFrom: string;
  periodTo: string;
  axisEnd: string;
  /** The block whose drawer is open, as `<interval start>|<category>`; empty for none. */
  openBlock?: string;
}>();
const emit = defineEmits<{
  // One block's exact interval, clipped to the period, and the category it draws.
  block: [category: CostPiece["kind"], window: JobWindow, opener: HTMLElement];
  explore: [opener: HTMLElement];
}>();

const tooltipElement = ref<HTMLElement | null>(null);
const tooltip = useChartTooltip(tooltipElement);

const unit = computed(() => props.timeline.bucket);
// The axis spans the whole period, so a day without cost still has its column.
const slots = computed<AxisSlot[]>(() => periodSlots(unit.value, props.timeline.axis, {
  from: props.periodFrom, to: props.periodTo, axisEnd: props.axisEnd,
}, props.timezone));
const byStart = computed(() => new Map(
  props.timeline.buckets.map(bucket => [Date.parse(bucket.from), bucket] as const)));
const scale = computed(() => niceScale(
  Math.max(0, ...props.timeline.buckets.map(bucket => Number(bucket.amount) || 0))));

const columns = computed(() => slots.value.map(slot => {
  const bucket = byStart.value.get(slot.from) ?? null;
  // At most two blocks, so none is folded away: a small one keeps a minimum height.
  const blocks = (bucket?.pieces ?? []).filter(piece => Number(piece.amount) > 0).map(piece => ({
    piece, size: Math.max(MINIMUM_VERTICAL, Number(piece.amount) / scale.value.max * PLOT_HEIGHT),
  }));
  return { slot, bucket, blocks, label: bucketLabel(unit.value, slot.from, slot.to, props.timezone) };
}));

const hasCost = computed(() => props.timeline.buckets.some(bucket => bucket.pieces.length > 0));
const anyIndividual = computed(() => props.timeline.buckets.some(
  bucket => bucket.pieces.some(piece => piece.kind === "individual")));

function pieceOf(bucket: CostBucket, key: string): CostPiece | undefined {
  return bucket.pieces.find(piece => piece.key === key);
}

const BLOCK_NAMES: Record<CostPiece["kind"], string> = { runs: WORKFLOW_BLOCK, individual: INDIVIDUAL_BLOCK };

function pieceContent(piece: CostPiece, label: string): TooltipContent {
  const named = jobOutcomes(piece.failed, piece.running);
  return {
    value: formatCost(piece.amount),
    lines: [
      BLOCK_NAMES[piece.kind], label, pieceCounts(piece.run_count, piece.job_count),
      ...(named ? [named] : []),
      piece.kind === "runs" ? "Select to see the runs" : "Select to see the jobs",
    ],
  };
}

function pieceTip(event: MouseEvent, bucket: CostBucket, key: string, label: string) {
  const piece = pieceOf(bucket, key);
  if (piece) void tooltip.show(pieceContent(piece, label), event.clientX, event.clientY);
}

function focusPiece(event: FocusEvent, piece: CostPiece, label: string) {
  const box = (event.target as HTMLElement).getBoundingClientRect();
  void tooltip.show(pieceContent(piece, label), box.left, box.bottom);
}

function pieceLabel(piece: CostPiece, label: string): string {
  return `${BLOCK_NAMES[piece.kind]}, ${label}: ${formatCost(piece.amount)}, `
    + `${pieceCounts(piece.run_count, piece.job_count)}. Select to see what ran.`;
}

function columnTip(event: MouseEvent, column: (typeof columns.value)[number]) {
  const bucket = column.bucket;
  if (!bucket) return;
  const named = jobOutcomes(bucket.failed_job_count, bucket.running_job_count);
  void tooltip.show({
    value: formatCost(bucket.amount),
    lines: [
      column.label, pieceCounts(bucket.run_count, bucket.job_count), ...(named ? [named] : []),
    ],
  }, event.clientX, event.clientY);
}

/** A block's interval, kept inside the period so a partial first or last bucket is exact. */
function windowOf(bucket: CostBucket): JobWindow {
  return {
    unit: unit.value,
    from: new Date(Math.max(Date.parse(bucket.from), Date.parse(props.periodFrom))).toISOString(),
    to: new Date(Math.min(Date.parse(bucket.to), Date.parse(props.periodTo))).toISOString(),
  };
}

function open(event: MouseEvent, bucket: CostBucket, piece: CostPiece) {
  emit("block", piece.kind, windowOf(bucket), event.currentTarget as HTMLElement);
}

function isOpen(bucket: CostBucket, piece: CostPiece): boolean {
  if (!props.openBlock) return false;
  const [from, category] = props.openBlock.split("|");
  return category === piece.kind && Date.parse(from) === Date.parse(windowOf(bucket).from);
}

const rows = computed(() => props.timeline.buckets.flatMap(bucket => {
  const label = bucketLabel(
    unit.value, Date.parse(bucket.from), Date.parse(bucket.to), props.timezone);
  return bucket.pieces.map(piece => ({ bucket, piece, label }));
}));

function leave() {
  tooltip.hide();
}
watch(() => props.timeline, leave);
</script>

<template>
  <section
    class="panel chart-panel"
    aria-labelledby="cost-chart-title"
  >
    <div class="panel-heading">
      <div>
        <h2 id="cost-chart-title">{{ OVERVIEW_CHART_TITLE }}</h2>
        <p v-if="hasCost">{{ OVERVIEW_CHART_SCOPE }}</p>
      </div>
      <button
        v-if="hasCost" class="secondary" type="button" data-detail-trigger
        @click="emit('explore', $event.currentTarget as HTMLElement)"
      >
        {{ EXPLORE_PERIOD }}
      </button>
    </div>

    <div
      class="chart"
      :aria-describedby="hasCost ? 'cost-chart-hint' : undefined"
    >
      <div class="chart-region">
        <div v-if="!hasCost" class="chart-empty">No cost was recorded in this period.</div>
        <div v-else class="time-bars">
          <TimeFrame :slots="slots" :unit="unit" :timezone="timezone" :as-of="asOf" :scale="scale">
            <div
              v-for="column in columns"
              :key="column.slot.from"
              class="col overview-col"
              :class="{ empty: !column.bucket }"
              @pointermove="columnTip($event, column)"
              @pointerleave="leave"
            >
              <span class="stack">
                <button
                  v-for="block in column.blocks"
                  :key="block.piece.key"
                  type="button"
                  class="blk"
                  data-detail-trigger
                  :data-kind="block.piece.kind"
                  :aria-label="pieceLabel(block.piece, column.label)"
                  :aria-current="column.bucket && isOpen(column.bucket, block.piece) ? 'true' : undefined"
                  :style="{ height: `${block.size}px` }"
                  @click="column.bucket && open($event, column.bucket, block.piece)"
                  @pointermove.stop="column.bucket && pieceTip($event, column.bucket, block.piece.key, column.label)"
                  @focus="focusPiece($event, block.piece, column.label)"
                  @blur="leave"
                />
              </span>
            </div>
          </TimeFrame>
        </div>
      </div>
    </div>
    <!-- A key and hints for a plot with nothing in it would only confuse. -->
    <div v-if="hasCost" class="chart-foot">
      <span class="key"><i class="sw" data-kind="runs" />{{ WORKFLOW_BLOCK }}</span>
      <span v-if="anyIndividual" class="key"><i class="sw" data-kind="individual" />{{ INDIVIDUAL_BLOCK }}</span>
      <span id="cost-chart-hint">{{ OVERVIEW_CHART_HINT }}</span>
    </div>
    <div
      v-if="timeline.unplaced"
      class="chart-notes"
    >
      <p>{{ unplacedSentence(timeline.unplaced.job_count, timeline.unplaced.amount) }}</p>
    </div>

    <details v-if="hasCost" class="inline-details">
      <summary>Show this chart as a table</summary>
      <div class="table-wrap">
        <table v-if="rows.length">
          <caption class="sr-only">
            Cost in this period by {{ unit }}, for workflow runs and individual jobs
          </caption>
          <thead>
            <tr>
              <th>{{ unit === "hour" ? "Hour" : unit === "week" ? "Week" : "Day" }}</th>
              <th>Work</th>
              <th class="num">
                Cost
              </th>
              <th class="num">
                Runs
              </th>
              <th class="num">
                Jobs
              </th>
              <th>Outcomes</th>
              <th><span class="sr-only">Open</span></th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="row in rows"
              :key="`${row.bucket.from}-${row.piece.key}`"
            >
              <td>{{ row.label }}</td>
              <td>{{ BLOCK_NAMES[row.piece.kind] }}</td>
              <td class="num">
                {{ formatCost(row.piece.amount) }}
              </td>
              <td class="num">
                {{ row.piece.run_count }}
              </td>
              <td class="num">
                {{ row.piece.job_count }}
              </td>
              <td>{{ jobOutcomes(row.piece.failed, row.piece.running) || "None failed or running" }}</td>
              <td>
                <button
                  class="link-button"
                  type="button"
                  data-detail-trigger
                  @click="open($event, row.bucket, row.piece)"
                >
                  {{ row.piece.kind === "runs" ? "See runs" : "See jobs" }}
                </button>
              </td>
            </tr>
          </tbody>
        </table>
        <p
          v-else
          class="empty"
        >
          Nothing to show for this period.
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
