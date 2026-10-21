<script setup lang="ts">
import { computed, nextTick, ref, watch } from "vue";
import { ApiError, put, type SpendGuard } from "../api";
import { triggersImmediately } from "../spendGuard";
import {
  BATCH_FINISH_EFFECT, BATCH_LIMIT_BEST_EFFORT, BATCH_LIMIT_SCOPE, BATCH_STOP_EFFECT,
  formatCost, formatDate, formatDateTime,
} from "../vocabulary";

const props = defineProps<{ guard: SpendGuard | null; error: string; timezone: string }>();
const emit = defineEmits<{ saved: [guard: SpendGuard]; reload: [] }>();
const amount = ref("");
const choice = ref("");
const dirty = ref(false);
const saving = ref(false);
const message = ref("");
const failure = ref("");
const conflict = ref(false);
const revision = ref(0);
const confirmation = ref<{ limit: string | null; stop_jobs: boolean; revision: number } | null>(null);
const confirmationHeading = ref<HTMLElement | null>(null);
const resultMessage = ref<HTMLElement | null>(null);
watch(() => props.guard, guard => {
  if (!guard || dirty.value || confirmation.value) return;
  revision.value = guard.revision;
  amount.value = guard.limit === null ? "" : (guard.limit.includes(".") ? guard.limit.replace(/(\.\d{2})\d*$/, "$1") : `${guard.limit}.00`);
  choice.value = guard.limit === null ? "" : guard.stop_jobs ? "stop" : "finish";
}, { immediate: true });
const outstanding = computed(() => props.guard?.cancellations.filter(item => !item.verified_at) ?? []);
const completed = computed(() => props.guard?.cancellations.filter(item => item.verified_at) ?? []);
const immediate = computed(() => confirmation.value?.limit && props.guard
  ? triggersImmediately(props.guard.snapshot.amount, props.guard.margin, confirmation.value.limit) : false);

async function review(disable = false) {
  if (!props.guard) return;
  failure.value = ""; message.value = "";
  if (!disable && (!/^\d+(\.\d{1,2})?$/.test(amount.value) || BigInt(amount.value.replace(".", "")) <= 0n)) {
    failure.value = "Enter a positive USD amount with at most two decimal places.";
    return;
  }
  if (!disable && !choice.value) { failure.value = "Choose whether existing Batch jobs should finish or stop."; return; }
  confirmation.value = { limit: disable ? null : amount.value, stop_jobs: !disable && choice.value === "stop", revision: revision.value };
  await nextTick(); confirmationHeading.value?.focus();
}
async function save() {
  if (!confirmation.value || saving.value) return;
  saving.value = true; failure.value = "";
  try {
    const saved = await put<SpendGuard>("/spend-guard", confirmation.value);
    dirty.value = false;
    confirmation.value = null;
    conflict.value = false;
    emit("saved", saved);
    revision.value = saved.revision;
    amount.value = saved.limit === null ? "" : (saved.limit.includes(".") ? saved.limit.replace(/(\.\d{2})\d*$/, "$1") : `${saved.limit}.00`);
    choice.value = saved.limit === null ? "" : saved.stop_jobs ? "stop" : "finish";
    message.value = saved.limit === null ? "Batch spend limit turned off. Waiting jobs may now run on Batch."
      : saved.triggered_at ? "Limit saved. New Batch jobs are paused."
        : "Batch spend limit saved. Waiting jobs may now run on Batch.";
    await nextTick(); resultMessage.value?.focus();
  } catch (error) {
    failure.value = error instanceof Error ? error.message : "Unable to save the Batch limit";
    conflict.value = error instanceof ApiError && error.status === 409;
  } finally { saving.value = false; }
}
async function backToEdit() {
  confirmation.value = null;
  await nextTick(); document.getElementById("batch-limit-amount")?.focus();
}
function reload() {
  dirty.value = false; confirmation.value = null; conflict.value = false; failure.value = "";
  emit("reload");
}
</script>

<template>
  <div class="spend-limit-page">
    <p class="limit-scope">
      {{ BATCH_LIMIT_SCOPE }}
    </p>
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
      <section
        class="panel limit-status"
        aria-labelledby="limit-status-title"
      >
        <h2 id="limit-status-title">
          {{ guard.source_changed ? 'Batch limit needs attention' : guard.limit === null ? 'No Batch spend limit set' : guard.triggered_at ? 'New Batch jobs are paused' : 'Batch spend limit active' }}
        </h2>
        <p v-if="guard.triggered_at && !guard.source_changed">
          Jobs that fit on your Galaxy server still run. Raise the limit or turn it off to resume sending jobs to Batch.
        </p>
        <dl class="limit-facts">
          <div><dt>Estimated Batch compute recorded so far</dt><dd>{{ formatCost(guard.snapshot.amount) }}</dd></div>
          <div v-if="guard.limit !== null">
            <dt>Your total Batch limit</dt><dd>{{ formatCost(guard.limit) }}</dd>
          </div>
        </dl>
        <p>{{ guard.snapshot.coverage_start ? `Batch compute since ${formatDate(guard.snapshot.coverage_start, timezone)}` : 'No Batch history recorded yet' }}. Earlier costs that Rainstone could not reconstruct are left out.</p>
        <p>Calculated: {{ guard.snapshot.observed_at ? formatDateTime(guard.snapshot.observed_at, timezone) : 'Not available' }}.</p>
        <p v-if="guard.snapshot.incomplete_jobs">
          {{ guard.snapshot.incomplete_jobs }} {{ guard.snapshot.incomplete_jobs === 1 ? 'job needs' : 'jobs need' }} cost data. The recorded amount leaves out costs that are not available.
        </p>
        <p v-if="guard.snapshot.gaps">
          {{ guard.snapshot.gaps === 1 ? 'A gap' : `${guard.snapshot.gaps} gaps` }} in Batch observations may leave costs out.
        </p>
        <p
          v-if="guard.stale"
          class="limit-condition"
        >
          Cost data is out of date, so your spend limit may not be enforced.
        </p>
        <p
          v-if="guard.snapshot.unpriced_running_resources"
          class="limit-condition"
        >
          Some Batch compute can't be priced, so your spend limit may be exceeded.
        </p>
        <p
          v-if="guard.source_changed"
          class="error"
        >
          The enrolled Galaxy source changed. This limit does not apply to the new source. Turn off the old limit before setting a new one.
        </p>
        <p
          v-for="notice in guard.notifications.filter(item => item.error)"
          :key="notice.condition"
          class="limit-condition"
        >
          Galaxy notification could not be updated: {{ notice.error }}. Rainstone will retry.
        </p>
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
      </section>

      <form
        v-if="!confirmation"
        class="panel limit-form"
        @submit.prevent="review()"
        @input="dirty = true"
      >
        <h2>{{ guard.limit === null ? 'Set a total limit' : 'Change your total limit' }}</h2>
        <p>The limit includes costs already accrued. It does not start a new allowance when you save it.</p>
        <label for="batch-limit-amount">Batch spend limit (USD)</label>
        <input
          id="batch-limit-amount"
          v-model="amount"
          type="text"
          inputmode="decimal"
          autocomplete="off"
          required
          aria-describedby="limit-amount-help"
        >
        <p id="limit-amount-help">
          Enter more than the current recorded cost. Rainstone checks the latest estimate when you save.
        </p>
        <fieldset>
          <legend>When the limit is reached</legend>
          <label><input
            v-model="choice"
            type="radio"
            value="finish"
            name="batch-existing"
            required
          >{{ BATCH_FINISH_EFFECT }}</label>
          <label><input
            v-model="choice"
            type="radio"
            value="stop"
            name="batch-existing"
            required
          >{{ BATCH_STOP_EFFECT }}</label>
        </fieldset>
        <p>New jobs stop being sent to Batch when estimated spend approaches the limit. Jobs that fit on your Galaxy server still run.</p>
        <p>{{ BATCH_LIMIT_BEST_EFFORT }}</p>
        <div class="limit-actions">
          <button
            type="submit"
            class="primary"
            :disabled="guard.source_changed || guard.snapshot.amount === null"
          >
            Review limit
          </button>
          <button
            v-if="guard.limit !== null"
            type="button"
            class="secondary"
            @click="review(true)"
          >
            Turn off limit
          </button>
        </div>
      </form>
      <section
        v-else
        class="panel limit-confirmation"
        aria-labelledby="limit-confirm-title"
      >
        <h2
          id="limit-confirm-title"
          ref="confirmationHeading"
          tabindex="-1"
        >
          {{ confirmation.limit === null ? 'Turn off your Batch limit?' : 'Save this Batch limit?' }}
        </h2>
        <template v-if="confirmation.limit !== null">
          <p>Total limit: <strong>{{ formatCost(confirmation.limit) }}</strong>, including <strong>{{ formatCost(guard.snapshot.amount) }}</strong> recorded so far.</p>
          <p>{{ confirmation.stop_jobs ? BATCH_STOP_EFFECT : BATCH_FINISH_EFFECT }}</p>
          <p
            v-if="immediate"
            class="limit-condition"
          >
            This is already within the current margin. New Batch jobs will pause immediately.
          </p>
          <p>The guard leaves a margin for observation and shutdown delays. The margin grows when Batch is spending faster or cost data is older.</p>
          <p>{{ BATCH_LIMIT_SCOPE }} {{ BATCH_LIMIT_BEST_EFFORT }}</p>
        </template>
        <p v-else>
          Waiting jobs may now run on Batch. Stop requests already sent cannot be undone, and stopped jobs will not restart.
        </p>
        <div class="limit-actions">
          <button
            type="button"
            class="primary"
            :disabled="saving"
            @click="save"
          >
            {{ saving ? 'Saving…' : confirmation.limit === null ? 'Turn off Batch limit' : 'Save Batch limit' }}
          </button>
          <button
            type="button"
            class="secondary"
            :disabled="saving"
            @click="backToEdit"
          >
            Back to edit
          </button>
        </div>
      </section>
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
    </template>
  </div>
</template>
