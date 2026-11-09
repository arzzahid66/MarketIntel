/**
 * Squarified treemap layout. Pure geometry, no React, no dependency.
 *
 * Our own implementation on purpose: the build plan (section 6) is explicit that
 * Finviz's map is their intellectual property and must not be embedded or
 * copied. This is the published squarified algorithm (Bruls, Huizing & van Wijk,
 * 2000), which is a paper, not someone's product.
 *
 * Why squarified rather than slice-and-dice: slice-and-dice gives long thin
 * slivers whose area is impossible to compare by eye, and area *is* the data
 * here. Squarified keeps aspect ratios near 1 so a tile twice the size looks
 * twice the size.
 */

export interface TreemapInput {
  key: string;
  /** Must be >= 0. Zero-value items are dropped: a zero-area tile is invisible
   *  anyway, and keeping it would divide by zero in the aspect-ratio test. */
  value: number;
}

export interface TreemapRect<T> {
  item: T;
  x: number;
  y: number;
  width: number;
  height: number;
}

interface Box {
  x: number;
  y: number;
  width: number;
  height: number;
}

function worstAspectRatio(row: number[], length: number, scale: number): number {
  if (length <= 0) return Number.POSITIVE_INFINITY;
  const total = row.reduce((sum, v) => sum + v, 0) * scale;
  if (total <= 0) return Number.POSITIVE_INFINITY;
  const min = Math.min(...row) * scale;
  const max = Math.max(...row) * scale;
  const side = length * length;
  // The paper's `worst` function: the least square-like tile in this row.
  return Math.max((side * max) / (total * total), (total * total) / (side * min));
}

/**
 * Lay `items` out inside a `width` x `height` box, largest first.
 *
 * Returns one rect per item with a positive value, in layout order. Items are
 * sorted descending internally, so the caller need not pre-sort.
 */
export function squarify<T extends TreemapInput>(
  items: T[],
  width: number,
  height: number,
): TreemapRect<T>[] {
  const positive = items.filter((item) => item.value > 0);
  if (positive.length === 0 || width <= 0 || height <= 0) return [];

  const sorted = [...positive].sort((a, b) => b.value - a.value);
  const total = sorted.reduce((sum, item) => sum + item.value, 0);
  // Map data units onto pixels once, so every row shares one scale.
  const scale = (width * height) / total;

  const out: TreemapRect<T>[] = [];
  let box: Box = { x: 0, y: 0, width, height };
  let index = 0;

  while (index < sorted.length) {
    const first = sorted[index];
    if (first === undefined) break;

    const shortest = Math.min(box.width, box.height);
    const row: T[] = [first];
    let next = index + 1;

    // Grow the row while adding one more makes the tiles *more* square.
    while (next < sorted.length) {
      const candidate = sorted[next];
      if (candidate === undefined) break;

      const current = worstAspectRatio(
        row.map((i) => i.value),
        shortest,
        scale,
      );
      const widened = worstAspectRatio(
        [...row.map((i) => i.value), candidate.value],
        shortest,
        scale,
      );
      if (widened > current) break;
      row.push(candidate);
      next += 1;
    }

    const rowValue = row.reduce((sum, item) => sum + item.value, 0);
    const rowThickness = (rowValue * scale) / shortest;

    // Lay the row along the box's shorter side, then shrink the box.
    let offset = 0;
    for (const item of row) {
      const share = (item.value * scale) / rowThickness;
      if (box.width >= box.height) {
        out.push({
          item,
          x: box.x,
          y: box.y + offset,
          width: rowThickness,
          height: share,
        });
      } else {
        out.push({
          item,
          x: box.x + offset,
          y: box.y,
          width: share,
          height: rowThickness,
        });
      }
      offset += share;
    }

    box =
      box.width >= box.height
        ? {
            x: box.x + rowThickness,
            y: box.y,
            width: box.width - rowThickness,
            height: box.height,
          }
        : {
            x: box.x,
            y: box.y + rowThickness,
            width: box.width,
            height: box.height - rowThickness,
          };

    index = next;
  }

  return out;
}
