<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from "vue";
import type { BucketUnit } from "../../api";
import { axisText, type AxisSlot } from "../../chart/axis";
import { axisLabelStep } from "../../chart/layout";
import { formatAxisCost } from "../../vocabulary";

/**
 * The frame every time chart shares: the cost axis, its grid lines and the
 * time axis, with one column per slot drawn by the chart in the default slot.
 */
const props = defineProps<{
  slots: AxisSlot[];
  unit: BucketUnit;
  timezone: string;
  asOf: string | null;
  scale: { max: number; step: number };
  /** Said across the plot when nothing in it has a cost. */
  empty?: string;
}>();

// The y axis and the plot's own padding leave this much of the chart unusable.
const AXIS_WIDTH = 48;

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

const ticks = computed(() => {
  const found: number[] = [];
  for (let value = 0; value <= props.scale.max + 1e-9; value += props.scale.step) found.push(value);
  return found;
});
const slotWidth = computed(() =>
  Math.max(1, (width.value - AXIS_WIDTH - 40) / Math.max(1, props.slots.length)));
const labelStep = computed(() => axisLabelStep(props.unit, slotWidth.value));
const asOfTime = computed(() => (props.asOf ? Date.parse(props.asOf) : Infinity));
</script>

<template>
  <div class="tplot">
    <div class="yaxis">
      <span
        v-for="tick in ticks" :key="tick" class="ytick"
        :style="{ bottom: `${tick / scale.max * 100}%` }"
      >{{ formatAxisCost(tick) }}</span>
    </div>
    <div :ref="measure" class="plot">
      <p v-if="empty" class="plot-empty">{{ empty }}</p>
      <div
        v-for="tick in ticks.slice(1)" :key="`grid-${tick}`" class="grid"
        :style="{ bottom: `${tick / scale.max * 100}%` }"
      />
      <div class="cols"><slot /></div>
    </div>
    <div class="xaxis">
      <div
        v-for="(slot, index) in slots" :key="slot.from" class="xl"
        :class="{ future: slot.from >= asOfTime }"
      >
        <span v-if="index % labelStep === 0">{{ axisText(unit, slot.from, timezone) }}</span>
      </div>
    </div>
  </div>
</template>
