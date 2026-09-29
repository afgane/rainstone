<script setup lang="ts">
import { ArrowLeft, RefreshCw, X } from "@lucide/vue";
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import {
  capacityLabel, costExplanation, durationText, formatCost, formatDateTime, jobStateLabel,
  needsCostData, pluralize, qualityLabel, runStatusLabel, WORKFLOW_JOBS,
} from "../vocabulary";

const props = defineProps<{
  kind: "runs" | "tool-runs" | null;
  detail: Record<string, unknown> | null;
  loading: boolean;
  periodLabel: string;
  timezone: string;
  /** Names where the back button leads; empty when the drawer was opened from outside it. */
  backLabel: string;
}>();
const emit = defineEmits<{
  // Escape and the close button; focus goes back to whatever opened the drawer.
  close: [];
  // A press outside dismisses the drawer, and focus stays where the press put it.
  dismiss: [];
  open: [kind: "runs" | "tool-runs", id: string];
  back: [];
}>();

const drawer = ref<HTMLElement | null>(null);
const title = ref<HTMLElement | null>(null);
const shown = computed(() => Boolean(props.detail) || props.loading);

// Focus moves to the title once its content has arrived, including when the
// drawer swaps from one run to another.
watch(() => props.detail, async detail => {
  if (!detail) return;
  await nextTick();
  title.value?.focus({ preventScroll: true });
});

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
const steps = computed(() => list("steps"));
const children = computed(() => list("children"));
const resources = computed(() => list("resources"));
// Galaxy's own record of an execution a provider also observed is evidence
// about that attempt, not another attempt.
const attempts = computed(() => list("attempts").filter(attempt => attempt.role !== "observation"));
</script>

<template>
  <div
    ref="drawer"
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
        {{ isRun ? "Workflow run" : kind === "tool-runs" ? "Job" : "" }}
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
    <template v-else-if="detail">
      <template v-if="isRun">
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

        <h3>Steps</h3>
        <div
          v-if="!steps.length"
          class="empty"
        >
          No jobs are recorded for this run yet.
        </div>
        <ul
          v-else
          class="step-list"
        >
          <li
            v-for="step in steps"
            :key="String(step.step_key)"
          >
            <template v-if="step.job">
              <button
                class="link-button"
                @click="emit('open', 'tool-runs', String((step.job as Record<string, unknown>).id))"
              >
                {{ (step.job as Record<string, unknown>).tool_name }}
              </button>
              <span>{{ jobStateLabel(String((step.job as Record<string, unknown>).state)) }}</span>
              <span>{{ formatCost((step.job as Record<string, unknown>).amount as string) }}</span>
              <small>{{ capacityLabel((step.job as Record<string, unknown>).capacities as string[]) }}</small>
            </template>
            <small v-else>Step {{ step.step_key }} has no authorized matching job.</small>
          </li>
        </ul>

        <template v-if="children.length">
          <h3>Child workflows</h3>
          <ul class="step-list">
            <li
              v-for="child in children"
              :key="String(child.id)"
            >
              <button
                class="link-button"
                @click="emit('open', 'runs', String(child.id))"
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

      <template v-else>
        <h2
          id="detail-title"
          ref="title"
          tabindex="-1"
        >
          {{ detail.tool_name }}
        </h2>
        <p class="dialog-amount">
          <strong>{{ formatCost(text("full_job_amount")) }}</strong>
          <span>Cost of this job</span>
        </p>
        <p class="dialog-meta">
          {{ jobStateLabel(String(detail.state)) }} ·
          submitted {{ formatDateTime(String(detail.created_at), timezone) }} ·
          {{ qualityLabel(String(detail.quality)) }}
        </p>
        <p
          v-if="text('interval_amount') !== text('full_job_amount')"
          class="dialog-meta"
        >
          {{ formatCost(text("interval_amount")) }} of it falls inside {{ periodLabel }}.
        </p>
        <p class="explanation">
          {{ costExplanation({
            quality: String(detail.quality),
            amount: text("full_job_amount"),
            reason: String(detail.reason || ""),
            capacities: detail.capacities as string[],
          }) }}
        </p>

        <h3>Where it ran</h3>
        <p
          v-if="!resources.length"
          class="dialog-meta"
        >
          No evidence of where this ran was collected.
        </p>
        <ul
          v-else
          class="step-list"
        >
          <li
            v-for="resource in resources"
            :key="String(resource.lifetime_id)"
          >
            <span>{{ resource.machine_type || "Your Galaxy server" }}</span>
            <span>{{ capacityLabel([String(resource.capacity_relationship)]) }}</span>
            <span>{{ formatCost(resource.amount as string) }}</span>
            <small v-if="Number(resource.shared_attempt_count) > 1">
              Charged once for {{ resource.shared_attempt_count }} attempts that reused it
            </small>
          </li>
        </ul>

        <h3>Attempts</h3>
        <ul class="step-list">
          <li
            v-for="attempt in attempts"
            :key="String(attempt.id)"
          >
            <span>
              {{ jobStateLabel(String(attempt.outcome)) }}{{ attempt.role === "repeat" ? " · repeat attempt" : "" }}
            </span>
            <span v-if="attempt.tool_started_at">
              {{ formatDateTime(String(attempt.tool_started_at), timezone) }}
            </span>
            <span v-if="attempt.amount">{{ formatCost(attempt.amount as string) }}</span>
            <small v-else-if="attempts.length > 1">Shares the resource charge above</small>
          </li>
        </ul>

        <details class="inline-details">
          <summary>Technical details</summary>
          <p class="mono">
            {{ detail.tool_id }}
          </p>
          <p class="mono">
            Job {{ detail.source_id }} · snapshot {{ detail.revision_id }}
          </p>
          <p>{{ detail.reason }}</p>
        </details>
      </template>
    </template>
  </div>
</template>
