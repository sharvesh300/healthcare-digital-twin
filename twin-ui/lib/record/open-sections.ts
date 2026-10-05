"use client";

// Which record sections the viewer has expanded. Remembered in this browser (localStorage) and
// shared across patients, so the record opens the way the viewer last left it. Sections the
// viewer never touched use their default. Server render and hydration see only defaults.

import { useSyncExternalStore } from "react";

const KEY = "twin.record.open";
type State = Record<string, boolean>;

const EMPTY: State = {};
let state: State | null = null;
const listeners = new Set<() => void>();

function load(): State {
  try {
    const raw = window.localStorage.getItem(KEY);
    return raw ? (JSON.parse(raw) as State) : {};
  } catch {
    return {};
  }
}

function save(next: State) {
  state = next;
  try {
    window.localStorage.setItem(KEY, JSON.stringify(next));
  } catch {
    // private mode or blocked storage: the state still holds for this page
  }
  listeners.forEach((l) => l());
}

/** A section named in the URL hash (#tests) opens: links and the section nav land expanded. */
function openFromHash() {
  const id = decodeURIComponent(window.location.hash.slice(1));
  if (id && state?.[id] !== true) save({ ...(state ?? load()), [id]: true });
}

function subscribe(listener: () => void) {
  if (state === null) {
    state = load();
    openFromHash();
  }
  listeners.add(listener);
  if (listeners.size === 1) window.addEventListener("hashchange", openFromHash);
  return () => {
    listeners.delete(listener);
    if (!listeners.size) window.removeEventListener("hashchange", openFromHash);
  };
}

export function setOpen(id: string, open: boolean) {
  save({ ...(state ?? load()), [id]: open });
}

export function setManyOpen(ids: string[], open: boolean) {
  save({ ...(state ?? load()), ...Object.fromEntries(ids.map((id) => [id, open])) });
}

/** Whether a section is open: the viewer's choice, else `fallback`. */
export function useOpen(id: string, fallback: boolean): boolean {
  return useSyncExternalStore(
    subscribe,
    () => (state ?? EMPTY)[id] ?? fallback,
    () => fallback,
  );
}

/** Whether every one of `ids` is open (for "Expand all" / "Collapse all"). */
export function useAllOpen(ids: { id: string; fallback: boolean }[]): boolean {
  return useSyncExternalStore(
    subscribe,
    () => ids.every(({ id, fallback }) => (state ?? EMPTY)[id] ?? fallback),
    () => ids.every(({ fallback }) => fallback),
  );
}
