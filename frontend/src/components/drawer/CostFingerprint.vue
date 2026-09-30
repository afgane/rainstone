<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { COLUMNS, type CostComposition, type Part } from "../../costBreakdown";
import {
  environmentLabel, fingerprintCaption, formatCost, formatShare, jobsInPart, pluralize, shareBasis,
} from "../../vocabulary";

const props = defineProps<{
  composition: CostComposition;
  /** The part whose details are open. */
  selected: string;
  /** A part a control is pointing at, so its squares light up with it. */
  pointed: string;
  /** A part whose control has keyboard focus, so its tooltip shows too. */
  tipped: string;
  running: boolean;
  complete: boolean;
}>();
const emit = defineEmits<{ select: [key: string] }>();

const CELLS_BELOW_WIDTH = 240;
// Between the pointer and the tooltip, so the square under the pointer is never covered.
const GAP = 14;
const frame = ref<HTMLElement | null>(null);
const tipBox = ref<HTMLElement | null>(null);
const cellBoxes: HTMLElement[] = [];
const columns = ref(COLUMNS);
// Where the pointer (or a focused part's first square) is, in the chart's own coordinates.
const tip = ref<{ key: string; x: number; y: number } | null>(null);
const frameBox = ref({ width: 0, top: 0 });
const tipSize = ref({ width: 0, height: 0 });
let observer: ResizeObserver | null = null;

onMounted(() => {
  if (typeof ResizeObserver === "undefined" || !frame.value) return;
  // The grid follows the drawer's own width: a tenth-by-tenth square only when a row of twenty would be specks.
  observer = new ResizeObserver(entries => {
    const width = entries[0]?.contentRect.width ?? CELLS_BELOW_WIDTH;
    columns.value = width < CELLS_BELOW_WIDTH ? 10 : COLUMNS;
  });
  observer.observe(frame.value);
});
onBeforeUnmount(() => {
  observer?.disconnect();
  document.removeEventListener("keydown", onEscape, true);
});

const owners = computed(() => props.composition.cellOwners);
// One blank square between tools keeps every square on the same grid. At the start of a row the
// wrap already breaks the tools apart, so no blank is added there.
const slots = computed(() => {
  const result: Array<{ key: string | null; index: number }> = [];
  owners.value.forEach((key, index) => {
    if (index > 0 && key !== owners.value[index - 1] && result.length % columns.value !== 0) {
      result.push({ key: null, index: -1 });
    }
    result.push({ key, index });
  });
  return result;
});
const hot = computed(() => tip.value?.key || props.pointed || "");

function part(key: string): Part {
  return props.composition.byKey.get(key)!;
}
const tipPart = computed(() => (tip.value ? part(tip.value.key) : null));
const tipLines = computed(() => {
  const each = tipPart.value;
  if (!each) return [];
  const place = each.kind === "other" && each.environment === "multiple"
    ? "Multiple environments" : environmentLabel(each.environment);
  return [
    each.kind === "other" ? pluralize(each.members.length, "part") : jobsInPart(each.jobIds.length),
    `${formatCost(each.amount)} · ${formatShare(each.share)} ${shareBasis(props.running, props.complete)}`,
    place,
    ...(!each.complete || props.running ? ["Not final: some cost is still missing or accruing"] : []),
  ];
});

// Above the pointer, so moving down the chart never runs into it; below only when there is no room above.
const tipStyle = computed(() => {
  if (!tip.value) return {};
  const { x, y } = tip.value;
  const left = Math.max(0, Math.min(x - tipSize.value.width / 2, frameBox.value.width - tipSize.value.width));
  const above = y - tipSize.value.height - GAP;
  const top = frameBox.value.top + above < 8 ? y + GAP + 10 : above;
  return { left: `${left}px`, top: `${top}px` };
});

async function place(key: string, x: number, y: number) {
  const box = frame.value?.getBoundingClientRect();
  if (!box) return;
  const changed = tip.value?.key !== key;
  frameBox.value = { width: box.width, top: box.top };
  tip.value = { key, x, y };
  if (!changed) return;
  await nextTick();
  const size = tipBox.value?.getBoundingClientRect();
  if (size) tipSize.value = { width: size.width, height: size.height };
}
function follow(key: string, event: MouseEvent) {
  const box = frame.value?.getBoundingClientRect();
  if (box) void place(key, event.clientX - box.left, event.clientY - box.top);
}
function leave() {
  tip.value = null;
}

// Escape clears the tooltip first; only a second press reaches the drawer.
function onEscape(event: KeyboardEvent) {
  if (event.key !== "Escape") return;
  tip.value = null;
  event.stopImmediatePropagation();
  event.preventDefault();
}
watch(() => tip.value !== null, open => {
  if (open) document.addEventListener("keydown", onEscape, true);
  else document.removeEventListener("keydown", onEscape, true);
});
// A control's keyboard focus shows the same tooltip at the part's first square.
watch(() => props.tipped, key => {
  if (!key) { if (tip.value) tip.value = null; return; }
  const first = owners.value.indexOf(key);
  const cell = cellBoxes[first]?.getBoundingClientRect();
  const box = frame.value?.getBoundingClientRect();
  if (cell && box) void place(key, cell.left - box.left + cell.width / 2, cell.top - box.top);
});

const figureName = computed(() => (
  `Cost breakdown: ${owners.value.length} squares, each about 1% of the cost shown`
));
</script>

<template>
  <div ref="frame" class="fingerprint" :data-columns="columns">
    <div
      class="fingerprint-cells" role="img" :aria-label="figureName" aria-describedby="fingerprint-caption"
      :style="{ gridTemplateColumns: `repeat(${columns}, minmax(0, 1fr))` }"
    >
      <template v-for="(slot, position) in slots" :key="position">
        <div v-if="slot.key === null" class="fp-gap" aria-hidden="true" />
        <div
          v-else
          :ref="(element: unknown) => { cellBoxes[slot.index] = element as HTMLElement }"
          class="fp-cell" :data-part="slot.key" :data-kind="part(slot.key).kind"
          :data-environment="part(slot.key).environment"
          :data-hot="hot === slot.key" :data-selected="selected === slot.key"
          @mouseenter="follow(slot.key, $event)" @mousemove="follow(slot.key, $event)" @mouseleave="leave"
          @click="emit('select', slot.key)"
        />
      </template>
    </div>
    <p id="fingerprint-caption" class="fingerprint-caption">{{ fingerprintCaption(owners.length) }}</p>
    <div v-if="tip && tipPart" ref="tipBox" class="fp-tip" role="tooltip" :style="tipStyle">
      <strong>{{ tipPart.name }}</strong>
      <span v-for="line in tipLines" :key="line">{{ line }}</span>
    </div>
  </div>
</template>
