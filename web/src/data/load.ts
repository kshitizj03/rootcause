import type { IndexData } from "./types";

export class DataError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "DataError";
  }
}

const isObject = (x: unknown): x is Record<string, unknown> =>
  typeof x === "object" && x !== null && !Array.isArray(x);

export function checkIndex(x: unknown): IndexData {
  if (!isObject(x)) throw new DataError("index.json is not an object");
  const arrays = ["solvers", "incidents", "paired"];
  const objects = ["summary", "planned_runs"];
  for (const k of arrays) {
    if (!Array.isArray(x[k])) throw new DataError(`index.json: "${k}" is missing or not an array`);
  }
  for (const k of objects) {
    if (!isObject(x[k])) throw new DataError(`index.json: "${k}" is missing or not an object`);
  }
  return x as unknown as IndexData;
}

export async function loadIndex(url = "data/index.json"): Promise<IndexData> {
  let json: unknown;
  try {
    const res = await fetch(url);
    if (!res.ok) throw new DataError(`${url} returned HTTP ${res.status}`);
    json = await res.json();
  } catch (e) {
    if (e instanceof DataError) throw e;
    throw new DataError(`could not load ${url}: ${e instanceof Error ? e.message : String(e)}`);
  }
  return checkIndex(json);
}
