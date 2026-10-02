<script setup lang="ts">
import { computed, watchEffect } from "vue";
import type { BreakdownGroup } from "../../api";
import { layoutSegments, MINIMUM_HORIZONTAL, type Segment } from "../../chart/layout";
import { formatCost, pluralize, rangeCaption, smallerRuns, STRIP_HINT, STRIP_TITLE } from "../../vocabulary";
import { useBarRoom } from "../useBarRoom";
import { groupedTooltip, runTooltip } from "./tooltips";
import type { TooltipContent } from "./useChartTooltip";

type Grouped = Extract<Segment, { kind: "more" }>;

const props = defineProps<{
  /** The chosen workflow's runs; null while none is chosen or they have not loaded. */
  group: BreakdownGroup | null;
  openRunId: string;
  hoverRunId: string;
  timezone: string;
}>();
const emit = defineEmits<{
  run: [id: string];
  grouped: [key: string, boundary: { amount: string; runId: string } | null];
  hover: [id: string | null];
  tip: [content: TooltipContent | null, x: number, y: number];
  more: [present: boolean];
}>();

const { chart, room } = useBarRoom();

// The strip draws the same contributions and grouped boundary as By workflow,
// at the chosen workflow's own scale: another view of it, never extra cost.
const segments = computed<Segment[]>(() => {
  const group = props.group;
  if (!group || group.amount === null) return [];
  return layoutSegments(
    group.runs.map(run => ({
      id: run.id, drawn: run.chart_amount === null ? null : Number(run.chart_amount),
      amount: run.amount, status: run.status,
    })),
    group.remainder, room.value, MINIMUM_HORIZONTAL,
  );
});
watchEffect(() => emit("more", segments.value.some(segment => segment.kind === "more")));

const caption = computed(() => (props.group ? rangeCaption(props.group.whole_run_range) : STRIP_HINT));

function showRun(event: PointerEvent, id: string) {
  const group = props.group;
  const run = group?.runs.find(candidate => candidate.id === id);
  if (!group || !run) return;
  emit("hover", id);
  emit("tip", runTooltip({ ...run, workflow_name: group.name }, props.timezone, run.chart_amount), event.clientX, event.clientY);
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
</script>

<template>
  <div ref="chart" class="wf-row zoom">
    <div class="zoom-label">
      <template v-if="group">
        <span :title="group.name">{{ group.name }}</span>
        <small>{{ pluralize(group.run_count, "run") }}, each at its own scale</small>
      </template>
      <template v-else>
        <span>{{ STRIP_TITLE }}</span>
      </template>
    </div>
    <div class="strip-body">
      <div
        v-if="group"
        class="track"
      >
        <div class="bar">
          <template
            v-for="segment in segments"
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
              @pointermove="showRun($event, segment.run.id)"
              @pointerleave="leave"
            />
            <button
              v-else
              class="blk more"
              type="button"
              :style="{ width: `${segment.size}px` }"
              :aria-label="`${smallerRuns(segment.count)}, ${group.name}, ${formatCost(String(segment.drawn))} together. Select to list them.`"
              @click="emit('grouped', group.key, segment.boundary)"
              @pointermove="showGrouped($event, segment)"
              @pointerleave="leave"
              @focus="showGrouped($event, segment)"
              @blur="leave"
            />
          </template>
        </div>
        <span class="total" data-full-scale>{{ formatCost(group.amount) }}</span>
      </div>
      <small class="strip-caption">{{ caption }}</small>
    </div>
  </div>
</template>
