<script setup lang="ts">
import { computed, reactive } from "vue";
import type { RunJob } from "../../api";
import { groupJobs } from "../../runJobs";
import {
  formatCost, groupCoverage, groupHeading, MULTIPLE_ENVIRONMENTS_NOTE, SERVER_GROUP_NOTE, showMore,
  shownOf,
} from "../../vocabulary";
import JobRow from "./JobRow.vue";

const props = defineProps<{ jobs: RunJob[] }>();
const emit = defineEmits<{ open: [id: string] }>();

// A very large run is shown a page at a time, with every job reachable.
const PAGE = 100;
const groups = computed(() => groupJobs(props.jobs));
const visible = reactive<Record<string, number>>({});

function limit(environment: string): number {
  return visible[environment] ?? PAGE;
}
function more(environment: string) {
  visible[environment] = limit(environment) + PAGE;
}

type Group = (typeof groups.value)[number];

/** The group's whole cost, on the heading's line; the server's jobs add none to state. */
function cost(group: Group): string {
  return group.showsCost && group.subtotal !== null ? formatCost(group.subtotal) : "";
}
function summary(group: Group): string {
  if (group.environment === "existing") return SERVER_GROUP_NOTE;
  const lines = [group.environment === "multiple" ? MULTIPLE_ENVIRONMENTS_NOTE : "",
    groupCoverage(Boolean(cost(group)), group.incomplete)];
  return lines.filter(Boolean).join(" ");
}
</script>

<template>
  <div class="job-groups">
    <section
      v-for="group in groups" :key="group.environment" class="job-group"
      :data-environment="group.environment" :aria-labelledby="`job-group-${group.environment}`"
    >
      <div class="group-head">
        <h4 :id="`job-group-${group.environment}`">
          {{ groupHeading(group.environment, group.jobs.length) }}
        </h4>
        <span v-if="cost(group)" class="group-cost">
          <span class="sr-only">Cost of these jobs: </span>{{ cost(group) }}
        </span>
      </div>
      <p v-if="summary(group)" class="group-summary">{{ summary(group) }}</p>
      <ul class="job-list" role="list" :data-with-cost="group.showsCost">
        <JobRow
          v-for="job in group.jobs.slice(0, limit(group.environment))" :key="job.id" :job="job"
          :show-cost="group.showsCost" @open="emit('open', $event)"
        />
      </ul>
      <template v-if="group.jobs.length > limit(group.environment)">
        <p class="group-summary">{{ shownOf(limit(group.environment), group.jobs.length, "job") }}</p>
        <button type="button" class="link-button" @click="more(group.environment)">
          {{ showMore(Math.min(PAGE, group.jobs.length - limit(group.environment))) }}
        </button>
      </template>
    </section>
  </div>
</template>
