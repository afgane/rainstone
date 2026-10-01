<script setup lang="ts">
import { computed } from "vue";
import type { ScopedJob } from "../../api";
import {
  capacityLabel, formatCompactCost, formatCost, formatJobDuration, jobStateLabel, qualityLabel,
} from "../../vocabulary";
import JobRowView from "./JobRowView.vue";

/**
 * A job listed for a tool or an interval. Its cost is the list's own scope,
 * named in every label; its duration is the job's whole run. No identifier is
 * shown or spoken: the row opens the job, whose details carry it.
 */
const props = defineProps<{
  job: ScopedJob;
  /** What the cost covers, as in "Cost in this period". */
  scope: string;
}>();
const emit = defineEmits<{ open: [id: string] }>();

const serverJob = computed(() => props.job.quality === "known_zero");
const durationWords = computed(() => {
  const { duration_seconds: seconds, duration_running: running } = props.job;
  if (seconds === null) return "Duration not recorded";
  return `Ran for ${formatJobDuration(seconds)}${running ? " so far" : ""}`;
});
const costWords = computed(() => (serverJob.value
  ? `${props.scope}: $0 extra, used your Galaxy server`
  : `${props.scope}: ${formatCost(props.job.amount)}`));
const label = computed(() => [
  props.job.tool_name, jobStateLabel(props.job.state), durationWords.value, costWords.value,
].join(", "));
const tipLines = computed(() => [
  jobStateLabel(props.job.state), durationWords.value, costWords.value,
  serverJob.value ? "" : qualityLabel(props.job.quality),
  capacityLabel(props.job.capacities),
].filter(Boolean));
</script>

<template>
  <JobRowView
    :id="job.id" :tool-name="job.tool_name" :state="job.state"
    :duration="formatJobDuration(job.duration_seconds)"
    :cost="serverJob ? '$0 extra' : formatCompactCost(job.amount)"
    :label="label" :tip-title="job.tool_name" :tip-lines="tipLines"
    @open="emit('open', $event)"
  />
</template>
