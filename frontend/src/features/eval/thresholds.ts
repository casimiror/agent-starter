// Colour bands from the RAG course evaluator.
export type Tone = "good" | "warn" | "bad";

/** Ratios 0..1 (MRR, nDCG, coverage, pass rate): green >= 0.9, amber >= 0.75. */
export function ratioTone(value: number): Tone {
  return value >= 0.9 ? "good" : value >= 0.75 ? "warn" : "bad";
}

/** Judge scores 1..5: green >= 4.5, amber >= 4.0. */
export function scoreTone(value: number): Tone {
  return value >= 4.5 ? "good" : value >= 4 ? "warn" : "bad";
}

export const percent = (value: number) => `${(value * 100).toFixed(0)}%`;
export const ratio = (value: number) => value.toFixed(2);
export const score = (value: number) => `${value.toFixed(2)}/5`;
