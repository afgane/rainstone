<script setup lang="ts">
import { computed } from "vue";
import type { RunTotals } from "../../api";
import {
  acrossWorkflows, formatCost, measureName, outcomeMix, outOfRuns, SHARED_JOBS_NOTE,
} from "../../vocabulary";

const props = defineProps<{
  totals: RunTotals;
  basis: string;
  periodText: string;
  /** The selected workflow's name, or empty when no single workflow is chosen. */
  workflowName: string;
  /** True when a page filter other than the workflow narrows the runs. */
  narrowed: boolean;
}>();

const filtered = computed(() => props.narrowed || Boolean(props.workflowName));
const empty = computed(() => props.totals.run_count === 0);
const scope = computed(() =>
  props.workflowName || (props.narrowed ? "Matching workflows" : "All workflows"));
const recordedSoFar = computed(() => props.totals.incomplete_run_count > 0 && props.totals.amount !== null);
// Every state has the same lines, so choosing something never moves the page; a coverage note joins the last one.
const amountText = computed(() => (empty.value ? "No matching runs" : formatCost(props.totals.amount)));
const coverage = computed(() => {
  const notes = [];
  if (props.totals.incomplete_run_count > 0) {
    const count = props.totals.incomplete_run_count;
    notes.push(`${count} ${count === 1 ? "run still needs" : "runs still need"} cost data`);
  }
  if (props.totals.shared_job_count > 0) notes.push(SHARED_JOBS_NOTE);
  return notes.join(" · ");
});
const note = computed(() => ["Compute only · USD", coverage.value].filter(Boolean).join(" · "));
const mix = computed(() => (empty.value ? "No runs match" : outcomeMix(props.totals.by_status)));
const context = computed(() =>
  filtered.value ? outOfRuns(props.totals.unfiltered_run_count) : acrossWorkflows(props.totals.workflow_count));
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
        {{ measureName(basis) }}
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
      <p
        class="figure-line figure-scope"
        :title="scope"
      >
        <strong v-if="workflowName">{{ scope }}</strong>
        <template v-else>
          {{ scope }}
        </template>
      </p>
      <!-- One line whatever it says: a long note is cut with an ellipsis and kept whole in the tooltip. -->
      <p
        class="figure-line figure-note"
        :title="note"
      >
        {{ note }}
      </p>
    </section>
    <section
      class="figure"
      aria-labelledby="figure-runs"
    >
      <p
        id="figure-runs"
        class="eyebrow"
      >
        Workflow runs
      </p>
      <p class="figure-amount">
        {{ totals.run_count }}
      </p>
      <p class="figure-line">
        {{ mix }}
      </p>
      <p class="figure-line">
        {{ context }}
      </p>
    </section>
  </div>
</template>
