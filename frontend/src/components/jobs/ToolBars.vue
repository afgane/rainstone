<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from "vue";
import type { JobBreakdown, ToolFamily } from "../../api";
import { TOOL_BATCH } from "../../api";
import { BLOCK_GAP, MINIMUM_HORIZONTAL } from "../../chart/layout";
import { costShares } from "../../jobsView";
import {
  formatCost, moreTools, needsCostData, pluralize, statusLine, TOOL_SEARCH_HELP, TOOL_SEARCH_LABEL,
} from "../../vocabulary";
import type { TooltipContent } from "../runs/useChartTooltip";

const props = defineProps<{
  breakdown: JobBreakdown;
  /** The tool whose drawer is open, so its row reads as selected. */
  openKey: string;
  search: string;
  /** True while a larger batch or a search is being fetched. */
  loading: boolean;
}>();
const emit = defineEmits<{
  open: [key: string, opener: HTMLElement];
  search: [text: string];
  limit: [count: number];
  tip: [content: TooltipContent | null, x: number, y: number];
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

// One scale for every row, however many are shown or found: the largest tool's cost.
const scale = computed(() => Number(props.breakdown.scale) || 0);
const allGroups = computed(() => [
  ...props.breakdown.groups, ...props.breakdown.server.groups,
  ...props.breakdown.zero.groups, ...props.breakdown.unavailable.groups,
]);
// Two tools can share a readable name; their keys tell them apart.
const sharedNames = computed(() => {
  const counts = new Map<string, number>();
  for (const group of allGroups.value) counts.set(group.name, (counts.get(group.name) ?? 0) + 1);
  return counts;
});

/**
 * A row's bar: its length is the tool's share of the largest tool, and each
 * status takes its exact share of that length. Only a bar too short to see is
 * held at a minimum; a status piece is never enlarged.
 */
const rows = computed(() => props.breakdown.groups.map(group => {
  const available = Math.max(0, trackWidth.value - VALUE_LABEL_WIDTH);
  const shares = costShares(group.by_status);
  const length = Math.max(MINIMUM_HORIZONTAL, available * ((Number(group.amount) || 0) / (scale.value || 1)));
  const drawable = Math.max(0, length - BLOCK_GAP * (shares.length - 1));
  return {
    group,
    segments: shares.map(({ piece, share }) => ({ piece, size: drawable * share })),
  };
}));

function qualifier(group: ToolFamily): string {
  return (sharedNames.value.get(group.name) ?? 0) > 1 ? group.key : "";
}

function tipFor(group: ToolFamily): TooltipContent {
  return {
    value: formatCost(group.amount),
    lines: [
      group.name, pluralize(group.job_count, "job"),
      ...group.by_status.map(statusLine),
      ...(group.incomplete_job_count ? [`Recorded so far · ${needsCostData(group.incomplete_job_count, "job")}`] : []),
      "Select to see this tool",
    ],
  };
}
function point(event: PointerEvent, group: ToolFamily) {
  emit("tip", tipFor(group), event.clientX, event.clientY);
}
function focusRow(event: FocusEvent, group: ToolFamily) {
  const box = (event.target as HTMLElement).getBoundingClientRect();
  emit("tip", tipFor(group), box.left + box.width / 2, box.bottom - 18);
}
function leave() {
  emit("tip", null, 0, 0);
}
watch(() => props.breakdown, leave);

const draft = ref(props.search);
watch(() => props.search, value => { draft.value = value; });
let timer = 0;
function typed(event: Event) {
  draft.value = (event.target as HTMLInputElement).value;
  window.clearTimeout(timer);
  timer = window.setTimeout(() => emit("search", draft.value), 250);
}
onBeforeUnmount(() => window.clearTimeout(timer));

const remainder = computed(() => props.breakdown.remainder);
const shownCount = computed(() => props.breakdown.groups.length);
const sections = computed(() => [
  { id: "server", section: props.breakdown.server, summary: (tools: number, jobs: number) =>
    `${pluralize(tools, "tool")} added $0 extra compute · ${pluralize(jobs, "job")}` },
  { id: "zero", section: props.breakdown.zero, summary: (tools: number, jobs: number) =>
    `${pluralize(tools, "tool")} recorded no compute cost · ${pluralize(jobs, "job")}` },
  { id: "unavailable", section: props.breakdown.unavailable, summary: (tools: number, jobs: number) =>
    `${pluralize(tools, "tool")} ${tools === 1 ? "has" : "have"} no cost data yet · ${pluralize(jobs, "job")}` },
].filter(entry => entry.section.tool_count > 0));
</script>

<template>
  <div class="tool-bars" :aria-busy="loading">
    <div class="tool-bars-head">
      <p class="tool-count">
        {{ search.trim()
          ? `${pluralize(breakdown.total, "tool")} with recorded cost match`
          : `Showing ${shownCount} of ${pluralize(breakdown.ranked_tool_count, "tool")} with recorded cost` }}
      </p>
      <label class="tool-search">
        <span>{{ TOOL_SEARCH_LABEL }}</span>
        <input
          type="search" :value="draft" placeholder="Search this chart" aria-describedby="tool-search-help"
          @input="typed"
        >
      </label>
      <p id="tool-search-help" class="sr-only">{{ TOOL_SEARCH_HELP }}</p>
    </div>

    <p v-if="!rows.length" class="empty">
      {{ search.trim() ? "No tool with recorded cost matches this search." : "No tool recorded a cost in this period." }}
    </p>
    <ul v-else class="tool-rows" role="list">
      <li v-for="(row, index) in rows" :key="row.group.key">
        <button
          type="button" class="tool-row" data-detail-trigger :data-tool-key="row.group.key"
          :aria-current="openKey === row.group.key ? 'true' : undefined"
          :aria-label="`${row.group.name}${qualifier(row.group) ? ` (${row.group.key})` : ''}, ${formatCost(row.group.amount)}, ${pluralize(row.group.job_count, 'job')}. ${row.group.by_status.map(statusLine).join('. ')}.`"
          @click="emit('open', row.group.key, $event.currentTarget as HTMLElement)"
          @pointermove="point($event, row.group)" @pointerleave="leave"
          @focus="focusRow($event, row.group)" @blur="leave"
        >
          <span class="tool-label">
            <span class="tool-name" :title="row.group.name">{{ row.group.name }}</span>
            <small v-if="qualifier(row.group)" class="tool-key" :title="row.group.key">{{ row.group.key }}</small>
            <small>{{ pluralize(row.group.job_count, "job") }}</small>
          </span>
          <span :ref="index === 0 ? measure : undefined" class="track">
            <span class="bar" aria-hidden="true">
              <span
                v-for="segment in row.segments" :key="segment.piece.status" class="blk"
                :data-status="segment.piece.status" :style="{ width: `${segment.size}px` }"
              />
            </span>
            <span class="total">
              {{ formatCost(row.group.amount) }}
              <small v-if="row.group.incomplete_job_count">Recorded so far</small>
            </span>
          </span>
        </button>
      </li>
    </ul>

    <div v-if="remainder.tool_count" class="tool-rest">
      <p>
        <strong>{{ moreTools(remainder.tool_count) }}</strong>
        <span>{{ pluralize(remainder.job_count, "job") }} · included in the total above</span>
      </p>
      <strong>{{ formatCost(remainder.amount) }}</strong>
    </div>
    <div v-if="remainder.tool_count" class="tool-more">
      <button
        type="button" class="secondary" :disabled="loading"
        @click="emit('limit', shownCount + TOOL_BATCH)"
      >Show {{ Math.min(TOOL_BATCH, remainder.tool_count) }} more tools</button>
      <button
        v-if="remainder.tool_count > TOOL_BATCH" type="button" class="link-button" :disabled="loading"
        @click="emit('limit', shownCount + remainder.tool_count)"
      >Show all {{ shownCount + remainder.tool_count }} tools</button>
    </div>

    <details v-for="entry in sections" :key="entry.id" class="inline-details tool-section">
      <summary>{{ entry.summary(entry.section.tool_count, entry.section.job_count) }}</summary>
      <ul class="tool-section-list" role="list">
        <li v-for="group in entry.section.groups" :key="group.key">
          <button
            type="button" class="link-button" data-detail-trigger :data-tool-key="group.key"
            :aria-current="openKey === group.key ? 'true' : undefined"
            @click="emit('open', group.key, $event.currentTarget as HTMLElement)"
          >{{ group.name }}</button>
          <small v-if="qualifier(group)" class="tool-key">{{ group.key }}</small>
          <span>{{ pluralize(group.job_count, "job") }}</span>
          <span v-if="entry.id === 'zero'">{{ formatCost(group.amount) }}</span>
        </li>
        <li v-if="!entry.section.groups.length" class="empty">No tool here matches this search.</li>
      </ul>
    </details>
  </div>
</template>
