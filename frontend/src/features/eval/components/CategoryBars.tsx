import type { Tone } from "../thresholds";

export interface Bar {
  category: string;
  value: number;
}

interface Props {
  title: string;
  bars: Bar[];
  max: number;
  min?: number;
  format: (value: number) => string;
  tone: (value: number) => Tone;
}

/** Horizontal bar chart in plain CSS: one row per category. */
export function CategoryBars({ title, bars, max, min = 0, format, tone }: Props) {
  return (
    <figure className="bars">
      <figcaption className="bars__title">{title}</figcaption>
      {bars.map(({ category, value }) => (
        <div key={category} className="bars__row">
          <span className="bars__label">{category}</span>
          <span className="bars__track">
            <span
              className={`bars__fill bars__fill--${tone(value)}`}
              style={{ width: `${(Math.max(value - min, 0) / (max - min)) * 100}%` }}
            />
          </span>
          <span className="bars__value">{format(value)}</span>
        </div>
      ))}
    </figure>
  );
}
