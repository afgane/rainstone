<script setup lang="ts">
import { X } from "@lucide/vue";
import { computed } from "vue";
import type { CostPiece, CostTimeline, Summary } from "../api";
import { offsetBoundary, periodOf, type ReportState } from "../api";
import { periodAxisEnd } from "../chart/axis";
import type { JobWindow } from "../jobsView";
import { describePeriod, exclusiveEnd } from "../periods";
import OverviewCostChart from "./overview/OverviewCostChart.vue";
import OverviewFigures from "./overview/OverviewFigures.vue";
import { undatedNote } from "../vocabulary";

const props = defineProps<{
  state: ReportState;
  summary: Summary;
  timeline: CostTimeline;
  /** The chart block whose drawer is open, as `<interval start>|<category>`. */
  openBlock: string;
  welcome: boolean;
  guideOpen: boolean;
}>();
const emit = defineEmits<{
  view: [view: "tool-runs" | "server"];
  block: [category: CostPiece["kind"], window: JobWindow, opener: HTMLElement];
  explore: [opener: HTMLElement];
  guide: [opener: HTMLElement];
  "dismiss-welcome": [];
}>();

const period = computed(() => periodOf(props.state));
const periodFrom = computed(() => offsetBoundary(period.value.fromDate, props.state.timezone));
const periodTo = computed(() => offsetBoundary(exclusiveEnd(period.value), props.state.timezone));
const axisEnd = computed(() => periodAxisEnd(period.value, props.state.timezone));
</script>

<template>
  <section v-if="welcome" class="overview-welcome" aria-label="Welcome to Rainstone">
    <p><strong>New to Rainstone?</strong> See what your analyses cost, then explore what contributed.</p>
    <button
      type="button" class="link-button" data-detail-trigger :aria-expanded="guideOpen"
      aria-controls="detail-drawer" @click="emit('guide', $event.currentTarget as HTMLElement)"
    >Quick guide</button>
    <button type="button" class="icon-close" aria-label="Dismiss welcome" @click="emit('dismiss-welcome')">
      <X :size="18" aria-hidden="true" />
    </button>
  </section>
  <OverviewFigures
    :summary="summary"
    :period-text="describePeriod(period, state.timezone)"
    @server="emit('view', 'server')"
  />
  <p v-if="summary.undated?.job_count" class="overview-notes">
    {{ undatedNote(summary.undated.job_count) }}
    <button class="link-button" type="button" @click="emit('view', 'tool-runs')">See them</button>
  </p>

  <OverviewCostChart
    :timeline="timeline"
    :timezone="state.timezone"
    :as-of="summary.as_of"
    :period-from="periodFrom"
    :period-to="periodTo"
    :axis-end="axisEnd"
    :open-block="openBlock"
    @block="(category, window, opener) => emit('block', category, window, opener)"
    @explore="emit('explore', $event)"
  />
</template>
