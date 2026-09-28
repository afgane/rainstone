<script setup lang="ts">
import { computed } from "vue";
import type { Infrastructure } from "../api";
import { formatDateTime, SERVER_EXPLANATION } from "../vocabulary";
import ServerLaunchFigures from "./ServerLaunchFigures.vue";

const props = defineProps<{ server: Infrastructure | null; timezone: string }>();
const launch = computed(() => props.server?.current_launch ?? null);
</script>

<template>
  <section class="panel">
    <div class="panel-heading">
      <div><h2>Galaxy server compute cost</h2><p>{{ SERVER_EXPLANATION }}</p></div>
    </div>
    <ServerLaunchFigures :launch="launch" :timezone="timezone" />
    <dl v-if="launch?.resource_uid" class="server-facts">
      <dt>Machine</dt>
      <dd>
        {{ launch.machine_type || "Unknown machine type" }} · {{ launch.region || "unknown region" }}
        <small>{{ launch.name || launch.resource_uid }} · {{ launch.state || "state unknown" }}</small>
      </dd>
      <dt>Launch</dt>
      <dd>
        {{ launch.launch_at ? formatDateTime(launch.launch_at, timezone) : "Launch time unavailable" }}
        <small v-if="launch.launch_source">From {{ launch.launch_source }}</small>
      </dd>
      <dt>Rate</dt>
      <dd>
        {{ launch.hourly_rate ? `${launch.hourly_rate} ${launch.currency}/hour` : "Not available" }}
        <small v-if="launch.price">
          Catalog {{ launch.price.catalog_id }}{{ launch.price.effective_from
            ? `, effective ${formatDateTime(launch.price.effective_from, timezone)}` : "" }}
        </small>
      </dd>
      <dt>Calculated through</dt>
      <dd>{{ launch.as_of ? formatDateTime(launch.as_of, timezone) : "No observation" }}</dd>
    </dl>
    <div class="callout">
      {{ launch?.scope }} Earlier launches are not included: a new launch starts a fresh total.
      Time is the provider's start of the current session up to the last observation, priced at
      public catalog rates for its machine and purchase model, with the provider's one-minute minimum applied once.
    </div>
  </section>
</template>
