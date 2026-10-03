/** What to show a person for a caught error: its message, or the value itself. */
export function errorText(e: unknown): string {
  return String((e as Error)?.message || e);
}
