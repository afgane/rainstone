import { computed, onBeforeUnmount, onMounted, onUpdated, ref } from "vue";

/**
 * The length a bar at full scale may take: the chart's track less its widest
 * value label, measured rather than assumed, so a label such as "less than
 * $0.01" always fits beside the longest bar.
 */
export function useBarRoom() {
  const chart = ref<HTMLElement | null>(null);
  const trackWidth = ref(0);
  const labelWidth = ref(0);

  function measure() {
    const track = chart.value?.querySelector<HTMLElement>(".track");
    trackWidth.value = track?.clientWidth ?? 0;
    let widest = 0;
    for (const label of chart.value?.querySelectorAll<HTMLElement>(".total") ?? []) {
      widest = Math.max(widest, label.offsetWidth + parseFloat(getComputedStyle(label).marginLeft));
    }
    labelWidth.value = Math.ceil(widest);
  }

  // Labels change size with their text and when the web font arrives, and
  // rows come and go, so the observed set is refreshed after every render.
  const observer = new ResizeObserver(measure);
  function observe() {
    observer.disconnect();
    const root = chart.value;
    if (!root) return;
    const track = root.querySelector(".track");
    if (track) observer.observe(track);
    for (const label of root.querySelectorAll(".total")) observer.observe(label);
    measure();
  }
  onMounted(observe);
  onUpdated(observe);
  onBeforeUnmount(() => observer.disconnect());

  return { chart, room: computed(() => Math.max(0, trackWidth.value - labelWidth.value)) };
}
