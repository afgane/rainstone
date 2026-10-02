<script setup lang="ts">
defineProps<{ canViewServer: boolean }>();
</script>

<template>
  <ol class="overview-guide">
    <li>
      <h3>{{ canViewServer ? "Read the two costs" : "Read your run compute cost" }}</h3>
      <p>
        Run compute covers the machines started to run your matching jobs in the selected period, whether
        the jobs ran in a workflow or on their own.
        <template v-if="canViewServer">Jobs that ran on the Galaxy server itself add nothing here.</template>
      </p>
      <p v-if="canViewServer">
        Galaxy server covers the whole server since its current launch, including idle time.
        It is an additional cost and stays the same when you change the period.
      </p>
    </li>
    <li>
      <h3>Choose your period</h3>
      <p>Use the period choices to explore another time window, or choose Custom dates.</p>
    </li>
    <li>
      <h3>Explore what ran</h3>
      <p>Select a chart block to see that interval's workflow runs or jobs outside workflows.</p>
      <p>Explore this period shows the period's top workflow runs and tools. Details open here without changing your report.</p>
    </li>
  </ol>
  <p class="dialog-meta">
    Amounts are estimated compute costs in USD. They do not include data storage or data transfer out of the
    cloud (egress), which are billed separately. “Recorded so far” means some jobs still need cost data.
  </p>
</template>
