<script setup lang="ts">
import { computed } from "vue";
import type { JobTotals, Summary } from "../../api";
import {
  formatCost, inProgressNote, JOBS_SCOPE, NO_JOBS, PRIMARY_MEASURE, statusMix, unrecordedNote, WORKLOAD_EYEBROW,
} from "../../vocabulary";

const props = defineProps<{
  summary: Summary;
  /** The whole matching set from the loaded chart; null until one has arrived. */
  totals: JobTotals | null;
  periodText: string;
  /** The tool the page is narrowed to, or empty. */
  toolName: string;
  /** True when a filter or search narrows the jobs. */
  narrowed: boolean;
}>();

const empty = computed(() => props.summary.job_count === 0);
const recordedSoFar = computed(() => props.summary.unpriced_job_count > 0 && props.summary.amount !== null);
const amountText = computed(() => (empty.value ? "No jobs" : formatCost(props.summary.amount)));
const scope = computed(() => props.toolName || (props.narrowed ? "Matching jobs" : "All jobs in this period"));
const note = computed(() => [
  "Compute only · USD",
  props.summary.in_progress_job_count ? inProgressNote(props.summary.in_progress_job_count) : "",
  props.summary.unrecorded_job_count ? unrecordedNote(props.summary.unrecorded_job_count) : "",
].filter(Boolean).join(" · "));
const mix = computed(() => (empty.value ? NO_JOBS : statusMix(props.totals?.by_status ?? [])));
</script>

<template>
  <div class="figures">
    <section class="figure featured" aria-labelledby="figure-cost">
      <p id="figure-cost" class="eyebrow">{{ PRIMARY_MEASURE }}</p>
      <p class="figure-amount">
        {{ amountText }}
        <span v-if="recordedSoFar" class="figure-qualifier">recorded so far</span>
      </p>
      <p class="figure-line">{{ periodText }}</p>
      <p class="figure-line figure-scope" :title="scope">
        <strong v-if="toolName">{{ scope }}</strong><template v-else>{{ scope }}</template>
      </p>
      <p class="figure-line figure-note" :title="note">{{ note }}</p>
    </section>
    <section class="figure workload" aria-labelledby="figure-jobs">
      <p id="figure-jobs" class="eyebrow">{{ WORKLOAD_EYEBROW }}</p>
      <div class="workload-groups">
        <div class="workload-group" role="group" aria-labelledby="jobs-count">
          <p id="jobs-count" class="workload-label">{{ summary.job_count === 1 ? "Job" : "Jobs" }}</p>
          <p class="figure-amount">{{ summary.job_count }}</p>
          <p class="figure-line">{{ mix }}</p>
        </div>
        <div class="workload-group" role="group" aria-labelledby="tools-count">
          <p id="tools-count" class="workload-label">{{ totals?.tool_count === 1 ? "Tool" : "Tools" }}</p>
          <p class="figure-amount">{{ totals ? totals.tool_count : "—" }}</p>
          <p class="figure-line">{{ JOBS_SCOPE }}</p>
        </div>
      </div>
    </section>
  </div>
</template>
