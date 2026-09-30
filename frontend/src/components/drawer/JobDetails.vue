<script setup lang="ts">
import { computed } from "vue";
import type { JobDetail } from "../../api";
import { executionHistory, formatMachineCapacity, logicalExecutions, neverStarted, sameAmount } from "../../jobDetail";
import {
  COMPUTE_HEADING, costExplanation, environmentLabel, formatCost, formatDateTime,
  formatJobDuration, jobDurationLabel, jobHeadlineLabel, jobStateKind, needsCostNote, NO_COMPUTE_EVIDENCE,
  WAITED_TO_START, pluralize, purchaseModelLabel, SUBMITTED, RAN_FOR,
} from "../../vocabulary";
import JobCostEstimate from "./JobCostEstimate.vue";
import JobExecutions from "./JobExecutions.vue";
import JobExecutionTimeline from "./JobExecutionTimeline.vue";
import JobResourceUse from "./JobResourceUse.vue";
import JobTechnicalDetails from "./JobTechnicalDetails.vue";

const props = defineProps<{ detail: JobDetail; timezone: string; periodLabel: string }>();

const history = computed(() => executionHistory(props.detail));
const periodNote = computed(() => {
  const { interval_amount: inside, full_job_amount: whole } = props.detail;
  if (sameAmount(inside, whole)) return "";
  return inside === null
    ? `Its cost inside ${props.periodLabel} is not available.`
    : `${formatCost(inside)} of it falls inside ${props.periodLabel}.`;
});
const costNote = computed(() => needsCostNote(props.detail.full_quality)
  ? costExplanation({
    quality: props.detail.full_quality, amount: props.detail.full_job_amount, reason: props.detail.full_reason,
    capacities: props.detail.full_capacities,
  })
  : "");

// A failed job states what was recorded; a retry's history carries the same facts per attempt.
const failure = computed(() => {
  const [only] = logicalExecutions(props.detail);
  if (jobStateKind(props.detail.state) !== "failed" || logicalExecutions(props.detail).length !== 1 || !only) return null;
  return { exitCode: only.exit_code, providerOutcome: only.provider_outcome };
});

const duration = computed(() => {
  const { duration_seconds: seconds, duration_running: running } = props.detail;
  return {
    text: seconds === null ? "—" : `${formatJobDuration(seconds)}${running ? " so far" : ""}`,
    words: jobDurationLabel(seconds, running),
  };
});
const beforeStart = computed(() => props.detail.before_start_seconds);
</script>

<template>
  <p class="dialog-amount">
    <strong>{{ formatCost(detail.full_job_amount) }}</strong>
    <span>{{ jobHeadlineLabel(detail.full_quality, detail.full_job_amount) }}</span>
  </p>
  <p v-if="costNote" class="explanation">{{ costNote }}</p>
  <p v-if="periodNote" class="dialog-meta">{{ periodNote }}</p>

  <dl class="drawer-facts job-facts">
    <dt>{{ SUBMITTED }}</dt><dd>{{ formatDateTime(detail.created_at, timezone) }}</dd>
    <template v-if="detail.started_at && !detail.timing_issue">
      <dt>{{ WAITED_TO_START }}</dt>
      <dd>{{ beforeStart === null ? "—" : formatJobDuration(beforeStart) }}</dd>
    </template>
    <template v-if="!neverStarted(detail.state)">
      <dt>{{ RAN_FOR }}</dt>
      <dd>
        <span aria-hidden="true">{{ duration.text }}</span><span class="sr-only">{{ duration.words }}</span>
      </dd>
    </template>
    <template v-if="failure && failure.exitCode !== null">
      <dt>Exit code</dt><dd>{{ failure.exitCode }}</dd>
    </template>
    <template v-if="failure && failure.providerOutcome">
      <dt>Provider outcome</dt><dd>{{ failure.providerOutcome }}</dd>
    </template>
  </dl>

  <JobExecutionTimeline :detail="detail" :timezone="timezone" />

  <section class="job-section" aria-labelledby="job-compute-heading">
    <h3 id="job-compute-heading">{{ COMPUTE_HEADING }}</h3>
    <p v-if="!detail.resources.length" class="dialog-meta">{{ NO_COMPUTE_EVIDENCE }}</p>
    <template v-else>
      <p v-if="detail.resources.length > 1" class="dialog-meta">
        This job used {{ pluralize(detail.resources.length, "machine") }}.
      </p>
      <ul class="compute-list" role="list">
        <li v-for="resource in detail.resources" :key="resource.lifetime_id">
          <span class="compute-environment">{{ environmentLabel(resource.capacity_relationship) }}</span>
          <span class="compute-machine">
            {{ resource.machine_type ?? "Machine type not recorded" }}<template v-if="resource.purchase_model">
              · {{ purchaseModelLabel(resource.purchase_model) }}
            </template>
          </span>
          <span v-if="resource.machine_capacity" class="compute-used">
            Machine capacity: {{ formatMachineCapacity(resource.machine_capacity) }}
          </span>
          <span v-if="detail.resources.length > 1" class="compute-used">
            Used by {{ pluralize(resource.shared_attempt_count, "run") }}
          </span>
          <span v-if="resource.shared_attempt_count > 1" class="compute-used">
            Its runs shared this machine; it is charged once.
          </span>
        </li>
      </ul>
    </template>
  </section>

  <JobResourceUse :use="detail.resource_use" />
  <JobExecutions v-if="history" :history="history" :resources="detail.resources" :timezone="timezone" />
  <JobCostEstimate :detail="detail" :timezone="timezone" />
  <JobTechnicalDetails :detail="detail" />
</template>
