<script setup lang="ts">
import { computed } from "vue";
import type { Summary } from "../../api";
import {
  ADDITIONAL_SERVER_SENTENCE, formatCost, formatRateInCents, inProgressNote, RUN_COMPUTE, SERVER_COMPUTE,
  serverQualifiers, sinceLaunch, unrecordedNote,
} from "../../vocabulary";

const props = defineProps<{
  summary: Summary;
  periodText: string;
}>();
const emit = defineEmits<{ server: [] }>();

const empty = computed(() => props.summary.job_count === 0);
const recordedSoFar = computed(() =>
  props.summary.unpriced_job_count > 0 && props.summary.amount !== null);
const amountText = computed(() => (empty.value ? "No jobs" : formatCost(props.summary.amount)));

const launch = computed(() => props.summary.current_launch);
// The whole server's session, whatever period or filter the report has.
const serverAmount = computed(() => {
  const current = launch.value;
  if (current?.completeness === "complete") return formatCost(current.total_since_launch);
  if (current?.completeness === "partial") return formatCost(current.known_subtotal);
  return "Not available";
});
const serverPartial = computed(() => launch.value?.completeness === "partial");
const uptime = computed(() => {
  const current = launch.value;
  if (!current?.launch_at) return "Launch time unavailable";
  return sinceLaunch(current.elapsed_seconds === null ? null : Number(current.elapsed_seconds));
});
const qualifiers = computed(() => serverQualifiers(launch.value, Boolean(props.summary.imported_snapshot)));
</script>

<template>
  <div class="cost-cards" :data-server="summary.can_view_infrastructure">
    <section class="figure cost-card featured" aria-labelledby="figure-run">
      <p id="figure-run" class="eyebrow">{{ RUN_COMPUTE }}</p>
      <p class="figure-amount">{{ amountText }}</p>
      <p class="figure-line">
        {{ periodText }}<template v-if="recordedSoFar"> · recorded so far</template>
      </p>
      <p v-if="summary.in_progress_job_count" class="figure-line">
        {{ inProgressNote(summary.in_progress_job_count) }}
      </p>
      <p v-if="summary.unrecorded_job_count" class="figure-line">
        {{ unrecordedNote(summary.unrecorded_job_count) }}
      </p>
    </section>
    <template v-if="summary.can_view_infrastructure">
      <span class="cost-plus" aria-hidden="true">+</span>
      <section class="figure cost-card" aria-labelledby="figure-server">
        <p id="figure-server" class="eyebrow">{{ SERVER_COMPUTE }}</p>
        <p class="figure-amount">
          {{ serverAmount }}<span v-if="launch?.hourly_rate" class="figure-qualifier">{{ formatRateInCents(launch.hourly_rate) }}</span>
        </p>
        <p class="figure-line">
          {{ uptime }}<template v-if="serverPartial"> · recorded so far</template>
        </p>
        <p class="figure-line cost-card-foot">
          <span v-for="label in qualifiers" :key="label" class="quiet-label">{{ label }}</span>
          <button type="button" class="link-button" @click="emit('server')">Server details</button>
        </p>
      </section>
    </template>
  </div>
  <p v-if="summary.can_view_infrastructure" class="cost-relation">{{ ADDITIONAL_SERVER_SENTENCE }}</p>
</template>
