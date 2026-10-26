import type { Tone } from "../thresholds";

interface Props {
  label: string;
  value: string;
  tone: Tone;
  hint?: string;
}

export function MetricCard({ label, value, tone, hint }: Props) {
  return (
    <div className={`metric metric--${tone}`}>
      <div className="metric__label">{label}</div>
      <div className="metric__value">{value}</div>
      {hint && <div className="metric__hint">{hint}</div>}
    </div>
  );
}
