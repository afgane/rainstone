<script setup lang="ts">
import { computed } from "vue";
import type { JobDetail } from "../../api";
import { buildTimeline } from "../../jobDetail";
import {
  dayKey, TIMELINE_HEADING, formatClock, formatDateTime, formatExactDateTime, TIMELINE_LABEL, WAITING_TO_START,
} from "../../vocabulary";

const props = defineProps<{ detail: JobDetail; timezone: string }>();
const timeline = computed(() => buildTimeline(props.detail));

// The date appears wherever the day changes, so a job crossing midnight is never ambiguous.
const events = computed(() => timeline.value.events.map((event, position, all) => ({
  ...event,
  label: TIMELINE_LABEL[event.key],
  text: position === 0 || dayKey(event.at, props.timezone) !== dayKey(all[position - 1].at, props.timezone)
    ? formatDateTime(event.at, props.timezone) : formatClock(event.at, props.timezone),
  exact: formatExactDateTime(event.at, props.timezone),
})));
</script>

<template>
  <section class="job-section" aria-labelledby="job-execution-heading">
    <h3 id="job-execution-heading">{{ TIMELINE_HEADING }}</h3>
    <div
      v-if="timeline.drawn" class="timeline-graphic" :data-running="timeline.running" aria-hidden="true"
    >
      <span class="timeline-before" :style="{ width: `${timeline.startPercent}%` }" />
      <span
        class="timeline-tool" :style="{ left: `${timeline.startPercent}%`, right: '0' }"
      />
      <span class="timeline-mark" data-event="submitted" style="left: 0%" />
      <span class="timeline-mark" data-event="started" :style="{ left: `${timeline.startPercent}%` }" />
      <span class="timeline-mark" :data-event="timeline.running ? 'recorded' : 'finished'" style="left: 100%" />
    </div>
    <p v-if="timeline.waiting" class="dialog-meta">{{ WAITING_TO_START }}</p>
    <ol class="timeline-events">
      <li v-for="event in events" :key="event.key" :data-event="event.key">
        <span class="timeline-key" aria-hidden="true" />
        <span class="timeline-label">{{ event.label }}</span>
        <time :datetime="event.at" :title="event.exact">
          <span aria-hidden="true">{{ event.text }}</span><span class="sr-only">{{ event.exact }}</span>
        </time>
      </li>
    </ol>
    <p v-if="timeline.note" class="dialog-meta">{{ timeline.note }}</p>
    <p class="dialog-meta timeline-zone">Times are shown in {{ timezone }}.</p>
  </section>
</template>
