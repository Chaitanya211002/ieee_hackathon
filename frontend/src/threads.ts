import type { Entry } from "./types";

/** A capture and the follow-up questions asked about it, oldest first. */
export interface Thread {
  root: Entry;
  followUps: Entry[];
}

/**
 * Group follow-up entries under the capture they are about.
 *
 * Every question stays its own hash-chained entry in the store; this only changes how the feed
 * is laid out. A follow-up whose original capture is not in the list (for example it was asked
 * from another experiment) is shown as a card of its own, as before.
 */
export function groupThreads(entries: Entry[]): Thread[] {
  const byId = new Map(entries.map((e) => [e.id, e]));
  const threads = new Map<string, Thread>();
  const order: Thread[] = [];
  for (const e of entries) {
    const rootId: string | undefined = e.details?.thread_root;
    const root = rootId && rootId !== e.id ? byId.get(rootId) : undefined;
    if (root) {
      let t = threads.get(root.id);
      if (!t) {
        // the original capture sorts later than its follow-up only if timestamps tie; keep its slot
        t = { root, followUps: [] };
        threads.set(root.id, t);
        order.push(t);
      }
      t.followUps.push(e);
    } else if (!threads.has(e.id)) {
      const t = { root: e, followUps: [] };
      threads.set(e.id, t);
      order.push(t);
    }
  }
  return order;
}

/** The entry a new follow-up should point at: the latest turn, so the model sees the whole thread. */
export const threadTail = (t: Thread): Entry => t.followUps[t.followUps.length - 1] ?? t.root;
