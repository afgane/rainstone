<script setup lang="ts">
import { computed } from "vue";
import type { Infrastructure } from "../api";
import { formatMachineCapacity } from "../jobDetail";
import { formatCost, formatDateTime, formatDuration, formatRateInCents, pluralize } from "../vocabulary";
import ServerActivityPlot from "./ServerActivityPlot.vue";

const props = defineProps<{ server: Infrastructure | null; timezone: string; imported: boolean }>();
const emit = defineEmits<{ refresh: [] }>();
const launch = computed(() => props.server?.current_launch ?? null);
const total = computed(() => {
  const current = launch.value;
  if (current?.completeness === "complete") return formatCost(current.total_since_launch);
  if (current?.completeness === "partial") return formatCost(current.known_subtotal);
  return "Not available";
});
const duration = computed(() => {
  const seconds = launch.value?.elapsed_seconds;
  if (seconds === null || seconds === undefined || !Number.isFinite(Number(seconds)) || Number(seconds) < 0) {
    return "Not available";
  }
  if (Number(seconds) >= 86400) {
    const days = Math.floor(Number(seconds) / 86400), hours = Math.floor(Number(seconds) % 86400 / 3600);
    return `${pluralize(days, "day")}${hours ? ` ${hours} h` : ""}`;
  }
  return Number(seconds) < 60 ? "Less than 1 min" : formatDuration(Number(seconds));
});
const stateLabel = computed(() => {
  if (launch.value?.ended_at) return "Stopped";
  switch (launch.value?.state) {
    case "RUNNING": return "Running at the last observation";
    case "PROVISIONING": case "STAGING": return "Starting at the last observation";
    case "TERMINATED": case "STOPPED": return "Stopped at the last observation";
    case "STOPPING": return "Stopping at the last observation";
    case "SUSPENDED": return "Suspended at the last observation";
    case "SUSPENDING": return "Suspending at the last observation";
    default: return "Server state unavailable";
  }
});
</script>

<template>
  <section class="panel server-panel" aria-label="Galaxy server session">
    <div class="server-summary">
      <h2 class="eyebrow">Current server session</h2>
      <p class="server-total">{{ total }}</p>
      <p class="server-cost-label">
        Estimated compute cost since this server started<template v-if="launch?.completeness === 'partial'"> · recorded so far</template>
      </p>
      <p v-if="launch?.unavailable_reason" class="server-notice">{{ launch.unavailable_reason }}</p>
      <div class="server-metrics">
        <span>{{ launch?.hourly_rate ? formatRateInCents(launch.hourly_rate) : 'Hourly rate unavailable' }}</span>
      </div>
      <p
        v-if="!launch?.hourly_rate && launch?.hourly_rate_unavailable_reason
          && launch.hourly_rate_unavailable_reason !== launch.unavailable_reason"
        class="server-notice"
      >
        {{ launch.hourly_rate_unavailable_reason }}
      </p>
      <p class="server-configuration">
        Server configuration:
        <strong>{{ launch?.machine_capacity ? formatMachineCapacity(launch.machine_capacity) : 'Not available' }}</strong>
      </p>
    </div>

    <div class="server-session">
      <ServerActivityPlot
        :activity="server?.activity ?? null" :started-at="launch?.launch_at ?? null"
        :recorded-through="launch?.as_of ?? null" :timezone="timezone" :duration="duration"
      />
      <p class="server-state"><span v-if="imported" class="quiet-label">Snapshot</span>{{ stateLabel }}</p>
      <p v-if="imported" class="server-snapshot-note">These figures stop at the last observation in this snapshot.</p>
      <p v-else-if="launch?.stale" class="server-notice" role="status">
        {{ launch.stale_reason || 'The server has not been observed recently. These figures stop at the recorded time above.' }}
      </p>
    </div>

    <p class="server-explanation">
      Your Galaxy server keeps running between jobs. Its cost includes that time and is additional to run compute.
    </p>
    <details class="inline-details server-details">
      <summary>What's included in this estimate?</summary>
      <p>
        This covers the whole server's compute during its current session, including time between jobs.
        Earlier sessions are not included; starting the server again starts a fresh total.
        Report dates and job filters do not change this figure.
      </p>
      <p>
        Costs are estimates in USD at published cloud prices. Disks, networking, discounts,
        credits, taxes and other cloud charges are excluded.
      </p>
    </details>
    <details class="inline-details server-details">
      <summary>Technical details</summary>
      <dl class="server-facts">
        <dt>Machine type</dt><dd>{{ launch?.machine_type || 'Not available' }}</dd>
        <dt>Region</dt><dd>{{ launch?.region || 'Not available' }}</dd>
        <dt>Server</dt><dd>{{ launch?.name || launch?.resource_uid || 'Not available' }}</dd>
        <dt>Exact hourly rate</dt><dd>{{ launch?.hourly_rate ? `${launch.hourly_rate} USD/hour` : 'Not available' }}</dd>
        <dt>Start time source</dt><dd>{{ launch?.launch_source || 'Not available' }}</dd>
        <template v-if="launch?.price">
          <dt>Price catalog</dt><dd>{{ launch.price.catalog_id }}</dd>
          <dt>Price effective from</dt>
          <dd>{{ launch.price.effective_from ? formatDateTime(launch.price.effective_from, timezone) : 'Not available' }}</dd>
        </template>
        <template v-if="launch?.calculation_version">
          <dt>Calculation</dt><dd class="mono">{{ launch.calculation_version }} · {{ launch.calculation_revision || 'Revision unavailable' }}</dd>
        </template>
      </dl>
      <p>
        Time runs from the provider's session start to the last observation, or the recorded stop time.
        Published rates for the machine and purchase model apply, with the provider's one-minute minimum applied once.
      </p>
    </details>
  </section>
  <div class="server-footer">
    <span>Estimated compute cost · USD · Times shown in {{ timezone }}</span>
    <button type="button" class="link-button" @click="emit('refresh')">Refresh</button>
  </div>
</template>
