<script setup lang="ts">
import { ChevronDown } from "@lucide/vue";
import { ref } from "vue";
import type { ExecutionHistory } from "../../jobDetail";
import type { JobResource } from "../../api";
import {
  formatExactDateTime, formatJobDuration, jobDurationLabel, jobStateLabel, formatDateTime,
} from "../../vocabulary";
import JobStateIcon from "./JobStateIcon.vue";

const props = defineProps<{ history: ExecutionHistory; resources: JobResource[]; timezone: string }>();

// One row is open at a time, in place, so the list never reflows around the reader.
const open = ref("");

function machines(keys: string[]): string {
  return keys
    .map(key => props.resources.find(resource => resource.resource_key === key))
    .map((resource, position) => resource?.machine_type ?? resource?.resource_key ?? keys[position])
    .join(", ");
}
</script>

<template>
  <section class="job-section" aria-labelledby="job-executions-heading">
    <h3 id="job-executions-heading">{{ history.heading }}</h3>
    <p class="dialog-meta">{{ history.summary }}</p>
    <ul class="execution-list" role="list">
      <li v-for="{ execution, title, dated } in history.rows" :key="execution.id" class="execution-item">
        <button
          type="button" class="execution-row" :aria-expanded="open === execution.id"
          :aria-controls="`execution-${execution.id}`"
          @click="open = open === execution.id ? '' : execution.id"
        >
          <span class="execution-title">
            <ChevronDown class="execution-chevron" :size="16" aria-hidden="true" />{{ title }}
          </span>
          <span class="execution-state">
            <JobStateIcon :state="execution.outcome" />{{ jobStateLabel(execution.outcome) }}
          </span>
          <span class="execution-start">
            {{ dated ? formatDateTime(execution.tool_started_at as string, timezone) : "Timing not recorded" }}
          </span>
          <span class="execution-duration">
            <span aria-hidden="true">{{ formatJobDuration(execution.duration_seconds) }}</span>
            <span class="sr-only">{{ jobDurationLabel(execution.duration_seconds, execution.duration_running) }}</span>
          </span>
        </button>
        <dl v-if="open === execution.id" :id="`execution-${execution.id}`" class="execution-facts">
          <template v-if="execution.tool_started_at">
            <dt>Started</dt><dd>{{ formatExactDateTime(execution.tool_started_at, timezone) }}</dd>
          </template>
          <template v-if="execution.tool_finished_at">
            <dt>Finished</dt><dd>{{ formatExactDateTime(execution.tool_finished_at, timezone) }}</dd>
          </template>
          <template v-if="execution.provider_outcome">
            <dt>Provider outcome</dt><dd>{{ execution.provider_outcome }}</dd>
          </template>
          <template v-if="execution.exit_code !== null">
            <dt>Exit code</dt><dd>{{ execution.exit_code }}</dd>
          </template>
          <template v-if="execution.resource_keys.length">
            <dt>Ran on</dt><dd>{{ machines(execution.resource_keys) }}</dd>
          </template>
        </dl>
      </li>
    </ul>
  </section>
</template>
