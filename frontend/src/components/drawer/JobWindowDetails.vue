<script setup lang="ts">
import { computed } from "vue";
import type { WindowDetail } from "../../api";
import {
  formatCost, needsCostData, pluralize, SPAN_NOTE, statusLine,
} from "../../vocabulary";
import ScopedJobRow from "./ScopedJobRow.vue";

const props = defineProps<{
  detail: WindowDetail;
  /** "this day", "this hour" or "this week". */
  noun: string;
  /** True while another page of jobs is being fetched. */
  paging: boolean;
}>();
const emit = defineEmits<{ open: [id: string]; page: [offset: number] }>();

const recordedSoFar = computed(() => props.detail.incomplete_job_count > 0 && props.detail.amount !== null);
const first = computed(() => (props.detail.total ? props.detail.offset + 1 : 0));
const last = computed(() => Math.min(props.detail.total, props.detail.offset + props.detail.items.length));
</script>

<template>
  <p class="dialog-amount">
    <strong>{{ detail.job_count ? formatCost(detail.amount) : "No jobs" }}</strong>
    <span v-if="detail.job_count">
      Cost during {{ noun }}{{ recordedSoFar ? ", recorded so far" : "" }}{{ detail.provisional ? ", still running" : "" }}
    </span>
  </p>
  <dl v-if="detail.job_count" class="drawer-facts">
    <dt>Jobs</dt><dd>{{ detail.job_count }}</dd>
    <dt>By status</dt>
    <dd><span v-for="piece in detail.by_status" :key="piece.status" class="fact-line">{{ statusLine(piece) }}</span></dd>
  </dl>
  <p v-if="detail.incomplete_job_count" class="dialog-meta">
    {{ needsCostData(detail.incomplete_job_count, "job") }}, so this amount is a subtotal.
  </p>

  <section class="job-section" aria-labelledby="window-jobs-heading">
    <h3 id="window-jobs-heading">Jobs, highest cost first</h3>
    <p v-if="!detail.job_count" class="dialog-meta">No job matching these filters had compute during {{ noun }}.</p>
    <template v-else>
      <p class="dialog-meta">{{ SPAN_NOTE }}</p>
      <ul class="job-list" role="list" data-with-cost="true" :class="{ refetching: paging }" :aria-busy="paging">
        <ScopedJobRow
          v-for="job in detail.items" :key="job.id" :job="job" :scope="`Cost during ${noun}`"
          @open="emit('open', $event)"
        />
      </ul>
      <nav v-if="detail.total > detail.limit" class="pagination drawer-pages" aria-label="Pages of these jobs">
        <button
          type="button" :disabled="detail.offset === 0 || paging"
          @click="emit('page', Math.max(0, detail.offset - detail.limit))"
        >Previous</button>
        <span>{{ first }}–{{ last }} of {{ pluralize(detail.total, "job") }}</span>
        <button
          type="button" :disabled="detail.offset + detail.limit >= detail.total || paging"
          @click="emit('page', detail.offset + detail.limit)"
        >Next</button>
      </nav>
    </template>
  </section>
</template>
