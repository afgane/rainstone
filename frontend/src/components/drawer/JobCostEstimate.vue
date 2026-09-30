<script setup lang="ts">
import { computed } from "vue";
import type { JobDetail } from "../../api";
import { buildLanes } from "../../jobDetail";
import {
  COST_COMPONENTS_NOTE, COST_ESTIMATE_HEADING, COST_EXCLUSIONS, COST_METHOD, dayKey, environmentLabel,
  formatClock, formatCost, formatDateTime, GPU_PRICE_NOTE, purchaseModelLabel, SERVER_GROUP_NOTE,
  TIMING_ESTIMATE_NOTE,
} from "../../vocabulary";

const props = defineProps<{ detail: JobDetail; timezone: string }>();
const lanes = computed(() => buildLanes(props.detail));
const serverOnly = computed(() => props.detail.full_quality === "known_zero");
const method = computed(() => {
  if (serverOnly.value) return SERVER_GROUP_NOTE;
  const usedGpus = props.detail.resources.some(resource => resource.machine_capacity?.gpu);
  return usedGpus ? `${COST_METHOD} ${GPU_PRICE_NOTE}` : COST_METHOD;
});

// The end says its date only when it is not the start's day.
function timeSpan(start: string | null, end: string | null, ongoing = false): string {
  if (!start) return "";
  const from = formatDateTime(start, props.timezone);
  if (!end) return `${from}, still in use`;
  const to = dayKey(start, props.timezone) === dayKey(end, props.timezone)
    ? formatClock(end, props.timezone) : formatDateTime(end, props.timezone);
  return `${from} to ${to}${ongoing ? " (recorded so far)" : ""}`;
}
</script>

<template>
  <details class="inline-details job-disclosure">
    <summary>{{ COST_ESTIMATE_HEADING }}</summary>
    <p>{{ method }}</p>
    <p>{{ COST_EXCLUSIONS }}</p>

    <template v-if="detail.resources.length && !serverOnly">
      <ul class="step-list cost-resources">
        <li v-for="resource in detail.resources" :key="resource.lifetime_id">
          <span class="resource-name">
            {{ resource.machine_type ?? "Machine type not recorded" }}
            <small v-if="resource.purchase_model">{{ purchaseModelLabel(resource.purchase_model) }}</small>
          </span>
          <span v-if="detail.resources.length > 1" class="resource-amount">{{ formatCost(resource.amount) }}</span>
          <small class="resource-window">
            {{ environmentLabel(resource.capacity_relationship) }}
            <template v-if="resource.resource_started_at">
              · {{ timeSpan(resource.resource_started_at, resource.resource_finished_at) }}
            </template>
          </small>
          <small v-if="resource.shared_attempt_count > 1">
            Charged once for {{ resource.shared_attempt_count }} runs that reused it
          </small>
        </li>
      </ul>
      <p v-if="detail.resources.length > 1" class="dialog-meta">{{ COST_COMPONENTS_NOTE }}</p>
    </template>

    <div v-if="lanes" class="lanes">
      <div class="lane" data-lane="tool">
        <span class="lane-label">Tool run</span>
        <span class="lane-track" aria-hidden="true">
          <span
            class="lane-bar" :style="{ left: `${lanes.tool.startPercent}%`, width: `${lanes.tool.endPercent - lanes.tool.startPercent}%` }"
          />
        </span>
        <span class="lane-times">{{ timeSpan(lanes.tool.start, lanes.tool.end, detail.duration_running) }}</span>
      </div>
      <div class="lane" data-lane="compute">
        <span class="lane-label">Compute lifetime</span>
        <span class="lane-track" aria-hidden="true">
          <span
            class="lane-bar" :data-ongoing="lanes.computeOngoing"
            :style="{ left: `${lanes.compute.startPercent}%`, width: `${lanes.compute.endPercent - lanes.compute.startPercent}%` }"
          />
        </span>
        <span class="lane-times">{{ timeSpan(lanes.compute.start, lanes.compute.end, lanes.computeOngoing) }}</span>
      </div>
      <p class="dialog-meta">{{ TIMING_ESTIMATE_NOTE }}</p>
    </div>

    <p v-if="detail.full_job_amount !== null" class="mono">Exact amount: {{ detail.full_job_amount }} USD</p>
  </details>
</template>
