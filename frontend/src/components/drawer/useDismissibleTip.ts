import { onBeforeUnmount, ref, watch } from "vue";

/**
 * A tooltip that Escape dismisses before anything else does, so a first Escape
 * clears the tip and only a second one closes the drawer around it.
 */
export function useDismissibleTip() {
  const shown = ref(false);

  function onKeyDown(event: KeyboardEvent) {
    if (event.key !== "Escape") return;
    shown.value = false;
    event.stopImmediatePropagation();
    event.preventDefault();
  }

  watch(shown, (open, wasOpen) => {
    if (open && !wasOpen) document.addEventListener("keydown", onKeyDown, true);
    else if (!open && wasOpen) document.removeEventListener("keydown", onKeyDown, true);
  });
  onBeforeUnmount(() => document.removeEventListener("keydown", onKeyDown, true));

  return {
    shown,
    show: () => { shown.value = true; },
    hide: () => { shown.value = false; },
  };
}
