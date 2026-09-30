<script setup lang="ts">
import { computed } from "vue";
import type { JobDetail } from "../../api";
import { TECHNICAL_HEADING } from "../../vocabulary";

const props = defineProps<{ detail: JobDetail }>();
// The cost lines' own wording: evidence for the estimate, not the plain-language explanation of it.
const basis = computed(() => props.detail.full_reason.split(" | ").filter(Boolean));
</script>

<template>
  <details class="inline-details job-disclosure">
    <summary>{{ TECHNICAL_HEADING }}</summary>
    <dl class="technical-facts">
      <dt>Tool</dt><dd class="mono">{{ detail.tool_id }}</dd>
      <template v-if="detail.tool_version">
        <dt>Version</dt><dd class="mono">{{ detail.tool_version }}</dd>
      </template>
      <dt>Job</dt><dd class="mono">{{ detail.source_id }}</dd>
      <dt>Snapshot</dt><dd class="mono">{{ detail.revision_id ?? "none" }}</dd>
      <template v-if="detail.runner">
        <dt>Runner</dt><dd class="mono">{{ detail.runner }}</dd>
      </template>
      <template v-if="detail.destination">
        <dt>Destination</dt><dd class="mono">{{ detail.destination }}</dd>
      </template>
    </dl>
    <template v-if="basis.length">
      <h4 class="technical-heading">Cost basis</h4>
      <ul class="cost-notes mono">
        <li v-for="line in basis" :key="line">{{ line }}</li>
      </ul>
    </template>
    <template v-for="resource in detail.resources" :key="resource.lifetime_id">
      <h4 class="technical-heading">Resource</h4>
      <dl class="technical-facts">
        <dt>Identifier</dt><dd class="mono">{{ resource.resource_key }}</dd>
        <dt>Provider</dt><dd class="mono">{{ resource.provider }}</dd>
        <template v-if="resource.region || resource.zone">
          <dt>Location</dt><dd class="mono">{{ [resource.region, resource.zone].filter(Boolean).join(" / ") }}</dd>
        </template>
        <template v-if="resource.machine_capacity">
          <dt>Capacity source</dt><dd class="mono">Google's published machine shapes</dd>
        </template>
        <template v-if="resource.timing_method">
          <dt>Timing method</dt><dd class="mono">{{ resource.timing_method }}</dd>
        </template>
      </dl>
    </template>
    <template v-if="detail.resource_use.metrics.length">
      <h4 class="technical-heading">Recorded metrics</h4>
      <dl class="technical-facts">
        <template v-for="metric in detail.resource_use.metrics" :key="`${metric.plugin}.${metric.name}`">
          <dt class="mono">{{ metric.plugin }}.{{ metric.name }}</dt>
          <dd class="mono">{{ metric.value }}{{ metric.unit ? ` ${metric.unit}` : "" }}</dd>
        </template>
        <dt>Scope</dt>
        <dd class="mono">
          {{ detail.resource_use.measurement_scope === "single_execution"
            ? "One run on one resource" : "Not tied to one run" }}
        </dd>
      </dl>
    </template>
  </details>
</template>
