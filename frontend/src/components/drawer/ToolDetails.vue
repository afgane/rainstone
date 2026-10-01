<script setup lang="ts">
import { computed } from "vue";
import type { ToolDetail } from "../../api";
import {
  contributorsHeading, excludedFromRanking, formatCost, needsCostData, TECHNICAL_HEADING, pluralize,
  RANKING_NOTE, SERVER_TOOL_NOTE, showJobs, statusLine,
} from "../../vocabulary";
import ScopedJobRow from "./ScopedJobRow.vue";

const props = defineProps<{ detail: ToolDetail; periodLabel: string }>();
const emit = defineEmits<{ open: [id: string]; "show-jobs": [key: string] }>();

const contributors = computed(() => props.detail.contributors);
const recordedSoFar = computed(() => props.detail.incomplete_job_count > 0 && props.detail.amount !== null);
const heading = computed(() => {
  const count = contributors.value.jobs.length;
  if (contributors.value.kind === "ranked") return contributorsHeading(count);
  if (contributors.value.kind === "server") return `Recent jobs on your Galaxy server`;
  if (contributors.value.kind === "zero") return "Recent jobs, which recorded no compute cost";
  return "Jobs contributing most to the cost";
});
/** Why no ranking is shown, rather than a ranking that cannot be trusted. */
const unavailable = computed(() => (props.detail.job_count === 0
  ? `No job of this tool matches the current filters in ${props.periodLabel}.`
  : "None of this tool's jobs has complete cost data yet, so they cannot be ranked by cost."));
const statistics = computed(() => props.detail.statistics);
</script>

<template>
  <p class="dialog-amount">
    <strong>{{ formatCost(detail.amount) }}</strong>
    <span>Cost in {{ periodLabel }}{{ recordedSoFar ? ", recorded so far" : "" }}</span>
  </p>
  <dl class="drawer-facts">
    <dt>Jobs</dt><dd>{{ detail.job_count }}</dd>
    <template v-if="detail.by_status.length">
      <dt>By status</dt>
      <dd><span v-for="piece in detail.by_status" :key="piece.status" class="fact-line">{{ statusLine(piece) }}</span></dd>
    </template>
    <template v-if="detail.versions.length">
      <dt>{{ detail.versions.length === 1 ? "Version" : "Versions" }}</dt>
      <dd>
        <span v-for="entry in detail.versions" :key="entry.version ?? ''" class="fact-line">
          {{ entry.version ?? "Unversioned" }} ({{ pluralize(entry.job_count, "job") }})
        </span>
      </dd>
    </template>
  </dl>
  <p v-if="detail.incomplete_job_count" class="dialog-meta">
    {{ needsCostData(detail.incomplete_job_count, "job") }}, so this amount is a subtotal.
  </p>

  <section class="job-section" aria-labelledby="tool-jobs-heading">
    <h3 id="tool-jobs-heading">{{ heading }}</h3>
    <template v-if="contributors.kind === 'unavailable'">
      <p class="dialog-meta">{{ unavailable }}</p>
    </template>
    <template v-else>
      <p v-if="contributors.kind === 'ranked'" class="dialog-meta">
        Ranked by their cost in {{ periodLabel }}. {{ RANKING_NOTE }}
        <template v-if="contributors.excluded_job_count">
          {{ excludedFromRanking(contributors.excluded_job_count) }}
        </template>
      </p>
      <p v-else-if="contributors.kind === 'server'" class="dialog-meta">{{ SERVER_TOOL_NOTE }}</p>
      <ul class="job-list" role="list" data-with-cost="true">
        <ScopedJobRow
          v-for="job in contributors.jobs" :key="job.id" :job="job" :scope="`Cost in ${periodLabel}`"
          @open="emit('open', $event)"
        />
      </ul>
    </template>
    <button
      v-if="detail.job_count" type="button" class="secondary show-jobs"
      @click="emit('show-jobs', detail.key)"
    >{{ showJobs(detail.job_count) }}</button>
    <p v-if="detail.job_count" class="dialog-meta">Lists every one of them on the page, with its totals.</p>
  </section>

  <details class="inline-details">
    <summary>{{ TECHNICAL_HEADING }}</summary>
    <p v-if="statistics.sample_count">
      Across {{ pluralize(statistics.sample_count, "completed job") }} with complete cost data:
      median {{ formatCost(statistics.median) }}, 95th percentile {{ formatCost(statistics.p95) }}.
      These describe past jobs; they are not a prediction of what the next job will cost.
    </p>
    <p v-else>Not enough completed jobs with known costs for past-job statistics.</p>
    <p v-if="statistics.sample_count && statistics.excluded_count">
      {{ pluralize(statistics.excluded_count, "job") }} left out: not completed, or missing cost data.
    </p>
    <p class="mono">{{ detail.tool_ids.join(", ") || detail.key }}</p>
  </details>
</template>
