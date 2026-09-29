import { nextTick, ref, type Ref } from "vue";

export interface TooltipContent {
  /** The number that matters, first. */
  value: string;
  lines: string[];
}

/**
 * One tooltip for a chart. Pointer movement and keyboard focus show the same
 * content, so what a pointer user reads is not reserved for them.
 */
export function useChartTooltip(element: Ref<HTMLElement | null>) {
  const content = ref<TooltipContent | null>(null);
  const position = ref({ left: 0, top: 0 });

  async function show(next: TooltipContent, x: number, y: number) {
    content.value = next;
    position.value = { left: x + 14, top: y + 18 };
    await nextTick();
    const box = element.value?.getBoundingClientRect();
    if (!box) return;
    // Keep the tooltip inside the window, above the pointer when there is no room below.
    position.value = {
      left: Math.min(Math.max(8, x + 14), window.innerWidth - box.width - 8),
      top: y + 18 + box.height > window.innerHeight ? Math.max(8, y - box.height - 14) : y + 18,
    };
  }

  function hide() {
    content.value = null;
  }

  return { content, position, show, hide };
}
