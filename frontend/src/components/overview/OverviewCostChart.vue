<script setup lang="ts">
import { computed, ref, watch } from "vue";
import type { CostBucket, CostPiece, CostTimeline } from "../../api";
import { periodSlots, type AxisSlot } from "../../chart/axis";
import { bucketLabel, MINIMUM_VERTICAL, niceScale, PLOT_HEIGHT } from "../../chart/layout";
import TimeFrame from "../chart/TimeFrame.vue";
import { useChartTooltip, type TooltipContent } from "../runs/useChartTooltip";
import {
  costChartTitle, formatCost, jobOutcomes, OVERVIEW_CHART_HINT, pieceCounts,
  unplacedSentence,
} from "../../vocabulary";

const props = defineProps<{
  timeline: CostTimeline;
  timezone: string;
  asOf: string | null;
  periodFrom: string;
  periodTo: string;
  axisEnd: string;
}>();
const emit = defineEmits<{
  runs: [target: { from: string; to: string }];
  jobs: [target: { from: string; to: string }];
  daily: [];
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

function pieceTip(event: MouseEvent, bucket: CostBucket, key: string, label: string) {
  const piece = pieceOf(bucket, key);
  if (!piece) return;
  const named = jobOutcomes(piece.failed, piece.running);
  const content: TooltipContent = {
    value: formatCost(piece.amount),
    lines: [
      piece.name, label, pieceCounts(piece.run_count, piece.job_count),
      ...(named ? [named] : []),
      piece.kind === "runs" ? "Select to see the runs" : "Select to see the jobs",
    ],
  };
  void tooltip.show(content, event.clientX, event.clientY);
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

function open(bucket: CostBucket, piece: CostPiece) {
  const target = { from: bucket.from, to: bucket.to };
  if (piece.kind === "runs") emit("runs", target);
  else emit("jobs", target);
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
        <h2 id="cost-chart-title">
          {{ costChartTitle(unit) }}
        </h2>
        <p>
          Each block is all the workflow runs together, or the jobs outside any; the taller, the
          more it cost.
        </p>
      </div>
      <button
        class="link-button"
        type="button"
        @click="emit('daily')"
      >
        View daily details
      </button>
    </div>

    <div
      class="chart"
      aria-describedby="cost-chart-hint"
    >
      <div class="chart-region">
        <div class="time-bars">
          <TimeFrame
            :slots="slots" :unit="unit" :timezone="timezone" :as-of="asOf" :scale="scale"
            :empty="hasCost ? '' : 'No cost was recorded in this period.'"
          >
            <div
              v-for="column in columns"
              :key="column.slot.from"
              class="col overview-col"
              :class="{ empty: !column.bucket }"
              @pointermove="columnTip($event, column)"
              @pointerleave="leave"
            >
              <span class="stack">
                <span
                  v-for="block in column.blocks"
                  :key="block.piece.key"
                  class="blk"
                  aria-hidden="true"
                  :data-kind="block.piece.kind"
                  :style="{ height: `${block.size}px` }"
                  @click="column.bucket && open(column.bucket, block.piece)"
                  @pointermove.stop="column.bucket && pieceTip($event, column.bucket, block.piece.key, column.label)"
                />
              </span>
            </div>
          </TimeFrame>
        </div>
      </div>
    </div>
    <p
      id="cost-chart-hint"
      class="sr-only"
    >
      {{ OVERVIEW_CHART_HINT }}
    </p>

    <div class="chart-foot">
      <span class="key"><i
        class="sw"
        data-kind="runs"
      />Workflow runs</span>
      <span
        v-if="anyIndividual"
        class="key"
      ><i
        class="sw"
        data-kind="individual"
      />Jobs outside any workflow</span>
      <span>Select a block to see what ran.</span>
    </div>
    <div
      v-if="timeline.unplaced"
      class="chart-notes"
    >
      <p>{{ unplacedSentence(timeline.unplaced.job_count, timeline.unplaced.amount) }}</p>
    </div>

    <details class="inline-details">
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
              <td>{{ row.piece.name }}</td>
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
                  @click="open(row.bucket, row.piece)"
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
