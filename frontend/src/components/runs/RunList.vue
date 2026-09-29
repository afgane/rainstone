<script setup lang="ts">
import { Download } from "@lucide/vue";
import { computed } from "vue";
import type { Invocation } from "../../api";
import {
  CLEAR_FILTERS, COST_SO_FAR, durationText, formatCost, formatDateTime, needsCostData, pluralize,
  RUN_SORTS, RUN_TOTAL, runStatusLabel, showingOf, showMore,
} from "../../vocabulary";
import { RUN_PAGE_SIZE } from "../../api";

const props = defineProps<{
  runs: Invocation[];
  total: number;
  sort: string;
  periodLabel: string;
  timezone: string;
  openRunId: string;
  hoverRunId: string;
  loadingMore: boolean;
}>();
const emit = defineEmits<{
  open: [id: string, opener: HTMLElement];
  sort: [id: string];
  more: [];
  clear: [];
  export: [];
  hover: [id: string | null];
}>();

const remaining = computed(() => props.total - props.runs.length);
</script>

<template>
  <section
    class="panel"
    aria-labelledby="run-list-title"
  >
    <div class="panel-heading">
      <div>
        <h2 id="run-list-title">
          Runs in this period
        </h2>
        <p>
          {{ pluralize(total, "workflow run") }} that used compute in {{ periodLabel }}. Each total covers the whole run.
        </p>
      </div>
      <div class="list-tools">
        <label>Sort by
          <select
            :value="sort"
            @change="emit('sort', ($event.target as HTMLSelectElement).value)"
          >
            <option
              v-for="choice in RUN_SORTS"
              :key="choice.id"
              :value="choice.id"
            >{{ choice.label }}</option>
          </select>
        </label>
        <button
          class="secondary"
          type="button"
          @click="emit('export')"
        >
          <Download
            :size="16"
            aria-hidden="true"
          /> Export CSV
        </button>
      </div>
    </div>
    <div
      v-if="!runs.length"
      class="empty"
    >
      No workflow runs match these filters.
      <button
        class="link-button"
        type="button"
        @click="emit('clear')"
      >
        {{ CLEAR_FILTERS }}
      </button>
    </div>
    <template v-else>
      <ul class="run-list">
        <li
          v-for="run in runs"
          :key="run.id"
        >
          <button
            class="run-card"
            type="button"
            data-detail-trigger
            :data-run-id="run.id"
            :class="{ 'row-hl': hoverRunId === run.id, 'row-sel': openRunId === run.id }"
            @click="emit('open', run.id, $event.currentTarget as HTMLElement)"
            @pointerenter="emit('hover', run.id)"
            @pointerleave="emit('hover', null)"
            @focus="emit('hover', run.id)"
            @blur="emit('hover', null)"
          >
            <span class="run-title">
              <strong>{{ run.workflow_name }}</strong>
              <small>
                {{ formatDateTime(run.started_at, timezone) }} · {{ durationText(run.duration_seconds, run.run_status) }}
              </small>
            </span>
            <span class="run-meta">
              <span
                class="status"
                :data-status="run.run_status"
              >{{ runStatusLabel(run.run_status) }}</span>
              <small>{{ pluralize(run.run_job_count, "job") }}</small>
            </span>
            <span class="run-cost">
              <strong>{{ formatCost(run.run_total) }}</strong>
              <small>{{ run.run_status === "running" ? COST_SO_FAR : RUN_TOTAL }}</small>
              <!-- The period share is only worth saying when it differs. -->
              <small v-if="run.amount !== run.run_total">
                {{ formatCost(run.amount) }} in the selected period
              </small>
              <small v-if="run.run_unpriced_job_count">{{ needsCostData(run.run_unpriced_job_count) }}</small>
              <small v-if="run.timing_unavailable">Timing unavailable for this run</small>
            </span>
          </button>
        </li>
      </ul>
      <div class="list-foot">
        <span>{{ showingOf(runs.length, total) }}</span>
        <button
          v-if="remaining > 0"
          class="secondary"
          type="button"
          :disabled="loadingMore"
          @click="emit('more')"
        >
          {{ showMore(Math.min(RUN_PAGE_SIZE, remaining)) }}
        </button>
      </div>
    </template>
  </section>
</template>
