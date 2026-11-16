import { afterEach, describe, expect, it, vi } from "vitest";
import { fixtureIndex } from "../test/fixture";
import { DataError, checkIndex, loadIndex } from "./load";

afterEach(() => vi.unstubAllGlobals());

describe("checkIndex", () => {
  it("accepts the fixture", () => {
    const x = fixtureIndex();
    expect(checkIndex(x)).toBe(x);
  });

  it("names a missing field", () => {
    const x: Record<string, unknown> = { ...fixtureIndex() };
    delete x.paired;
    expect(() => checkIndex(x)).toThrow(DataError);
    expect(() => checkIndex(x)).toThrow(/paired/);
  });

  it("names a mistyped field", () => {
    const x = { ...fixtureIndex(), summary: [] };
    expect(() => checkIndex(x)).toThrow(/summary/);
  });

  it("rejects a non-object", () => {
    for (const bad of [null, [], "x"]) expect(() => checkIndex(bad)).toThrow(DataError);
  });
});

describe("loadIndex", () => {
  it("returns the checked index on success", async () => {
    const x = fixtureIndex();
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => x }));
    await expect(loadIndex()).resolves.toEqual(x);
  });

  it("turns a 404 into DataError", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 404 }));
    await expect(loadIndex()).rejects.toThrow(DataError);
  });

  it("turns bad JSON into DataError", async () => {
    const json = () => Promise.reject(new SyntaxError("bad json"));
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json }));
    await expect(loadIndex()).rejects.toThrow(DataError);
  });
});
