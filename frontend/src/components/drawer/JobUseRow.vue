<script setup lang="ts">
import type { UseRow } from "../../jobDetail";
import { useDismissibleTip } from "./useDismissibleTip";

defineProps<{ row: UseRow }>();
const tip = useDismissibleTip();
</script>

<template>
  <figure class="use-row" :data-row="row.key">
    <figcaption class="use-caption">
      <span class="use-name">{{ row.label }}</span>
      <span v-if="row.comparison" class="use-values">{{ row.comparison.values }}</span>
    </figcaption>
    <template v-if="row.comparison">
      <div
        class="use-track" :data-above="row.comparison.aboveRequest" aria-hidden="true"
        @mouseenter="tip.show()" @mouseleave="tip.hide()"
      >
        <span class="use-fill" :style="{ width: `${row.comparison.fillPercent}%` }" />
        <span
          v-if="row.comparison.markerPercent !== null" class="use-marker"
          :style="{ left: `${row.comparison.markerPercent}%` }"
        />
      </div>
      <div
        v-if="row.comparison.markerPercent !== null" class="use-marker-label" aria-hidden="true"
        :data-side="row.comparison.markerPercent > 50 ? 'end' : 'start'"
        :style="{ left: `${row.comparison.markerPercent}%` }"
      >
        Requested
      </div>
      <p class="use-percent">
        {{ row.comparison.percent }}
        <span v-if="row.comparison.aboveRequest" class="sr-only">
          . The bar's scale is extended because use was above the request.
        </span>
      </p>
      <span v-if="tip.shown.value" class="use-tip" aria-hidden="true">{{ row.comparison.explanation }}</span>
    </template>
    <template v-else>
      <p v-for="fact in row.facts" :key="fact" class="use-fact">{{ fact }}</p>
      <p v-if="row.note" class="dialog-meta">{{ row.note }}</p>
    </template>
  </figure>
</template>
