// Drives one Plaid Link session using Plaid's own CDN script. No npm
// package -- the global constraints call for exactly one script
// (link-initialize.js), loaded on demand, and nothing else.

interface PlaidLinkCreateConfig {
  token: string;
  onSuccess: (publicToken: string) => void;
  onExit: () => void;
}

interface PlaidLinkHandler {
  open: () => void;
}

// Minimal shape of the global Plaid's script defines -- just enough to
// drive one Link session, not a full typing of their SDK.
declare global {
  interface Window {
    Plaid?: {
      create: (config: PlaidLinkCreateConfig) => PlaidLinkHandler;
    };
  }
}

const PLAID_LINK_SCRIPT_URL = "https://cdn.plaid.com/link/v2/stable/link-initialize.js";

// Module-level so repeated calls -- opening Link again, reconnecting a
// second connection, etc. -- never inject the script twice.
let linkScriptPromise: Promise<void> | null = null;

export function loadPlaidLink(): Promise<void> {
  if (linkScriptPromise) return linkScriptPromise;
  linkScriptPromise = new Promise<void>((resolve, reject) => {
    if (window.Plaid) {
      resolve();
      return;
    }
    const script = document.createElement("script");
    script.src = PLAID_LINK_SCRIPT_URL;
    script.async = true;
    script.onload = () => resolve();
    script.onerror = () => {
      // Let a later call retry rather than permanently remembering a
      // transient failure (a flaky network load shouldn't lock Plaid out
      // for the rest of the session).
      linkScriptPromise = null;
      reject(new Error("Failed to load Plaid Link"));
    };
    document.head.appendChild(script);
  });
  return linkScriptPromise;
}

/**
 * Opens one Plaid Link session with the given token -- a fresh link_token
 * for a brand-new connection, or an update-mode token for reconnecting an
 * existing one. Resolves with the public token on success, or null if the
 * user exits without finishing.
 */
export function openPlaidLink(linkToken: string): Promise<{ publicToken: string } | null> {
  return loadPlaidLink().then(
    () =>
      new Promise<{ publicToken: string } | null>((resolve, reject) => {
        if (!window.Plaid) {
          reject(new Error("Plaid Link failed to load"));
          return;
        }
        const handler = window.Plaid.create({
          token: linkToken,
          onSuccess: (publicToken) => resolve({ publicToken }),
          onExit: () => resolve(null),
        });
        handler.open();
      }),
  );
}
