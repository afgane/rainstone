<script setup lang="ts">
import { MousePointerClick } from "@lucide/vue";
import { computed, ref, watch } from "vue";
import type { InvocationDetail } from "../../api";
import { collidingNames, composeCost, partQualifier } from "../../costBreakdown";
import {
  BREAKDOWN_HEADING, BREAKDOWN_UNAVAILABLE, environmentLabel, formatCost, formatShare, jobsInPart,
  needsCostData, pluralize, selectionGone, shareBasis,
} from "../../vocabulary";
import ContributorDetails from "./ContributorDetails.vue";
import CostFingerprint from "./CostFingerprint.vue";

const props = defineProps<{
  detail: InvocationDetail;
  /** The open part's key, and the pooled part's member inside it; empty for none. */
  selected: string;
  member: string;
  running: boolean;
}>();
const emit = defineEmits<{
  select: [key: string, member: string];
  open: [jobId: string];
}>();

const composition = computed(() => composeCost(props.detail));
const complete = computed(() => props.detail.cost_breakdown.complete);
const names = computed(() => collidingNames(composition.value.parts));
// A part a control is pointing at lights its squares; only keyboard focus also shows the tooltip,
// since the pointer already has the control's own text under it.
const pointed = ref("");
const tipped = ref("");
const announcement = ref("");

const openPart = computed(() => composition.value.parts.find(each => each.key === props.selected) ?? null);
const validMember = computed(() => Boolean(
  openPart.value && (!props.member || openPart.value.members.some(each => each.key === props.member)),
));

// A link or a reload can name a part the data no longer has; clear it and say so.
watch([composition, () => props.selected, () => props.member], () => {
  if (!props.selected) return;
  if (composition.value.status === "chart" && openPart.value && validMember.value) return;
  emit("select", "", "");
  announcement.value = selectionGone();
}, { immediate: true });

watch(openPart, part => {
  if (part) announcement.value = `${part.name}, ${formatCost(part.amount)}, ${jobsInPart(part.jobIds.length)}`;
});

function focused(key: string, event: FocusEvent) {
  pointed.value = key;
  try {
    if ((event.target as HTMLElement).matches(":focus-visible")) tipped.value = key;
  } catch {
    tipped.value = key;
  }
}
function blurred() {
  pointed.value = ""; tipped.value = "";
}
function choose(key: string) {
  emit("select", props.selected === key ? "" : key, "");
}
// What each part says when a screen reader or the keyboard reaches it.
const drawn = computed(() => composition.value.parts.filter(part => part.cells > 0));
const tiny = computed(() => composition.value.parts.filter(part => part.cells === 0));
function describe(part: (typeof drawn.value)[number]): string {
  const place = part.kind === "other" && part.environment === "multiple"
    ? "Multiple environments" : environmentLabel(part.environment);
  const qualifier = names.value.has(part.name) ? `, ${partQualifier(part)}` : "";
  return `${part.name}${qualifier}, ${formatCost(part.amount)}, ${formatShare(part.share)} `
    + `${shareBasis(props.running, complete.value)}, ${place}`;
}
const noPaidCost = computed(() => {
  const { unknownJobs } = composition.value;
  return [
    "Nothing in this run added compute cost, so there is nothing to break down.",
    unknownJobs ? `${needsCostData(unknownJobs, "job")}.` : "",
  ].filter(Boolean).join(" ");
});
</script>

<template>
  <section class="cost-breakdown" aria-labelledby="breakdown-heading">
    <h3 id="breakdown-heading">{{ BREAKDOWN_HEADING }}</h3>
    <p class="sr-only" role="status" aria-live="polite">{{ announcement }}</p>

    <template v-if="composition.status === 'chart'">
      <CostFingerprint
        :composition="composition" :selected="selected" :pointed="pointed" :tipped="tipped" :running="running"
        :complete="complete" @select="choose"
      />
      <!-- The squares are the picture; these buttons are their keyboard and screen reader path.
           Focusing one lights its squares, so focus is always visible in the chart. -->
      <ul class="part-list sr-only">
        <li v-for="part in drawn" :key="part.key">
          <button
            type="button" :aria-pressed="selected === part.key"
            :aria-controls="selected === part.key ? 'part-detail' : undefined"
            :data-part="part.key" :data-environment="part.environment" :data-kind="part.kind"
            @click="choose(part.key)" @focus="focused(part.key, $event)" @blur="blurred"
          >
            {{ describe(part) }}
          </button>
        </li>
      </ul>
      <!-- A part with no square of its own cannot be pressed in the chart, so it is listed. -->
      <template v-if="tiny.length">
        <p class="dialog-meta tiny-note">Too small to show in the chart:</p>
        <ul class="part-list tiny-list">
          <li v-for="part in tiny" :key="part.key">
            <button
              type="button" class="part-button" :aria-pressed="selected === part.key"
              :aria-controls="selected === part.key ? 'part-detail' : undefined"
              :data-part="part.key" :data-environment="part.environment" :data-kind="part.kind"
              @click="choose(part.key)"
            >
              <span class="part-name">
                {{ part.name }}
                <small v-if="part.kind === 'other'">{{ pluralize(part.members.length, "part") }}</small>
              </span>
              <span class="part-amount">{{ formatCost(part.amount) }}</span>
              <span class="part-share">{{ formatShare(part.share) }}</span>
            </button>
          </li>
        </ul>
      </template>
      <p v-if="running || !complete" class="dialog-meta">
        Shares are {{ running ? "of the cost so far" : "of the cost recorded so far" }}.
      </p>
      <ContributorDetails
        v-if="openPart && validMember" :part="openPart" :composition="composition" :jobs="detail.jobs"
        :member="member" :running="running" :complete="complete"
        @open="emit('open', $event)" @member="emit('select', selected, $event)"
        @clear="emit('select', '', '')"
      />
      <p v-else id="part-placeholder" class="part-placeholder">
        <MousePointerClick :size="18" aria-hidden="true" />
        <span>Choose a square in the chart to see what that tool cost and which jobs it ran.</span>
      </p>
    </template>

    <p v-else-if="composition.status === 'empty'" class="dialog-meta">{{ noPaidCost }}</p>
    <div v-else class="dialog-meta" role="note">
      <strong>{{ BREAKDOWN_UNAVAILABLE }}.</strong>
      <span v-if="composition.reason"> {{ composition.reason }}</span>
      <span> The total above and the list of jobs remain available.</span>
    </div>
  </section>
</template>
