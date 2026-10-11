/**
 * Entry transition controller: login → (bus drives across) → destination dashboard.
 *
 * The login screen calls `runEntryTransition` only AFTER authentication has succeeded. The root layout hosts the
 * bus overlay (`TransitionHost`) and the dashboard reveal wrapper (`ArrivalReveal`), so the bus keeps driving while
 * the route changes and whichever existing dashboard the user lands on slides in. Only one transition can run.
 */

export const ENTRY_EASING = [0.22, 1, 0.36, 1] as const;
// Development only: `globalThis.__nbSlowMo = 8` plays the transition 8× slower for frame-by-frame checking.
const slowMo = () => (typeof __DEV__ !== 'undefined' && __DEV__ ? Number((globalThis as any).__nbSlowMo) || 1 : 1);
// ≤ 1 s and skippable with a tap (the dashboard appears behind the bus from ~40%)
export const BUS_DURATION_BASE_MS = 1000;
export const NAVIGATE_AT_BASE_MS = 380;
export const busDurationMs = () => BUS_DURATION_BASE_MS * slowMo();
export const navigateAtMs = () => NAVIGATE_AT_BASE_MS * slowMo();


type HostRunner = (opts: { reduced: boolean; navigate: () => void; done: () => void }) => void;
type RevealRunner = (reduced: boolean) => void;

let host: HostRunner | null = null;
let reveal: RevealRunner | null = null;
let active = false;

export function registerTransitionHost(fn: HostRunner | null) {
  host = fn;
}

export function registerArrivalReveal(fn: RevealRunner | null) {
  reveal = fn;
}

export function isTransitionActive() {
  return active;
}

/** Plays the bus transition, calls `navigate` part-way through and reveals the destination. Never runs twice at once. */
export function runEntryTransition(navigate: () => void, reduced: boolean): Promise<void> {
  if (active) return Promise.resolve();
  active = true;
  return new Promise(resolve => {
    let navigated = false;
    const go = () => {
      if (navigated) return;
      navigated = true;
      navigate();
      reveal?.(reduced);
    };
    const finish = () => {
      go(); // safety: always end on the destination
      active = false;
      resolve();
    };
    if (!host) return finish();
    try {
      host({ reduced, navigate: go, done: finish });
    } catch {
      finish();
    }
  });
}

// Development only: preview the transition without signing in (stays on the current page).
if (typeof __DEV__ !== 'undefined' && __DEV__) {
  (globalThis as any).__nbPreviewTransition = (reduced = false) => runEntryTransition(() => undefined, reduced);
}
