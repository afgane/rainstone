<script setup lang="ts">
import { ArrowLeft, RefreshCw, X } from "@lucide/vue";
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import type { DrawerKind, InvocationDetail, JobDetail, OverviewDetail, ToolDetail, WindowDetail } from "../api";
import type { OverviewScope } from "../overviewDetail";
import { byAttribute } from "../dom";
import {
  durationText, formatCost, formatDateTime, JOBS_HEADING, jobStateKind, jobStateLabel, needsCostData,
  NO_RUN_JOBS, pluralize, runStatusLabel, unavailableSteps, WORKFLOW_JOBS,
} from "../vocabulary";
import JobDetails from "./drawer/JobDetails.vue";
import JobStateIcon from "./drawer/JobStateIcon.vue";
import JobWindowDetails from "./drawer/JobWindowDetails.vue";
import OverviewDetails from "./drawer/OverviewDetails.vue";
import OverviewGuide from "./drawer/OverviewGuide.vue";
import RunCostBreakdown from "./drawer/RunCostBreakdown.vue";
import RuntimeJobList from "./drawer/RuntimeJobList.vue";
import ToolDetails from "./drawer/ToolDetails.vue";

const props = defineProps<{
  kind: DrawerKind | null;
  detail: Record<string, unknown> | null;
  loading: boolean;
  periodLabel: string;
  timezone: string;
  /** Names where the back button leads; empty when the drawer was opened from outside it. */
  backLabel: string;
  /** The part of a run's cost that is open, and the member of a pooled part inside it. */
  part?: string;
  member?: string;
  /** Where a run was left, so returning to it puts the reader back. */
  restore?: { scrollTop: number; focusId: string } | null;
  /** Why the details could not be loaded; the drawer then offers to try again. */
  error?: string;
  /** An interval or Overview drawer's title, such as "Sep 28", and how its sentences name it. */
  windowTitle?: string;
  windowNoun?: string;
  /** True while another page of an interval's jobs is being fetched. */
  paging?: boolean;
  /** What an Overview drawer explains; null for every other kind. */
  overview?: OverviewScope | null;
  /** True when a run was opened from an interval, so its share of that interval is named. */
  intervalShare?: boolean;
  canViewServer?: boolean;
}>();
const emit = defineEmits<{
  // Escape and the close button; focus goes back to whatever opened the drawer.
  close: [];
  // A press outside dismisses the drawer, and focus stays where the press put it.
  dismiss: [];
  open: [kind: "runs" | "tool-runs" | "tool", id: string, scrollTop: number];
  // A tool's jobs, listed on the page itself under that tool's filter.
  "show-jobs": [key: string];
  page: [offset: number, scrollTop: number];
  back: [];
  select: [part: string, member: string];
  restored: [];
  retry: [];
  // An Overview period drawer's other tab, and the page that lists all of its kind.
  tab: [category: "runs" | "tools"];
  all: [category: "runs" | "tools"];
}>();

const drawer = ref<HTMLElement | null>(null);
const title = ref<HTMLElement | null>(null);
const shown = computed(() => Boolean(props.detail) || props.loading || Boolean(props.error));

// Focus moves to the title once its content has arrived, including when the
// drawer swaps from one run to another.
watch(() => props.detail, async detail => {
  if (!detail) return;
  await nextTick();
  const back = props.restore;
  if (back && drawer.value) {
    // Returning to a run puts the reader back on the row that opened the other one.
    drawer.value.scrollTop = back.scrollTop;
    const row = drawer.value.querySelector<HTMLElement>(["data-job-id", "data-run-id", "data-tool-key", "data-tab"]
      .map(name => byAttribute(name, back.focusId)).join(", "));
    (row ?? title.value)?.focus({ preventScroll: true });
    emit("restored");
    return;
  }
  title.value?.focus({ preventScroll: true });
});

function openFrom(kind: "runs" | "tool-runs" | "tool", id: string) {
  emit("open", kind, id, drawer.value?.scrollTop ?? 0);
}

/**
 * A press anywhere outside the drawer dismisses it: the masthead, the sidebar
 * and the page background included. A press on another run's trigger is left
 * to that trigger's own click, which swaps the drawer to that run.
 */
function onPointerDown(event: PointerEvent) {
  if (!shown.value) return;
  const target = event.target as Element | null;
  if (!target || drawer.value?.contains(target) || target.closest("[data-detail-trigger]")) return;
  emit("dismiss");
}
function onKeyDown(event: KeyboardEvent) {
  if (event.key === "Escape" && shown.value) emit("close");
}
onMounted(() => {
  document.addEventListener("pointerdown", onPointerDown);
  document.addEventListener("keydown", onKeyDown);
});
onBeforeUnmount(() => {
  document.removeEventListener("pointerdown", onPointerDown);
  document.removeEventListener("keydown", onKeyDown);
});

function list(key: string): Array<Record<string, unknown>> {
  const value = props.detail?.[key];
  return Array.isArray(value) ? (value as Array<Record<string, unknown>>) : [];
}
function text(key: string): string | null {
  const value = props.detail?.[key];
  return typeof value === "string" ? value : null;
}

const isRun = computed(() => props.kind === "runs");
const running = computed(() => props.detail?.run_status === "running");
// A run's headline is the whole run.
const runTotal = computed(() => text("run_total"));
const run = computed(() => (isRun.value ? props.detail as unknown as InvocationDetail : null));
const jobs = computed(() => run.value?.jobs ?? []);
const children = computed(() => list("children"));
const job = computed(() => (props.kind === "tool-runs" ? props.detail as unknown as JobDetail : null));
const tool = computed(() => (props.kind === "tool" ? props.detail as unknown as ToolDetail : null));
const interval = computed(() => (props.kind === "window" ? props.detail as unknown as WindowDetail : null));
// A response for another kind of Overview drawer is never shown under this one's title.
const aggregate = computed(() => {
  const value = props.kind === "overview" ? props.detail as unknown as OverviewDetail : null;
  return value && props.overview && value.kind === props.overview.category ? value : null;
});
const EYEBROWS: Record<DrawerKind, string> = {
  runs: "Workflow run", "tool-runs": "Job", tool: "Tool", window: "Jobs in this interval", overview: "", guide: "Quick guide",
};
const eyebrow = computed(() => {
  if (props.kind !== "overview") return props.kind ? EYEBROWS[props.kind] : "";
  return props.overview?.scope === "period" ? "Explore this period" : "What ran";
});
</script>

<template>
  <div
    ref="drawer"
    id="detail-drawer"
    class="drawer"
    role="dialog"
    aria-modal="false"
    :aria-labelledby="detail ? 'detail-title' : undefined"
    :aria-label="detail ? undefined : 'Details'"
    :data-open="shown"
    :inert="shown ? undefined : true"
    :aria-hidden="!shown"
  >
    <div class="drawer-head">
      <p class="eyebrow">
        {{ eyebrow }}
      </p>
      <button
        class="icon-close"
        type="button"
        aria-label="Close details"
        @click="emit('close')"
      >
        <X
          :size="20"
          aria-hidden="true"
        />
      </button>
    </div>
    <button v-if="backLabel" class="drawer-back" type="button" @click="emit('back')">
      <ArrowLeft :size="16" aria-hidden="true" />{{ backLabel }}
    </button>
    <div
      v-if="loading"
      class="loading"
    >
      <RefreshCw class="spin" /> Loading details…
    </div>
    <div
      v-else-if="error && !detail"
      class="error"
      role="alert"
    >
      <p><strong>These details could not be loaded.</strong> {{ error }}</p>
      <button
        type="button"
        class="link-button"
        @click="emit('retry')"
      >
        Try again
      </button>
    </div>
    <template v-else-if="detail">
      <template v-if="kind === 'guide'">
        <h2 id="detail-title" ref="title" tabindex="-1">How to read this page</h2>
        <OverviewGuide :can-view-server="Boolean(canViewServer)" />
      </template>
      <template v-else-if="isRun">
        <h2
          id="detail-title"
          ref="title"
          tabindex="-1"
        >
          {{ detail.workflow_name }}
        </h2>
        <p class="dialog-amount">
          <strong>{{ formatCost(runTotal) }}</strong>
          <span>
            {{ running ? "Cost so far" : "Run total" }}{{ detail.run_total_complete || running ? "" : " recorded so far" }}
          </span>
        </p>
        <dl class="drawer-facts">
          <dt>Status</dt><dd>{{ runStatusLabel(String(detail.run_status)) }}</dd>
          <dt>Started</dt><dd>{{ formatDateTime(String(detail.started_at), timezone) }}</dd>
          <dt>Duration</dt>
          <dd>{{ durationText(detail.duration_seconds as number | null, String(detail.run_status)) }}</dd>
          <dt>{{ WORKFLOW_JOBS }}</dt><dd>{{ detail.run_job_count }}</dd>
        </dl>
        <p v-if="intervalShare" class="dialog-meta">
          Inside {{ periodLabel }}: {{ formatCost(text("amount")) }} of this run's cost.
        </p>
        <p
          v-if="Number(detail.run_unpriced_job_count)"
          class="dialog-meta"
        >
          {{ needsCostData(Number(detail.run_unpriced_job_count)) }}, so this total is a subtotal.
        </p>
        <p
          v-if="Number(detail.reused_job_count)"
          class="dialog-meta"
        >
          {{ pluralize(Number(detail.reused_job_count), "step") }} reused earlier outputs and
          added no new compute.
        </p>

        <div
          v-if="!jobs.length"
          class="empty"
        >
          {{ NO_RUN_JOBS }}
        </div>
        <template v-else-if="run">
          <RunCostBreakdown
            :detail="run" :selected="part ?? ''" :member="member ?? ''" :running="running"
            @select="(key, inside) => emit('select', key, inside)"
            @open="id => openFrom('tool-runs', id)"
          />
          <section aria-labelledby="run-jobs-heading">
            <h3 id="run-jobs-heading">{{ JOBS_HEADING }}</h3>
            <RuntimeJobList
              :jobs="jobs"
              @open="id => openFrom('tool-runs', id)"
            />
            <p
              v-if="run.unavailable_step_count"
              class="dialog-meta"
            >
              {{ unavailableSteps(run.unavailable_step_count) }}
            </p>
          </section>
        </template>

        <template v-if="children.length">
          <h3>Child workflows</h3>
          <ul class="step-list">
            <li
              v-for="child in children"
              :key="String(child.id)"
            >
              <button
                class="link-button"
                :data-run-id="String(child.id)"
                @click="openFrom('runs', String(child.id))"
              >
                {{ child.workflow_name }}
              </button>
              <span>{{ pluralize(Number(child.run_job_count || child.job_count), "job") }}</span>
              <span>{{ formatCost(child.run_total as string) }}</span>
            </li>
          </ul>
          <p class="dialog-meta">
            Child runs are already counted once in the run total above.
          </p>
        </template>
      </template>

      <template v-else-if="job">
        <div class="job-title-row">
          <h2
            id="detail-title"
            ref="title"
            tabindex="-1"
          >
            {{ job.tool_name }}
          </h2>
          <span class="job-state-text" :data-kind="jobStateKind(job.state)">
            <JobStateIcon :state="job.state" />{{ jobStateLabel(job.state) }}
          </span>
        </div>
        <JobDetails :detail="job" :timezone="timezone" :period-label="periodLabel" />
      </template>

      <template v-else-if="tool">
        <h2 id="detail-title" ref="title" tabindex="-1">{{ tool.name }}</h2>
        <ToolDetails
          :detail="tool" :period-label="periodLabel"
          @open="id => openFrom('tool-runs', id)" @show-jobs="emit('show-jobs', $event)"
        />
      </template>

      <template v-else-if="interval">
        <h2 id="detail-title" ref="title" tabindex="-1">{{ windowTitle }}</h2>
        <JobWindowDetails
          :detail="interval" :noun="windowNoun ?? ''" :paging="Boolean(paging)"
          @open="id => openFrom('tool-runs', id)" @page="emit('page', $event, drawer?.scrollTop ?? 0)"
        />
      </template>

      <template v-else-if="aggregate && overview">
        <h2 id="detail-title" ref="title" tabindex="-1">{{ windowTitle }}</h2>
        <OverviewDetails
          :detail="aggregate" :descriptor="overview" :period-label="periodLabel" :noun="windowNoun ?? ''"
          :paging="Boolean(paging)"
          @open="openFrom" @page="emit('page', $event, drawer?.scrollTop ?? 0)"
          @tab="emit('tab', $event)" @all="emit('all', $event)"
        />
      </template>
    </template>
  </div>
</template>
