<script setup lang="ts">
import { ArrowLeft, X } from "@lucide/vue";
import { computed, nextTick, ref } from "vue";
import type { RunJob } from "../../api";
import { byAttribute } from "../../dom";
import type { CostComposition, Part } from "../../costBreakdown";
import {
  CLEAR_SELECTION, environmentLabel, formatCost, formatShare, jobsInPart, shareBasis, showMore, shownOf,
} from "../../vocabulary";
import JobRow from "./JobRow.vue";

const props = defineProps<{
  part: Part;
  composition: CostComposition;
  jobs: RunJob[];
  /** A pooled part's member opened within this same area. */
  member: string;
  running: boolean;
  complete: boolean;
}>();
const emit = defineEmits<{
  open: [jobId: string];
  member: [key: string];
  clear: [];
}>();

const PAGE = 50;
const visible = ref(PAGE);
const title = ref<HTMLElement | null>(null);
const area = ref<HTMLElement | null>(null);
const byId = computed(() => new Map(props.jobs.map(job => [job.id, job])));
const shown = computed<Part>(() => props.part.members.find(each => each.key === props.member) ?? props.part);
const inMember = computed(() => shown.value !== props.part);
const members = computed(() => (shown.value.kind === "other" ? shown.value.members : []));
const rows = computed(() => shown.value.jobIds.map(id => byId.value.get(id)).filter((job): job is RunJob => Boolean(job)));
// A virtual machine's jobs used it; their own cost is not a share of its charge.
const showsCost = computed(() => shown.value.kind !== "vm_session");
const place = computed(() => (shown.value.kind === "other" && shown.value.environment === "multiple"
  ? "Multiple environments" : environmentLabel(shown.value.environment)));

async function openMember(key: string) {
  emit("member", key);
  // The button that was pressed is gone; the member's heading is where reading continues.
  await nextTick();
  title.value?.focus({ preventScroll: true });
}
async function backToOther() {
  const from = props.member;
  emit("member", "");
  await nextTick();
  area.value?.querySelector<HTMLElement>(byAttribute("data-member-key", from))?.focus();
}
</script>

<template>
  <section
    id="part-detail" ref="area" class="part-detail" aria-labelledby="part-detail-title"
    :data-kind="shown.kind"
  >
    <button type="button" class="detail-clear" :aria-label="CLEAR_SELECTION" @click="emit('clear')">
      <X :size="16" aria-hidden="true" />
    </button>
    <div v-if="inMember" class="detail-head">
      <button type="button" class="link-button back-to" @click="backToOther">
        <ArrowLeft :size="14" aria-hidden="true" /> Back to {{ part.name }}
      </button>
    </div>
    <h4 id="part-detail-title" ref="title" tabindex="-1">{{ shown.name }}</h4>
    <dl class="detail-facts">
      <dt>Cost</dt><dd>{{ formatCost(shown.amount) }}</dd>
      <dt>Share</dt>
      <dd>{{ formatShare(shown.share) }} {{ shareBasis(running, complete) }}</dd>
      <dt>Where it ran</dt><dd>{{ place }}</dd>
      <dt>{{ shown.kind === "other" ? "Parts" : "Jobs" }}</dt>
      <dd>
        {{ shown.kind === "other" ? members.length : jobsInPart(shown.jobIds.length) }}
      </dd>
    </dl>
    <p v-if="!shown.complete" class="dialog-meta">
      Some of this cost is still missing, so the amount is a subtotal.
    </p>

    <ul v-if="members.length" class="member-list">
      <li v-for="each in members" :key="each.key">
        <button type="button" class="member-button" :data-member-key="each.key" @click="openMember(each.key)">
          <span class="member-name">{{ each.name }}</span>
          <span class="member-amount">{{ formatCost(each.amount) }}</span>
          <span class="member-share">{{ formatShare(each.share) }}</span>
          <span class="member-jobs">{{ jobsInPart(each.jobIds.length) }}</span>
        </button>
      </li>
    </ul>
    <template v-else>
      <ul class="job-list" role="list" :data-with-cost="showsCost">
        <JobRow
          v-for="job in rows.slice(0, visible)" :key="job.id" :job="job" :show-cost="showsCost" show-id
          @open="emit('open', $event)"
        />
      </ul>
      <template v-if="rows.length > visible">
        <p class="group-summary">{{ shownOf(visible, rows.length, "job") }}</p>
        <button type="button" class="link-button" @click="visible += PAGE">
          {{ showMore(Math.min(PAGE, rows.length - visible)) }}
        </button>
      </template>
    </template>
  </section>
</template>
