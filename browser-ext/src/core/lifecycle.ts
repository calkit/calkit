/**
 * Running a content script: following navigation, and shutting down once the
 * extension reloads.
 */
import { isExtensionAlive, onAuthChange, onUrlChange } from "./messages";

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
  /** Called once, after any older copy has shut down, to watch the page. */
  watch?: () => void;
  /** Called on load and on every navigation within the page. */
  sync: () => void;
  /** Remove everything this script added to the page. */
  teardown: () => void;
  /** Called when someone signs in or out, from this page or any other. */
  authChanged: () => void;
}): void {
  // A page can end up with the same content script injected more than once,
  // e.g., after the extension is reloaded while the tab is open. Only the
  // newest copy should be doing anything. The older one may be in another
  // world, which shares only the DOM, so it's told with a DOM event.
  function stop(): void {
    if (stopped) {
      return;
    }
    stopped = true;
    document.removeEventListener(event, stop);
    stopListening();
    if (checkTimer !== undefined) {
      clearInterval(checkTimer);
    }
    options.teardown();
  }
  function checkAlive(): boolean {
    if (isExtensionAlive()) {
      return true;
    }
    stop();
    return false;
  }
  let stopListening: () => void = () => undefined;
  let checkTimer: ReturnType<typeof setInterval> | undefined;
  let stopped = false;
  const event = `calkit-${options.id}-started`;
  document.dispatchEvent(new Event(event));
  document.addEventListener(event, stop, { once: true });
  options.watch?.();
  const stopUrl = onUrlChange(() => {
    if (!checkAlive()) {
      return;
    }
    options.sync();
  });
  const stopAuth = onAuthChange(() => {
    if (checkAlive()) {
      options.authChanged();
    }
  });
  stopListening = () => {
    stopUrl();
    stopAuth();
  };
  // The page gets no event when an extension is reloaded, so an orphan can
  // only find out by asking. This is the one timer in a content script, it
  // is cheap, and it stops itself the first time the answer is no.
  checkTimer = setInterval(checkAlive, 5000);
  options.sync();
}
