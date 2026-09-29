<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch, watchEffect } from "vue";
import type { BreakdownGroup } from "../../api";
import { layoutSegments, MINIMUM_HORIZONTAL, type LayoutRun, type Segment } from "../../chart/layout";
import { formatCost, pluralize, smallerRuns } from "../../vocabulary";
import { groupedTooltip, runTooltip } from "./tooltips";
import type { TooltipContent } from "./useChartTooltip";

type Grouped = Extract<Segment, { kind: "more" }>;

const props = defineProps<{
  groups: BreakdownGroup[];
  selectedKey: string;
  openRunId: string;
  hoverRunId: string;
  timezone: string;
}>();
const emit = defineEmits<{
  workflow: [key: string];
  run: [id: string];
  grouped: [key: string, boundary: { amount: string; runId: string } | null];
  hover: [id: string | null];
  tip: [content: TooltipContent | null, x: number, y: number];
  more: [present: boolean];
}>();

// Room for the value label at the end of the longest bar.
const VALUE_LABEL_WIDTH = 96;
const trackWidth = ref(0);
let observed: HTMLElement | null = null;
const observer = new ResizeObserver(entries => {
  trackWidth.value = Math.round(entries[0].contentRect.width);
});
function measure(element: unknown) {
  const target = element instanceof HTMLElement ? element : null;
  if (target === observed) return;
  if (observed) observer.unobserve(observed);
  observed = target;
  if (target) observer.observe(target);
}
onBeforeUnmount(() => observer.disconnect());

// All groups share one scale: the largest group's attributed cost.
const scale = computed(() => Math.max(0, ...props.groups.map(group => Number(group.amount) || 0)));

function asRuns(group: BreakdownGroup): LayoutRun[] {
  return group.runs.map(run => ({
    id: run.id, drawn: run.chart_amount === null ? null : Number(run.chart_amount),
    amount: run.amount, status: run.status,
  }));
}

const rows = computed(() => props.groups.map(group => {
  const length = Math.max(
    MINIMUM_HORIZONTAL,
    (trackWidth.value - VALUE_LABEL_WIDTH) * ((Number(group.amount) || 0) / (scale.value || 1)),
  );
  const segments: Segment[] = group.amount === null ? [] : layoutSegments(
    asRuns(group), group.remainder, length, MINIMUM_HORIZONTAL,
  );
  return { group, segments };
}));

function showRun(event: PointerEvent, group: BreakdownGroup, id: string) {
  const run = group.runs.find(candidate => candidate.id === id);
  if (!run) return;
  emit("hover", id);
  emit(
    "tip", runTooltip({ ...run, workflow_name: group.name }, props.timezone, run.chart_amount),
    event.clientX, event.clientY,
  );
}

function showGrouped(event: PointerEvent | FocusEvent, segment: Grouped) {
  let x: number;
  let y: number;
  if ("clientX" in event) {
    x = event.clientX; y = event.clientY;
  } else {
    const box = (event.target as HTMLElement).getBoundingClientRect();
    x = box.left; y = box.bottom - 18;
  }
  emit("tip", groupedTooltip(segment.count, segment.drawn, segment.failed, segment.running, "Select to list them"), x, y);
}

function leave() {
  emit("hover", null);
  emit("tip", null, 0, 0);
}

watch(() => props.groups, leave);
watchEffect(() => emit("more", rows.value.some(row => row.segments.some(segment => segment.kind === "more"))));
</script>

<template>
  <div class="workflow-bars">
    <div
      v-for="(row, index) in rows"
      :key="row.group.key"
      class="wf-row"
    >
      <button
        class="wf-label"
        type="button"
        :title="row.group.name"
        :aria-pressed="selectedKey === row.group.key"
        @click="emit('workflow', row.group.key)"
      >
        <span class="wf-name">{{ row.group.name }}</span>
        <small>{{ pluralize(row.group.run_count, "run") }}</small>
      </button>
      <div
        :ref="index === 0 ? measure : undefined"
        class="track"
      >
        <div class="bar">
          <template
            v-for="segment in row.segments"
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
              :style="{ width: `${segment.size}px` }"
              @click="emit('run', segment.run.id)"
              @pointermove="showRun($event, row.group, segment.run.id)"
              @pointerleave="leave"
            />
            <button
              v-else
              class="blk more"
              type="button"
              :style="{ width: `${segment.size}px` }"
              :aria-label="`${smallerRuns(segment.count)}, ${row.group.name}, ${formatCost(String(segment.drawn))} together. Select to list them.`"
              @click="emit('grouped', row.group.key, segment.boundary)"
              @pointermove="showGrouped($event, segment)"
              @pointerleave="leave"
              @focus="showGrouped($event, segment)"
              @blur="leave"
            />
          </template>
        </div>
        <span class="total">{{ formatCost(row.group.amount) }}</span>
      </div>
    </div>
  </div>
</template>
