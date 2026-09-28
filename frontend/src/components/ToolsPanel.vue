<script setup lang="ts">
import type { GroupItem } from "../api";
import { formatCost, pluralize } from "../vocabulary";

defineProps<{ tools: GroupItem[]; periodLabel: string }>();
const emit = defineEmits<{ select: [toolId: string] }>();
</script>

<template>
  <section class="panel">
    <div class="panel-heading">
      <div>
        <h2>Tools in this period</h2>
        <p>What each tool cost in {{ periodLabel }}, highest first.</p>
      </div>
    </div>
    <div v-if="!tools.length" class="empty">No tools ran in this period.</div>
    <div v-else class="table-wrap">
      <table>
        <thead><tr><th>Tool</th><th>Jobs</th><th>Cost</th><th>Details</th></tr></thead>
        <tbody>
          <tr v-for="tool in tools" :key="`${tool.tool_id}@${tool.tool_version}`">
            <td>
              <button class="link-button" @click="emit('select', tool.tool_id || '')">
                {{ tool.tool_name || tool.tool_id }}
              </button>
              <small>{{ tool.tool_version || "Unversioned" }}</small>
            </td>
            <td>{{ tool.job_count }}</td>
            <td>
              <strong>{{ formatCost(tool.amount) }}</strong>
              <small v-if="tool.incomplete_count">
                {{ pluralize(tool.incomplete_count, "job") }} still need cost data
              </small>
            </td>
            <td>
              <details>
                <summary>Past jobs and identity</summary>
                <p class="mono">{{ tool.tool_id }}</p>
                <p v-if="tool.statistics?.sample_count">
                  Across {{ pluralize(tool.statistics.sample_count, "completed job") }}:
                  median {{ formatCost(tool.statistics.median) }},
                  95th percentile {{ formatCost(tool.statistics.p95) }}.
                  These describe past jobs; they are not a prediction of what the next job will cost.
                </p>
                <p v-else>Not enough completed jobs with known costs for past-job statistics.</p>
              </details>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>
</template>
