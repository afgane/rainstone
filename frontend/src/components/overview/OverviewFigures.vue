<script setup lang="ts">
import { computed } from "vue";
import type { Summary, WorkloadTotals } from "../../api";
import {
  acrossWorkflows, coverageSentence, formatCost, NO_JOBS, outcomeMix, PRIMARY_EXPLANATION,
  PRIMARY_MEASURE, WORKLOAD_EYEBROW,
} from "../../vocabulary";

const props = defineProps<{
  summary: Summary;
  workload: WorkloadTotals;
  periodText: string;
}>();

const empty = computed(() => props.summary.job_count === 0);
const recordedSoFar = computed(() =>
  props.summary.unpriced_job_count > 0 && props.summary.amount !== null);
const amountText = computed(() => (empty.value ? "No jobs" : formatCost(props.summary.amount)));
const mix = computed(() => (empty.value ? NO_JOBS : outcomeMix(props.workload.by_outcome)));
</script>

<template>
  <div class="figures">
    <section
      class="figure featured"
      aria-labelledby="figure-cost"
    >
      <p
        id="figure-cost"
        class="eyebrow"
      >
        {{ PRIMARY_MEASURE }}
      </p>
      <p class="figure-amount">
        {{ amountText }}
        <span
          v-if="recordedSoFar"
          class="figure-qualifier"
        >recorded so far</span>
      </p>
      <p class="figure-line">
        {{ periodText }}
      </p>
      <p class="figure-line">
        {{ coverageSentence(summary.job_count, summary.unpriced_job_count) }}
        <span class="measure-note">Compute only · USD</span>
      </p>
      <p class="figure-line">
        {{ PRIMARY_EXPLANATION }}
      </p>
    </section>
    <section
      class="figure workload"
      aria-labelledby="figure-workload"
    >
      <p
        id="figure-workload"
        class="eyebrow"
      >
        {{ WORKLOAD_EYEBROW }}
      </p>
      <div class="workload-groups">
        <div
          class="workload-group"
          role="group"
          aria-labelledby="workload-jobs"
        >
          <p
            id="workload-jobs"
            class="workload-label"
          >
            {{ workload.job_count === 1 ? "Job" : "Jobs" }}
          </p>
          <p class="figure-amount">
            {{ workload.job_count }}
          </p>
          <p class="figure-line">
            {{ mix }}
          </p>
        </div>
        <div
          class="workload-group"
          role="group"
          aria-labelledby="workload-runs"
        >
          <p
            id="workload-runs"
            class="workload-label"
          >
            {{ workload.run_count === 1 ? "Workflow run" : "Workflow runs" }}
          </p>
          <p class="figure-amount">
            {{ workload.run_count }}
          </p>
          <p class="figure-line">
            {{ acrossWorkflows(workload.workflow_count) }}
          </p>
        </div>
      </div>
    </section>
  </div>
</template>
