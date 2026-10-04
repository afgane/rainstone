<script setup lang="ts">
import { Search, X } from "@lucide/vue";
import { computed } from "vue";
import type { ReportState, RunFilterOptions } from "../../api";
import {
  ALL_WORKFLOWS, CLEAR_FILTERS, focusChipLabel, groupedChipLabel, NO_ACTIVE_FILTERS, OUTCOME_FIELD,
  OUTCOMES, PAGE_FILTERS_HEADING, PAGE_FILTERS_NOTE, WORKFLOW_FIELD,
} from "../../vocabulary";

const props = defineProps<{ state: ReportState; options: RunFilterOptions | null }>();
const emit = defineEmits<{
  workflow: [key: string];
  outcome: [status: string];
  search: [text: string];
  "clear-focus": [];
  "clear-grouped": [];
  clear: [];
}>();

const counts = computed(() => props.options?.by_status ?? {});
const workflows = computed(() => props.options?.workflows ?? []);
// Canceled runs are rare, so the choice appears only when there are some.
const outcomes = computed(() => OUTCOMES.filter(
  outcome => outcome.id !== "cancelled" || counts.value.cancelled > 0 || props.state.runStatus === "cancelled",
));
const total = computed(() => Object.values(counts.value).reduce((sum, count) => sum + count, 0));
const workflowName = computed(() =>
  workflows.value.find(option => option.key === props.state.workflowKey)?.name ?? props.state.workflowKey);
const focusLabel = computed(() => props.state.focusFrom
  ? focusChipLabel(props.state.focusFrom, props.state.focusTo, props.state.timezone, props.state.mode)
  : "");
const groupedLabel = computed(() => (props.state.boundaryRunId ? groupedChipLabel(workflowName.value) : ""));
const anyFilter = computed(() => Boolean(
  props.state.workflowKey || props.state.runStatus || props.state.search
  || props.state.focusFrom || props.state.boundaryRunId,
));
const countFor = (id: string) => (id === "" ? total.value : counts.value[id] ?? 0);
</script>

<template>
  <div
    class="page-filters"
    role="group"
    aria-labelledby="page-filters-heading"
  >
    <h2 id="page-filters-heading">
      {{ PAGE_FILTERS_HEADING }}
    </h2>
    <p class="page-filters-note">
      {{ PAGE_FILTERS_NOTE }}
    </p>

    <label class="page-filter-field">
      <span>{{ WORKFLOW_FIELD }}</span>
      <select
        :value="state.workflowKey"
        @change="emit('workflow', ($event.target as HTMLSelectElement).value)"
      >
        <option value="">{{ ALL_WORKFLOWS }}</option>
        <option
          v-for="option in workflows"
          :key="option.key"
          :value="option.key"
        >
          {{ `${option.name} (${option.run_count})` }}
        </option>
      </select>
    </label>

    <div class="page-filter-field">
      <span id="outcome-label">{{ OUTCOME_FIELD }}</span>
      <div
        class="chip-group"
        role="group"
        aria-labelledby="outcome-label"
      >
        <button
          v-for="outcome in outcomes"
          :key="outcome.id"
          class="chip-button"
          type="button"
          :aria-pressed="state.runStatus === outcome.id"
          @click="emit('outcome', outcome.id)"
        >
          {{ outcome.label }}<small>{{ countFor(outcome.id) }}</small>
        </button>
      </div>
    </div>

    <label class="search">
      <Search
        :size="16"
        aria-hidden="true"
      />
      <span class="sr-only">Find a workflow run</span>
      <input
        type="search"
        placeholder="Find a workflow run"
        autocomplete="off"
        :value="state.search"
        @input="emit('search', ($event.target as HTMLInputElement).value)"
      >
    </label>

    <ul
      class="chips page-chips"
      aria-label="Active filters"
    >
      <li v-if="focusLabel">
        <button
          type="button"
          :title="focusLabel"
          @click="emit('clear-focus')"
        >
          <span class="chip-label">{{ focusLabel }}</span><X
            :size="14"
            aria-hidden="true"
          />
          <span class="sr-only">Remove filter: {{ focusLabel }}</span>
        </button>
      </li>
      <li v-if="groupedLabel">
        <button
          type="button"
          :title="groupedLabel"
          @click="emit('clear-grouped')"
        >
          <span class="chip-label">{{ groupedLabel }}</span><X
            :size="14"
            aria-hidden="true"
          />
          <span class="sr-only">Remove filter: {{ groupedLabel }}</span>
        </button>
      </li>
      <li v-if="anyFilter">
        <button
          class="link-button"
          type="button"
          @click="emit('clear')"
        >
          {{ CLEAR_FILTERS }}
        </button>
      </li>
      <li
        v-else
        class="none"
      >
        {{ NO_ACTIVE_FILTERS }}
      </li>
    </ul>
  </div>
</template>
