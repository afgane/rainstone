<script setup lang="ts">
import { computed } from "vue";
import type { JobDetail } from "../../api";
import { buildLanes, phaseBreakdown, type PhaseRow } from "../../jobDetail";
import {
  COST_COMPONENTS_NOTE, COST_ESTIMATE_HEADING, COST_EXCLUSIONS, COST_METHOD, dayKey, environmentLabel,
  formatClock, formatCompactCost, formatCost, formatDateTime, formatJobDuration, formatShare, GPU_PRICE_NOTE,
  PHASES_HEADING, purchaseModelLabel, SERVER_GROUP_NOTE, TIMING_ESTIMATE_NOTE, UNATTRIBUTED_PHASES_NOTE,
} from "../../vocabulary";

const props = defineProps<{ detail: JobDetail; timezone: string }>();
const lanes = computed(() => buildLanes(props.detail));
const serverOnly = computed(() => props.detail.full_quality === "known_zero");
const phases = computed(() => (serverOnly.value ? null : phaseBreakdown(props.detail)));

function phaseSentence(row: PhaseRow): string {
  const cost = row.amount === null ? "cost not available" : `${formatCost(row.amount)}${row.complete ? "" : " known so far"}`;
  const share = row.share === null ? "" : `, ${formatShare(row.share)} of the job's cost`;
  return `${row.label}: ${formatJobDuration(row.seconds)}, ${cost}${share}`;
}
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
      <!-- The compute bar's Running segment already is the tool run, so the separate lane is only drawn without phases. -->
      <div v-if="!lanes.phases.length" class="lane" data-lane="tool">
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
            class="lane-bar" :data-ongoing="lanes.computeOngoing" :data-phased="lanes.phases.length > 0"
            :style="{ left: `${lanes.compute.startPercent}%`, width: `${lanes.compute.endPercent - lanes.compute.startPercent}%` }"
          >
            <span
              v-for="segment in lanes.phases" :key="segment.phase" class="lane-phase" :data-phase="segment.phase"
              :style="{ left: `${segment.startPercent}%`, width: `${segment.endPercent - segment.startPercent}%` }"
            />
          </span>
        </span>
        <span class="lane-times">{{ timeSpan(lanes.compute.start, lanes.compute.end, lanes.computeOngoing) }}</span>
      </div>
      <p class="dialog-meta">{{ TIMING_ESTIMATE_NOTE }}</p>
    </div>

    <div v-if="phases" class="phase-breakdown">
      <h4 class="technical-heading">{{ PHASES_HEADING }}</h4>
      <ul v-if="phases.rows.length" class="phase-rows">
        <li v-for="row in phases.rows" :key="row.phase" :data-phase="row.phase">
          <span class="phase-name" aria-hidden="true"><span class="phase-swatch" />{{ row.label }}</span>
          <span class="phase-duration" aria-hidden="true">{{ formatJobDuration(row.seconds) }}</span>
          <span class="phase-cost" aria-hidden="true" :title="row.amount ? `${row.amount} USD` : undefined">
            {{ formatCompactCost(row.amount) }}<template v-if="row.amount !== null && !row.complete"> known so far</template>
          </span>
          <span class="phase-share" aria-hidden="true">{{ row.share === null ? "" : formatShare(row.share) }}</span>
          <span class="sr-only">{{ phaseSentence(row) }}</span>
        </li>
      </ul>
      <p v-for="reason in phases.unattributedReasons" :key="reason" class="dialog-meta">
        {{ UNATTRIBUTED_PHASES_NOTE }} {{ reason }}
      </p>
    </div>

    <p v-if="detail.full_job_amount !== null" class="mono">Exact amount: {{ detail.full_job_amount }} USD</p>
  </details>
</template>
