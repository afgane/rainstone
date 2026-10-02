<script setup lang="ts">
import { computed } from "vue";
import type { OverviewDetail } from "../../api";
import type { OverviewScope } from "../../overviewDetail";
import {
  COUNTED_HERE, excludedContributors, formatCost, needsCostData, PERIOD_OVERLAP_NOTE, pluralize,
  runStatusLabel, SPAN_NOTE, sharedJobsNote, topContributors,
} from "../../vocabulary";
import ScopedJobRow from "./ScopedJobRow.vue";

/**
 * What lies behind an Overview figure: one chart block's runs or jobs, or the
 * whole period's top workflow runs and tools. Every amount and count above the
 * list describes the whole scope, never the page of rows below it.
 */
const props = defineProps<{
  detail: OverviewDetail;
  descriptor: OverviewScope;
  /** "this month", or "the selected dates", for a period; unused for an interval. */
  periodLabel: string;
  /** "this day", "this hour" or "this week", for an interval. */
  noun: string;
  paging: boolean;
}>();
const emit = defineEmits<{
  open: [kind: "runs" | "tool-runs" | "tool", id: string];
  page: [offset: number];
  tab: [category: "runs" | "tools"];
  all: [category: "runs" | "tools"];
}>();

const period = computed(() => props.descriptor.scope === "period");
const recordedSoFar = computed(() => props.detail.incomplete_job_count > 0 && props.detail.amount !== null);
const scopeWords = computed(() => {
  const when = period.value ? `in ${props.periodLabel}` : `during ${props.noun}`;
  const what = props.detail.kind === "runs" ? "Jobs inside workflow runs"
    : props.detail.kind === "tools" ? "All jobs" : "Jobs outside workflows";
  return `${what} ${when}${recordedSoFar.value ? ", recorded so far" : ""}`
    + `${props.detail.provisional ? ", still running" : ""}`;
});
const ranking = computed(() => props.detail.ranking);
const rankedNoun = computed(() => (props.detail.kind === "tools" ? "tool" : "run"));
/** Why no ranking is shown, rather than a ranking that cannot be trusted. */
const unranked = computed(() => {
  if (!props.detail.job_count) {
    return props.detail.kind === "runs"
      ? `No job matching these filters ran inside a workflow run in ${props.periodLabel}.`
      : `No job matches these filters in ${props.periodLabel}.`;
  }
  if (ranking.value?.excluded_count && !ranking.value.zero_count) {
    return `None has complete cost data yet, so none can be ranked by cost.`;
  }
  return `None recorded a compute cost above $0, so there is nothing to rank.`;
});
const first = computed(() => (props.detail.total ? props.detail.offset + 1 : 0));
const last = computed(() => Math.min(props.detail.total, props.detail.offset + props.detail.items.length));
const pageNoun = computed(() => (props.detail.kind === "runs" ? "run" : "job"));
const TABS = [{ category: "runs", label: "Workflow runs" }, { category: "tools", label: "Tools" }] as const;

function moveTab(event: KeyboardEvent) {
  if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
  emit("tab", props.detail.kind === "tools" ? "runs" : "tools");
}
</script>

<template>
  <div v-if="period" class="tabs drawer-tabs" role="tablist" aria-label="What to explore">
    <button
      v-for="tab in TABS" :id="`overview-tab-${tab.category}`" :key="tab.category"
      role="tab" type="button" aria-controls="overview-panel" :data-tab="tab.category"
      :aria-selected="detail.kind === tab.category" :tabindex="detail.kind === tab.category ? 0 : -1"
      @click="detail.kind !== tab.category && emit('tab', tab.category)" @keydown="moveTab"
    >{{ tab.label }}</button>
  </div>

  <div
    id="overview-panel" :role="period ? 'tabpanel' : undefined"
    :aria-labelledby="period ? `overview-tab-${detail.kind}` : undefined"
  >
    <p class="dialog-amount">
      <strong>{{ detail.job_count ? formatCost(detail.amount) : "No jobs" }}</strong>
      <span v-if="detail.job_count">{{ scopeWords }}</span>
    </p>
    <dl v-if="detail.job_count" class="drawer-facts">
      <template v-if="detail.run_count !== null">
        <dt>Workflow runs</dt><dd>{{ detail.run_count }}</dd>
      </template>
      <template v-if="detail.tool_count !== null">
        <dt>Tools</dt><dd>{{ detail.tool_count }}</dd>
      </template>
      <dt>Jobs</dt><dd>{{ detail.job_count }}</dd>
    </dl>
    <p v-if="detail.incomplete_job_count" class="dialog-meta">
      {{ needsCostData(detail.incomplete_job_count, "job") }}, so this amount is a subtotal.
    </p>
    <p v-if="detail.kind === 'runs' && detail.shared_job_count" class="dialog-meta">
      {{ sharedJobsNote(detail.shared_job_count) }}
    </p>

    <section v-if="period" class="job-section" aria-labelledby="overview-list-heading">
      <h3 id="overview-list-heading">
        {{ detail.items.length
          ? topContributors(detail.items.length, detail.kind === "tools" ? "tool" : "workflow run")
          : "Top contributors" }}
      </h3>
      <p v-if="!detail.items.length" class="dialog-meta">{{ unranked }}</p>
      <template v-else>
        <p class="dialog-meta">
          Ranked by cost in {{ periodLabel }}, among those with complete cost data.
          <template v-if="ranking?.excluded_count">{{ excludedContributors(ranking.excluded_count, rankedNoun) }}</template>
        </p>
        <p class="rank-head" aria-hidden="true">
          <span>{{ detail.kind === "tools" ? "Tool" : "Workflow run" }}</span>
          <span>{{ detail.kind === "tools" ? "Cost" : COUNTED_HERE }}</span>
        </p>
        <ul class="rank-list" role="list">
          <li v-for="item in detail.items" :key="'key' in item ? item.key : item.id">
            <button
              v-if="detail.kind === 'tools' && 'key' in item" type="button" class="rank-row" data-detail-trigger
              :data-tool-key="item.key"
              :aria-label="`${item.name}, ${pluralize(item.job_count, 'job')}, ${formatCost(item.amount)}`"
              @click="emit('open', 'tool', item.key)"
            >
              <span><strong>{{ item.name }}</strong><small>{{ pluralize(item.job_count, "job") }}</small></span>
              <span class="rank-amount">{{ formatCost(item.amount) }}</span>
            </button>
            <button
              v-else-if="'workflow_name' in item" type="button" class="rank-row" data-detail-trigger
              :data-run-id="item.id"
              :aria-label="`${item.workflow_name}, ${runStatusLabel(item.run_status ?? '')}, ${COUNTED_HERE.toLowerCase()} ${formatCost(item.amount)}`"
              @click="emit('open', 'runs', item.id)"
            >
              <span>
                <strong>{{ item.workflow_name }}</strong>
                <small>{{ item.run_status ? runStatusLabel(item.run_status) : "Status not recorded" }}</small>
              </span>
              <span class="rank-amount">{{ formatCost(item.amount) }}</span>
            </button>
          </li>
        </ul>
      </template>
      <p class="dialog-meta">{{ PERIOD_OVERLAP_NOTE }}</p>
      <button type="button" class="secondary show-jobs" @click="emit('all', detail.kind === 'tools' ? 'tools' : 'runs')">
        {{ detail.kind === "tools" ? "See all tools" : "See all workflow runs" }}
      </button>
    </section>

    <section v-else class="job-section" aria-labelledby="overview-list-heading">
      <h3 id="overview-list-heading">
        {{ detail.kind === "runs" ? "Workflow runs, highest cost first" : "Jobs, highest cost first" }}
      </h3>
      <p v-if="!detail.job_count" class="dialog-meta">
        Nothing matching these filters had compute during {{ noun }}.
      </p>
      <template v-else-if="detail.kind === 'runs'">
        <p class="dialog-meta">Each run shows only the cost the chart counts under it during {{ noun }}.</p>
        <p class="rank-head" aria-hidden="true"><span>Workflow run</span><span>{{ COUNTED_HERE }}</span></p>
        <ul class="rank-list" role="list" :class="{ refetching: paging }" :aria-busy="paging">
          <li v-for="run in detail.items" :key="run.id">
            <button
              type="button" class="rank-row" data-detail-trigger :data-run-id="run.id"
              :aria-label="`${run.workflow_name}, ${runStatusLabel(run.run_status ?? '')}, ${COUNTED_HERE.toLowerCase()} ${formatCost(run.amount)}`"
              @click="emit('open', 'runs', run.id)"
            >
              <span>
                <strong>{{ run.workflow_name }}</strong>
                <small>
                  {{ run.run_status ? runStatusLabel(run.run_status) : "Status not recorded" }}<template
                    v-if="run.incomplete_job_count"
                  > · {{ needsCostData(run.incomplete_job_count, "job") }}</template>
                </small>
              </span>
              <span class="rank-amount">{{ formatCost(run.amount) }}</span>
            </button>
          </li>
        </ul>
      </template>
      <template v-else-if="detail.kind === 'individual'">
        <p class="dialog-meta">{{ SPAN_NOTE }}</p>
        <ul class="job-list" role="list" data-with-cost="true" :class="{ refetching: paging }" :aria-busy="paging">
          <ScopedJobRow
            v-for="job in detail.items" :key="job.id" :job="job" :scope="`Cost during ${noun}`"
            @open="emit('open', 'tool-runs', $event)"
          />
        </ul>
      </template>
      <nav
        v-if="detail.total > detail.limit" class="pagination drawer-pages"
        :aria-label="`Pages of these ${pageNoun}s`"
      >
        <button
          type="button" :disabled="detail.offset === 0 || paging"
          @click="emit('page', Math.max(0, detail.offset - detail.limit))"
        >Previous</button>
        <span>{{ first }}–{{ last }} of {{ pluralize(detail.total, pageNoun) }}</span>
        <button
          type="button" :disabled="detail.offset + detail.limit >= detail.total || paging"
          @click="emit('page', detail.offset + detail.limit)"
        >Next</button>
      </nav>
    </section>
  </div>
</template>
