import "server-only";

import { notFound } from "next/navigation";

import { ApiError } from "@/lib/api/server";

/** The response, or the nearest not-found page when the API says the entry doesn't exist. */
export async function orNotFound<T>(request: Promise<T>): Promise<T> {
  try {
    return await request;
  } catch (e) {
    if (e instanceof ApiError && (e.status === 404 || e.status === 422)) notFound();
    throw e;
  }
}

type Params = Record<string, string | string[] | undefined>;

/** A single string query parameter, or null. */
export const param = (q: Params, key: string): string | null => (typeof q[key] === "string" ? (q[key] as string) : null);
