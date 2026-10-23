<script setup lang="ts">
import { computed, nextTick, ref, watch } from "vue";
import { ApiError, put, type SpendGuard } from "../api";
import { minimumSpendLimit, triggersImmediately } from "../spendGuard";
import { BATCH_LIMIT_SCOPE, formatCost, formatDate, formatDateTime } from "../vocabulary";

const props = defineProps<{ guard: SpendGuard | null; error: string; timezone: string }>();
const emit = defineEmits<{ saved: [guard: SpendGuard]; reload: [] }>();
const amount = ref("");
const stopJobs = ref(false);
const dirty = ref(false);
const saving = ref(false);
const message = ref("");
const failure = ref("");
const conflict = ref(false);
const revision = ref(0);
const sliderMaximum = ref(100);
const resultMessage = ref<HTMLElement | null>(null);
const minimum = computed(() => minimumSpendLimit(props.guard?.snapshot.amount ?? null));
const spent = computed(() => Number(props.guard?.snapshot.amount ?? 0));
const validAmount = computed(() => /^\d+(\.\d{1,2})?$/.test(amount.value) && Number.isFinite(Number(amount.value)));
const sliderValue = computed(() => Math.max(Number(minimum.value), validAmount.value ? Number(amount.value) : Number(minimum.value)));
const spentPercent = computed(() => Math.min(100, spent.value / sliderMaximum.value * 100));
const selectedPercent = computed(() => Math.min(100, sliderValue.value / sliderMaximum.value * 100));
const remaining = computed(() => validAmount.value && props.guard?.snapshot.amount !== null
  ? Math.max(0, Number(amount.value) - spent.value).toFixed(2) : null);
const immediate = computed(() => validAmount.value && props.guard
  ? triggersImmediately(props.guard.snapshot.amount, props.guard.margin, amount.value) : false);
const outstanding = computed(() => props.guard?.cancellations.filter(item => !item.verified_at) ?? []);
const completed = computed(() => props.guard?.cancellations.filter(item => item.verified_at) ?? []);
function expandSlider() {
  // Keep the scale steady while dragging; typed amounts can extend it.
  sliderMaximum.value = Math.max(sliderMaximum.value, Math.ceil(Math.max(spent.value * 2, Number(amount.value) * 1.25 || 0, 100) / 10) * 10);
}
function load(guard: SpendGuard) {
  revision.value = guard.revision;
  amount.value = guard.limit === null ? "" : Number(guard.limit).toFixed(2);
  stopJobs.value = guard.stop_jobs;
  expandSlider();
}
watch(() => props.guard, guard => {
  if (!guard) return;
  expandSlider();
  if (!dirty.value) load(guard);
}, { immediate: true });
function slide(event: Event) {
  amount.value = Math.max(Number(minimum.value), Number((event.target as HTMLInputElement).value)).toFixed(2);
  (event.target as HTMLInputElement).value = amount.value;
  dirty.value = true;
}
async function save(disable = false) {
  if (!props.guard || saving.value) return;
  failure.value = ""; message.value = "";
  if (!disable && (!validAmount.value || Number(amount.value) <= 0)) {
    failure.value = "Enter a positive USD amount with at most two decimal places.";
    return;
  }
  if (!disable && (props.guard.snapshot.amount === null || triggersImmediately(props.guard.snapshot.amount, "0", amount.value))) {
    failure.value = props.guard.snapshot.amount === null ? "Spending is not available yet. Try again when cost data is available."
      : `Enter a total limit of at least $${minimum.value}, above estimated spending.`;
    return;
  }
  saving.value = true;
  try {
    const saved = await put<SpendGuard>("/spend-guard", { limit: disable ? null : amount.value, stop_jobs: !disable && stopJobs.value, revision: revision.value });
    dirty.value = false;
    conflict.value = false;
    load(saved);
    emit("saved", saved);
    message.value = saved.limit === null ? "Batch spend limit turned off. Waiting jobs may now run on Batch."
      : saved.triggered_at ? "Limit saved. New Batch jobs are paused."
        : "Batch spend limit saved. Waiting jobs may now run on Batch.";
    await nextTick(); resultMessage.value?.focus();
  } catch (error) {
    failure.value = error instanceof Error ? error.message : "Unable to save the Batch limit";
    conflict.value = error instanceof ApiError && error.status === 409;
  } finally { saving.value = false; }
}
function reload() {
  dirty.value = false; conflict.value = false; failure.value = "";
  emit("reload");
}
</script>

<template>
  <div class="spend-limit-page">
    <p class="limit-scope">
      Set a total ceiling for Batch compute spending, including what you’ve already spent.
      New Batch jobs stop being submitted as spending approaches it.
    </p>
    <details class="limit-help">
      <summary>More</summary>
      <p>{{ BATCH_LIMIT_SCOPE }} Jobs that fit on your Galaxy server still run.</p>
      <p>The ceiling covers recorded Batch history, not a monthly allowance. Saving a limit does not reset spending.</p>
    </details>
    <div
      v-if="error"
      class="error"
      role="alert"
    >
      {{ error }} <button
        type="button"
        @click="reload"
      >
        Try again
      </button>
    </div>
    <p
      v-if="!guard && !error"
      role="status"
    >
      Loading Batch spend…
    </p>
    <template v-if="guard">
      <form
        class="panel limit-form"
        @submit.prevent="save()"
        @input="dirty = true"
      >
        <div class="limit-form-heading">
          <h2>{{ guard.limit === null ? 'Set your ceiling' : 'Your spending ceiling' }}</h2>
          <span class="limit-state">{{ guard.source_changed ? 'Needs attention' : guard.limit === null ? 'No limit set' : guard.triggered_at ? 'New Batch jobs paused' : 'Limit active' }}</span>
        </div>
        <div v-if="guard.triggered_at && !guard.source_changed" class="limit-pause-explanation">
          <p v-if="guard.trigger?.amount !== null && guard.trigger?.amount !== undefined && guard.trigger?.margin">
            Batch paused at {{ formatCost(guard.trigger.amount) }} recorded,
            with {{ formatCost(guard.trigger.margin) }} reserved for observation and shutdown delays.
          </p>
          <p v-else>Batch paused before the ceiling to allow for observation and shutdown delays.</p>
          <p>Recorded spending can settle below the ceiling after jobs stop.
            Raise the limit or turn it off to resume sending jobs to Batch.</p>
        </div>
        <div class="limit-amount-row">
          <label for="batch-limit-amount">Total limit <span>(USD)</span></label>
          <div class="limit-currency-input">
            <span aria-hidden="true">$</span>
            <input
              id="batch-limit-amount"
              v-model="amount"
              type="text"
              inputmode="decimal"
              autocomplete="off"
              placeholder="Enter amount"
              required
              aria-describedby="limit-amount-help"
              :disabled="saving"
              @input="expandSlider"
            >
          </div>
        </div>
        <div
          class="limit-slider"
          :style="{ '--spent-position': `${spentPercent}%`, '--selected-position': `${selectedPercent}%` }"
        >
          <label
            class="sr-only"
            for="batch-limit-slider"
          >Adjust total limit (USD)</label>
          <input
            id="batch-limit-slider"
            type="range"
            min="0"
            :max="sliderMaximum"
            step="0.01"
            :value="sliderValue"
            :disabled="saving || guard.snapshot.amount === null"
            :aria-valuetext="`${formatCost(String(sliderValue))} total limit`"
            aria-describedby="limit-amount-help"
            @input="slide"
          >
          <span
            v-if="guard.snapshot.amount !== null"
            class="limit-spent-marker"
            aria-hidden="true"
          />
        </div>
        <div
          class="limit-slider-scale"
          aria-hidden="true"
        >
          <span>$0</span><span>{{ formatCost(String(sliderMaximum)) }}</span>
        </div>
        <p
          id="limit-amount-help"
          class="limit-budget-readout"
        >
          <span>Recorded spend <strong>{{ formatCost(guard.snapshot.amount) }}</strong></span>
          <span v-if="remaining !== null">{{ guard.triggered_at && !guard.source_changed ? 'Below ceiling' : 'Remaining' }} <strong>{{ formatCost(remaining) }}</strong></span>
        </p>
        <div class="limit-job-choice">
          <input
            id="batch-stop-jobs"
            v-model="stopJobs"
            type="checkbox"
            role="switch"
            :disabled="saving"
            aria-describedby="limit-job-effect"
          >
          <label for="batch-stop-jobs">Stop running jobs when the limit is reached</label>
          <p id="limit-job-effect">
            {{ stopJobs ? 'Unfinished work is lost; affected workflow runs remain failed.' : 'Running jobs can finish and continue adding costs.' }}
          </p>
        </div>
        <div class="limit-actions">
          <button
            type="submit"
            class="primary"
            :disabled="saving || guard.source_changed || guard.snapshot.amount === null"
          >
            {{ saving ? 'Saving…' : guard.limit === null ? 'Save limit' : 'Update limit' }}
          </button>
          <p
            class="limit-inline-note"
            :class="{ 'is-hidden': !immediate }"
            :aria-hidden="!immediate"
          >
            This amount is close enough to current spending that new Batch jobs will pause immediately.
          </p>
          <button
            v-if="guard.limit !== null"
            type="button"
            class="secondary"
            :disabled="saving"
            @click="save(true)"
          >
            Turn off limit
          </button>
        </div>
      </form>
      <p
        v-if="failure"
        role="alert"
        class="error"
      >
        {{ failure }} <button
          v-if="conflict"
          type="button"
          @click="reload"
        >
          Reload saved limit
        </button>
      </p>
      <p
        v-if="message"
        ref="resultMessage"
        role="status"
        tabindex="-1"
        class="limit-result"
      >
        {{ message }}
      </p>
      <div class="limit-notes">
        <p v-if="guard.snapshot.incomplete_jobs || guard.snapshot.gaps || guard.snapshot.unpriced_running_resources || guard.snapshot.amount === null">
          Some costs are missing. Actual spending may be higher.
        </p>
        <p>The limit uses estimated spending and may be exceeded.</p>
        <p
          v-if="guard.stale"
          class="limit-condition"
        >
          Cost data is out of date, so your spend limit may not be enforced.
        </p>
        <p
          v-if="guard.source_changed"
          class="error"
        >
          The enrolled Galaxy source changed. This limit does not apply to the new source. Turn off the old limit before setting a new one.
        </p>
        <p
          v-if="guard.cancellation_error"
          class="error"
        >
          {{ guard.cancellation_error }}. Rainstone will retry.
        </p>
        <p
          v-if="outstanding.length"
          class="limit-condition"
        >
          {{ outstanding.length }} {{ outstanding.length === 1 ? 'stop request is' : 'stop requests are' }} still being checked. Spending may continue until their Batch VMs are gone.
        </p>
        <p
          v-for="notice in guard.notifications.filter(item => item.error)"
          :key="notice.condition"
          class="limit-condition"
        >
          Galaxy notification could not be updated: {{ notice.error }}. Rainstone will retry.
        </p>
        <details class="limit-details">
          <summary>Spending details</summary>
          <p>{{ guard.snapshot.coverage_start ? `Batch compute since ${formatDate(guard.snapshot.coverage_start, timezone)}` : 'No Batch history recorded yet' }}. Earlier costs that Rainstone could not reconstruct are left out.</p>
          <p>Calculated: {{ guard.snapshot.observed_at ? formatDateTime(guard.snapshot.observed_at, timezone) : 'Not available' }}.</p>
          <p v-if="guard.snapshot.incomplete_jobs">
            {{ guard.snapshot.incomplete_jobs }} {{ guard.snapshot.incomplete_jobs === 1 ? 'job needs' : 'jobs need' }} cost data. The recorded amount leaves out costs that are not available.
          </p>
          <p v-if="guard.snapshot.gaps">
            {{ guard.snapshot.gaps }} gaps in Batch observations may leave costs out.
          </p>
          <p v-if="guard.snapshot.unpriced_running_resources">
            Some running Batch compute cannot be priced.
          </p>
          <p>Rainstone checks the latest estimate when you save. New Batch jobs pause before the ceiling to allow for observation and shutdown delays. This margin grows when Batch is spending faster or cost data is older.</p>
          <p>Turning off the limit allows waiting jobs to run on Batch. Stop requests already sent cannot be undone, and stopped jobs will not restart.</p>
          <div
            v-if="guard.triggered_at && guard.stop_jobs || guard.cancellations.length"
            class="limit-stops"
          >
            <h3>Batch stop requests</h3>
            <p
              v-if="guard.cancellation_error"
              class="error"
            >
              {{ guard.cancellation_error }}. Rainstone will retry.
            </p>
            <p v-if="!guard.cancellations.length">
              {{ guard.cancellation_checked_at && guard.cancellation_checked_at >= (guard.triggered_at || '') ? 'No outstanding Batch jobs were found.' : 'Checking for outstanding Batch jobs…' }}
            </p>
            <p v-if="outstanding.length">
              {{ outstanding.length }} {{ outstanding.length === 1 ? 'stop request is' : 'stop requests are' }} still being checked. Spending may continue until their Batch VMs are gone.
            </p>
            <ul v-if="outstanding.length">
              <li
                v-for="item in outstanding"
                :key="item.job_id"
              >
                {{ item.error || 'Stop requested; checking Batch VM cleanup.' }}
              </li>
            </ul>
            <p v-if="completed.length">
              Batch VM cleanup verified for {{ completed.length }} {{ completed.length === 1 ? 'stop request' : 'stop requests' }}.
            </p>
            <p v-if="completed.some(item => !item.cost_reconciled)">
              Final cost evidence is still being checked.
            </p>
            <p>Stopped jobs are not restarted. Workflow runs containing them stay failed.</p>
          </div>
        </details>
      </div>
    </template>
  </div>
</template>
