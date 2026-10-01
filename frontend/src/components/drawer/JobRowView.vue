<script setup lang="ts">
import JobStateIcon from "./JobStateIcon.vue";
import { useDismissibleTip } from "./useDismissibleTip";

/**
 * One job as a compact drawer row: name, state icon, duration and cost. The
 * adapters around it decide what each column means for their own list, so a
 * period's share of a cost never passes for a whole job's amount.
 */
defineProps<{
  id: string;
  toolName: string;
  state: string;
  duration: string;
  /** Null hides the cost column. */
  cost: string | null;
  /** Everything the columns say, in words, so nothing depends on truncated text. */
  label: string;
  /** Small text after the name, such as an identifier where equal names must be told apart. */
  idText?: string;
  flag?: string;
  tipTitle: string;
  tipLines: string[];
}>();
const emit = defineEmits<{ open: [id: string] }>();

const tip = useDismissibleTip();

function onFocus(event: FocusEvent) {
  // A pointer press focuses the row too; only keyboard focus needs a tooltip of its own.
  try {
    if ((event.target as HTMLElement).matches(":focus-visible")) tip.show();
  } catch {
    tip.show();
  }
}
</script>

<template>
  <li class="job-item" role="listitem">
    <button
      type="button" class="job-row" data-detail-trigger :data-job-id="id" :aria-label="label"
      @click="emit('open', id)" @mouseenter="tip.show()" @mouseleave="tip.hide()"
      @focus="onFocus" @blur="tip.hide()"
    >
      <span class="job-name">
        <span class="job-title">{{ toolName }}</span>
        <span v-if="idText" class="job-id">{{ idText }}</span>
        <span v-if="flag" class="job-flag">{{ flag }}</span>
      </span>
      <span class="job-state"><JobStateIcon :state="state" /></span>
      <span class="job-duration">{{ duration }}</span>
      <span v-if="cost !== null" class="job-cost">{{ cost }}</span>
      <span v-if="tip.shown.value" class="job-tip" aria-hidden="true">
        <strong>{{ tipTitle }}</strong>
        <span v-for="line in tipLines" :key="line">{{ line }}</span>
      </span>
    </button>
  </li>
</template>
