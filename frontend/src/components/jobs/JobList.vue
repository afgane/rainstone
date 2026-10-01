<script setup lang="ts">
import { Download } from "@lucide/vue";
import { computed } from "vue";
import type { Job, Meta } from "../../api";
import {
  capacityLabel, formatDateTime, formatJobDuration, JOB_SORTS, jobAmountText, jobDurationLabel,
  jobStateKind, jobStateLabel, originLabel, otherRuns, pluralize, qualityLabel, undatedSentence,
} from "../../vocabulary";
import JobStateIcon from "../drawer/JobStateIcon.vue";

const props = defineProps<{
  jobs: Job[];
  undatedJobs: Job[];
  undated: Meta["undated"];
  total: number;
  offset: number;
  limit: number;
  sort: string;
  direction: "asc" | "desc";
  periodLabel: string;
  timezone: string;
  openJobId: string;
  /** True while another page or order is being fetched. */
  loading: boolean;
}>();
const emit = defineEmits<{
  detail: [id: string, opener: HTMLElement];
  run: [id: string, opener: HTMLElement];
  sort: [sort: string, direction: "asc" | "desc"];
  page: [offset: number];
  export: [];
  "more-undated": [];
}>();

const choice = computed(() => JOB_SORTS.find(
  option => option.sort === props.sort && option.direction === props.direction)?.id ?? "link");
function choose(event: Event) {
  const next = JOB_SORTS.find(option => option.id === (event.target as HTMLSelectElement).value);
  if (next) emit("sort", next.sort, next.direction);
}
const first = computed(() => (props.total ? props.offset + 1 : 0));
const last = computed(() => Math.min(props.total, props.offset + props.jobs.length));

/** Where it ran and how complete its cost is, said once and briefly. */
function context(job: Job): string {
  if (job.quality === "known_zero") return "Used your Galaxy server";
  const quality = qualityLabel(job.quality);
  return quality === "Estimated" ? capacityLabel(job.capacities) : quality;
}
</script>

<template>
  <section class="panel" aria-labelledby="job-list-title" :aria-busy="loading">
    <div class="panel-heading">
      <div>
        <h2 id="job-list-title">Jobs in this period</h2>
        <p>
          {{ pluralize(total, "job") }} · the cost shown is the part used in {{ periodLabel }}.
          Open a job for its explanation.
        </p>
      </div>
      <div class="list-tools">
        <label>Sort by
          <select :value="choice" @change="choose">
            <option v-if="choice === 'link'" value="link">As linked</option>
            <option v-for="option in JOB_SORTS" :key="option.id" :value="option.id">{{ option.label }}</option>
          </select>
        </label>
        <button class="secondary" type="button" @click="emit('export')">
          <Download :size="16" aria-hidden="true" /> Export CSV
        </button>
      </div>
    </div>
    <div v-if="!jobs.length" class="empty">No jobs match this period.</div>
    <ul v-else class="job-cards" :class="{ refetching: loading }" role="list">
      <!-- The job's name opens it and covers the whole card; the run it names is a control of its own. -->
      <li
        v-for="job in jobs" :key="job.id" class="job-card"
        :class="{ 'row-sel': openJobId === job.id }"
      >
        <span class="job-card-title">
          <button
            type="button" class="job-open" data-detail-trigger :data-job-id="job.id"
            @click="emit('detail', job.id, $event.currentTarget as HTMLElement)"
          >{{ job.tool_name }}</button>
          <small v-if="job.origin_run" class="origin" data-origin="workflow">
            Part of
            <button
              type="button" class="link-button origin-run" data-detail-trigger :data-run-id="job.origin_run.id"
              @click="emit('run', job.origin_run.id, $event.currentTarget as HTMLElement)"
            >{{ job.origin_run.workflow_name }}</button>
            {{ otherRuns((job.origin_run_count ?? 1) - 1) }}
          </small>
          <small v-else class="origin" :data-origin="job.origin ?? 'unknown'">{{ originLabel(job.origin) }}</small>
        </span>
        <span class="job-card-when">
          <span class="job-state-text" :data-kind="jobStateKind(job.state)">
            <JobStateIcon :state="job.state" />{{ jobStateLabel(job.state) }}
          </span>
          <small>Submitted {{ formatDateTime(job.created_at, timezone) }}</small>
        </span>
        <span class="job-card-duration">
          <span aria-hidden="true">{{ formatJobDuration(job.duration_seconds) }}{{ job.duration_running ? " so far" : "" }}</span>
          <span class="sr-only">{{ job.duration_seconds === null || job.duration_seconds === undefined
            ? "Duration not recorded" : jobDurationLabel(job.duration_seconds, job.duration_running) }}</span>
        </span>
        <span class="job-card-cost">
          <strong>{{ jobAmountText(job.amount, job.quality) }}</strong>
          <small>{{ context(job) }}</small>
        </span>
      </li>
    </ul>
    <nav v-if="total > limit" class="pagination" aria-label="Pages of jobs">
      <button type="button" :disabled="offset === 0 || loading" @click="emit('page', Math.max(0, offset - limit))">
        Previous
      </button>
      <span>{{ first }}–{{ last }} of {{ pluralize(total, "job") }}</span>
      <button type="button" :disabled="offset + limit >= total || loading" @click="emit('page', offset + limit)">
        Next
      </button>
    </nav>
    <details v-if="undated?.job_count" class="inline-details">
      <summary>{{ undatedSentence(undated.job_count) }}</summary>
      <p>
        Their cost evidence has no time it can be placed at, so no period can claim them. They are
        listed here for inspection only and are not part of the totals or the export.
      </p>
      <ul class="step-list">
        <li v-for="job in undatedJobs" :key="job.id">
          <button
            class="link-button" data-detail-trigger :data-job-id="job.id"
            @click="emit('detail', job.id, $event.currentTarget as HTMLElement)"
          >{{ job.tool_name }}</button>
          <span>{{ jobStateLabel(job.state) }}</span>
          <small>Submitted {{ formatDateTime(job.created_at, timezone) }} · {{ qualityLabel(job.quality) }}</small>
        </li>
      </ul>
      <p v-if="undated.job_count > undatedJobs.length">
        Showing {{ undatedJobs.length }} of {{ undated.job_count }}.
        <button class="link-button" @click="emit('more-undated')">Show more</button>
      </p>
    </details>
  </section>
</template>
