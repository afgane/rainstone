import { computed, onBeforeUnmount, onMounted, onUpdated, ref } from "vue";

/**
 * The length a bar at full scale may take: the chart's track less the label
 * beside a full-scale bar, measured rather than assumed, so a label such as
 * "less than $0.01" always fits beside the longest bar.
 *
 * The chart marks that label with `data-full-scale`. Measuring whichever labels
 * happen to be shown instead would let showing more rows, or finding one,
 * change the room, and with it every bar's length on what is meant to be one
 * scale. A chart whose full-scale row may be off screen renders a hidden copy.
 */
export function useBarRoom() {
  const chart = ref<HTMLElement | null>(null);
  const trackWidth = ref(0);
  const labelWidth = ref(0);

  function measure() {
    const track = chart.value?.querySelector<HTMLElement>(".track");
    trackWidth.value = track?.clientWidth ?? 0;
    const label = chart.value?.querySelector<HTMLElement>("[data-full-scale]");
    labelWidth.value = label
      ? Math.ceil(label.offsetWidth + parseFloat(getComputedStyle(label).marginLeft))
      : 0;
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
    const label = root.querySelector("[data-full-scale]");
    if (label) observer.observe(label);
    measure();
  }
  onMounted(observe);
  onUpdated(observe);
  onBeforeUnmount(() => observer.disconnect());

  return { chart, room: computed(() => Math.max(0, trackWidth.value - labelWidth.value)) };
}
