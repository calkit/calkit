import { isExtensionAlive, onUrlChange } from "./messages";

/**
 * Wire a content script's lifecycle: react to navigation, and shut down
 * cleanly once the extension is reloaded out from under it.
 *
 * A reloaded extension leaves its already-injected content scripts running
 * in the page, connected to nothing. Left alone they keep their UI on
 * screen, keep answering clicks, and fail every one of those clicks. So a
 * script watches for that, removes what it put in the page, and stops
 * listening, leaving the page as if it had never run.
 */
export function runContentScript(options: {
  /** Distinguishes this script from the others, for the re-injection guard. */
  id: string;
  /** Called on load and on every navigation within the page. */
  sync: () => void;
  /** Remove everything this script added to the page. */
  teardown: () => void;
}): void {
  // A page can end up with the same content script injected more than once,
  // e.g. after the extension is reloaded while the tab is open. Only the
  // newest copy should be doing anything.
  let stopListening: () => void = () => undefined;
  let checkTimer: ReturnType<typeof setInterval> | undefined;
  const marker = `__calkit_${options.id}`;
  const globals = window as unknown as Record<string, unknown>;
  const previous = globals[marker];
  if (typeof previous === "function") {
    (previous as () => void)();
  }
  globals[marker] = () => {
    stopListening();
    if (checkTimer !== undefined) {
      clearInterval(checkTimer);
    }
    options.teardown();
  };
  stopListening = onUrlChange(() => {
    if (!checkAlive()) {
      return;
    }
    options.sync();
  });

  function checkAlive(): boolean {
    if (isExtensionAlive()) {
      return true;
    }
    stopListening();
    if (checkTimer !== undefined) {
      clearInterval(checkTimer);
    }
    options.teardown();
    return false;
  }

  // The page gets no event when an extension is reloaded, so an orphan can
  // only find out by asking. This is the one timer in a content script, it
  // is cheap, and it stops itself the first time the answer is no.
  checkTimer = setInterval(checkAlive, 5000);
  options.sync();
}
