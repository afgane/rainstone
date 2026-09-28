<script setup lang="ts">
import { computed } from "vue";
import type { CurrentLaunch } from "../api";
import { formatCost, formatDateTime, formatRate } from "../vocabulary";

const props = defineProps<{ launch: CurrentLaunch | null; timezone: string }>();

const total = computed(() => {
  const launch = props.launch;
  if (!launch?.launch_at) return "Launch time unavailable";
  if (launch.completeness === "complete") return formatCost(launch.total_since_launch);
  if (launch.completeness === "partial") return `${formatCost(launch.known_subtotal)} recorded so far`;
  return "Not available";
});
</script>

<template>
  <div class="quiet-amount">
    <span :title="launch?.hourly_rate || undefined">{{ formatRate(launch?.hourly_rate) }}</span>
    <small v-if="launch?.hourly_rate_unavailable_reason && !launch.hourly_rate">
      {{ launch.hourly_rate_unavailable_reason }}
    </small>
    <span :title="launch?.total_since_launch || launch?.known_subtotal || undefined">
      Total since launched: {{ total }}
    </span>
    <small v-if="launch?.unavailable_reason">{{ launch.unavailable_reason }}</small>
    <small v-if="launch?.launch_at">Launched {{ formatDateTime(launch.launch_at, timezone) }}</small>
    <small v-if="launch?.as_of" :class="{ stale: launch.stale }">
      Calculated through {{ formatDateTime(launch.as_of, timezone) }}{{ launch.stale ? " (stale)" : "" }}
    </small>
    <small v-if="launch?.stale_reason">{{ launch.stale_reason }}</small>
    <small>Estimated compute cost · USD</small>
  </div>
</template>

