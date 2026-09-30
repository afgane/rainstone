<script setup lang="ts">
import { computed } from "vue";
import type { RunJob } from "../../api";
import {
  environmentLabel, formatCompactCost, formatJobDuration, jobCostLabel, jobDurationLabel, jobStateLabel,
} from "../../vocabulary";
import JobStateIcon from "./JobStateIcon.vue";
import { useDismissibleTip } from "./useDismissibleTip";

const props = defineProps<{
  job: RunJob;
  /** Whether this group states a cost for each job. */
  showCost: boolean;
  /** Names the job by its identifier, where equal names must be told apart. */
  showId?: boolean;
}>();
const emit = defineEmits<{ open: [id: string] }>();

const tip = useDismissibleTip();
const stateText = computed(() => jobStateLabel(props.job.state));
const stepContext = computed(() => {
  const step = props.job.steps[0];
  if (!step) return "";
  return step.nested ? `Step ${step.step_key} of ${step.workflow_name}` : `Step ${step.step_key}`;
});
// The full name, the job and everything the columns say, so nothing depends on the truncated text.
const label = computed(() => [
  props.job.tool_name, `job ${props.job.source_id}`, stateText.value,
  jobDurationLabel(props.job.duration_seconds, props.job.duration_running),
  props.showCost ? jobCostLabel(props.job.amount) : "",
  props.job.reused ? "reused earlier output" : "",
].filter(Boolean).join(", "));

function onFocus(event: FocusEvent) {
  // A pointer press focuses the row too; only keyboard focus needs a tooltip of its own.
  try {
    if ((event.target as HTMLElement).matches(":focus-visible")) tip.show();
  } catch {
    tip.show();
  }
}
</script>

<template>
  <li class="job-item" role="listitem">
    <button
      type="button" class="job-row" :data-job-id="job.id" :aria-label="label"
      @click="emit('open', job.id)" @mouseenter="tip.show()" @mouseleave="tip.hide()"
      @focus="onFocus" @blur="tip.hide()"
    >
      <span class="job-name">
        <span class="job-title">{{ job.tool_name }}</span>
        <span v-if="showId" class="job-id">#{{ job.source_id }}</span>
        <span v-if="job.reused" class="job-flag">reused</span>
      </span>
      <span class="job-state"><JobStateIcon :state="job.state" /></span>
      <span class="job-duration">{{ formatJobDuration(job.duration_seconds) }}</span>
      <span v-if="showCost" class="job-cost">{{ formatCompactCost(job.amount) }}</span>
      <span v-if="tip.shown.value" class="job-tip" aria-hidden="true">
        <strong>{{ job.tool_name }}</strong> · job {{ job.source_id }}
        <span>{{ stateText }}{{ job.duration_running ? " · running" : "" }}</span>
        <span v-if="job.reused">Reused an earlier output and added no new compute</span>
        <span v-if="stepContext">{{ stepContext }}</span>
        <span v-if="showCost && job.amount !== null">{{ jobCostLabel(job.amount) }}</span>
        <span v-if="job.environment !== 'dedicated'">{{ environmentLabel(job.environment) }}</span>
      </span>
    </button>
  </li>
</template>
