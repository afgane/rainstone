<script setup lang="ts">
import { computed } from "vue";
import type { RunJob } from "../../api";
import {
  environmentLabel, formatCompactCost, formatJobDuration, jobCostLabel, jobDurationLabel, jobStateLabel,
} from "../../vocabulary";
import JobRowView from "./JobRowView.vue";

const props = defineProps<{
  job: RunJob;
  /** Whether this group states a cost for each job. */
  showCost: boolean;
  /** Names the job by its identifier, where equal names must be told apart. */
  showId?: boolean;
}>();
const emit = defineEmits<{ open: [id: string] }>();

const stateText = computed(() => jobStateLabel(props.job.state));
const stepContext = computed(() => {
  const step = props.job.steps[0];
  if (!step) return "";
  return step.nested ? `Step ${step.step_key} of ${step.workflow_name}` : `Step ${step.step_key}`;
});
const label = computed(() => [
  props.job.tool_name, `job ${props.job.source_id}`, stateText.value,
  jobDurationLabel(props.job.duration_seconds, props.job.duration_running),
  props.showCost ? jobCostLabel(props.job.amount) : "",
  props.job.reused ? "reused earlier output" : "",
].filter(Boolean).join(", "));
const tipLines = computed(() => [
  `${stateText.value}${props.job.duration_running ? " · running" : ""}`,
  props.job.reused ? "Reused an earlier output and added no new compute" : "",
  stepContext.value,
  props.showCost && props.job.amount !== null ? jobCostLabel(props.job.amount) : "",
  props.job.environment !== "dedicated" ? environmentLabel(props.job.environment) : "",
].filter(Boolean));
</script>

<template>
  <JobRowView
    :id="job.id" :tool-name="job.tool_name" :state="job.state"
    :duration="formatJobDuration(job.duration_seconds)"
    :cost="showCost ? formatCompactCost(job.amount) : null"
    :label="label" :id-text="showId ? `#${job.source_id}` : undefined"
    :flag="job.reused ? 'reused' : undefined"
    :tip-title="`${job.tool_name} · job ${job.source_id}`" :tip-lines="tipLines"
    @open="emit('open', $event)"
  />
</template>
