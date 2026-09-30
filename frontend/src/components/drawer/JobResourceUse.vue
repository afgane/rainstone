<script setup lang="ts">
import { computed } from "vue";
import type { JobResourceUse } from "../../api";
import { resourceUseView } from "../../jobDetail";
import {
  ABOVE_REQUEST_NOTE, MEASUREMENTS_EXPLANATION, MEASUREMENTS_HEADING, RESOURCE_USE_HEADING, SERVER_USE_NOTE,
  USAGE_NOT_RECORDED,
} from "../../vocabulary";
import JobUseRow from "./JobUseRow.vue";

const props = defineProps<{ use: JobResourceUse }>();
const view = computed(() => resourceUseView(props.use));
const aboveRequest = computed(() => view.value.rows.some(row => row.comparison?.aboveRequest));
</script>

<template>
  <section class="job-section" aria-labelledby="job-use-heading">
    <h3 id="job-use-heading">{{ RESOURCE_USE_HEADING }}</h3>
    <p v-if="view.serverJob" class="dialog-meta">{{ SERVER_USE_NOTE }}</p>
    <template v-else-if="view.unrecorded">
      <p class="dialog-meta">{{ USAGE_NOT_RECORDED }}</p>
      <p v-if="view.requested.length" class="dialog-meta">Requested: {{ view.requested.join(" · ") }}</p>
    </template>
    <template v-else>
      <JobUseRow v-for="row in view.rows" :key="row.key" :row="row" />
      <details class="inline-details">
        <summary>{{ MEASUREMENTS_HEADING }}</summary>
        <p>{{ MEASUREMENTS_EXPLANATION }}</p>
        <p v-if="aboveRequest">{{ ABOVE_REQUEST_NOTE }}</p>
      </details>
    </template>
  </section>
</template>
