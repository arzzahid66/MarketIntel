import { describe, expect, it } from "vitest";

import { squarify } from "@/lib/treemap";

const WIDTH = 800;
const HEIGHT = 400;

function input(values: number[]) {
  return values.map((value, index) => ({ key: `k${index}`, value }));
}

describe("squarify", () => {
  it("gives every tile an area proportional to its value", () => {
    const values = [17.02, 6.34, 4.81, 2.38, 2.25, 2.15, 1.45, 0.62, 0.41, 0.38, 0.28];
    const rects = squarify(input(values), WIDTH, HEIGHT);
    const total = values.reduce((sum, v) => sum + v, 0);

    expect(rects).toHaveLength(values.length);
    for (const rect of rects) {
      const expected = (rect.item.value / total) * WIDTH * HEIGHT;
      // Area is the data. A tile whose area is wrong is a chart that lies.
      expect(rect.width * rect.height).toBeCloseTo(expected, 4);
    }
  });

  it("fills the box exactly, with no overlap and no gaps", () => {
    const rects = squarify(input([5, 4, 3, 2, 1, 1]), WIDTH, HEIGHT);

    const area = rects.reduce((sum, r) => sum + r.width * r.height, 0);
    expect(area).toBeCloseTo(WIDTH * HEIGHT, 3);

    for (const rect of rects) {
      expect(rect.x).toBeGreaterThanOrEqual(-1e-9);
      expect(rect.y).toBeGreaterThanOrEqual(-1e-9);
      expect(rect.x + rect.width).toBeLessThanOrEqual(WIDTH + 1e-9);
      expect(rect.y + rect.height).toBeLessThanOrEqual(HEIGHT + 1e-9);
    }
  });

  it("keeps tiles roughly square, which is the whole point of squarifying", () => {
    const rects = squarify(input([10, 9, 8, 7, 6, 5, 4, 3, 2, 1]), 600, 600);
    const ratios = rects.map((r) => Math.max(r.width / r.height, r.height / r.width));
    // Slice-and-dice on this input produces slivers above 10:1; squarified
    // should keep everything well under that or area cannot be compared by eye.
    expect(Math.max(...ratios)).toBeLessThan(5);
  });

  it("drops non-positive values rather than emitting invisible tiles", () => {
    const rects = squarify(input([4, 0, 2, -1]), WIDTH, HEIGHT);
    expect(rects.map((r) => r.item.value)).toEqual([4, 2]);
  });

  it("returns nothing for an empty list or a zero-sized box", () => {
    expect(squarify(input([]), WIDTH, HEIGHT)).toEqual([]);
    expect(squarify(input([1, 2]), 0, HEIGHT)).toEqual([]);
    expect(squarify(input([1, 2]), WIDTH, 0)).toEqual([]);
  });

  it("sorts internally, so the caller need not", () => {
    const ascending = squarify(input([1, 5, 3]), WIDTH, HEIGHT);
    expect(ascending.map((r) => r.item.value)).toEqual([5, 3, 1]);
  });
});
