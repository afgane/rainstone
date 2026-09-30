<script setup lang="ts">
import {
  CircleCheck, Circle, CircleHelp, CirclePause, CircleX, Clock, LoaderCircle, RotateCw, Square, Trash2,
} from "@lucide/vue";
import { computed } from "vue";
import { jobStateKind, type JobStateKind } from "../../vocabulary";

const props = defineProps<{ state: string }>();

const ICONS = {
  completed: CircleCheck, running: LoaderCircle, failed: CircleX, queued: Clock, cancelled: Square,
  paused: CirclePause, "not-started": Circle, deleted: Trash2, restarted: RotateCw, unknown: CircleHelp,
};
const kind = computed<JobStateKind>(() => jobStateKind(props.state));
</script>

<template>
  <component
    :is="ICONS[kind]" class="state-icon" :data-kind="kind" :size="18" :stroke-width="2.25"
    aria-hidden="true" focusable="false"
  />
</template>
