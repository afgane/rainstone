/** A selector for an element by one of its attributes, safe for values with quotes or slashes. */
export function byAttribute(name: string, value: string): string {
  return `[${name}="${value.replace(/["\\]/g, "\\$&")}"]`;
}
