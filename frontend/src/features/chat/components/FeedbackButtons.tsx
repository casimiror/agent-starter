import type { Rating } from "../types";

interface Props {
  rating: Rating | null;
  onRate: (rating: Rating | null) => void;
}

const OPTIONS: { value: Rating; label: string; path: string }[] = [
  {
    value: "up",
    label: "Helpful",
    path: "M7 10v11H3V10h4Zm2 11V9.5l4.6-7.2a1.6 1.6 0 0 1 2.9 1.2L15.4 9H20a2 2 0 0 1 2 2.3l-1.4 8A2 2 0 0 1 18.6 21H9Z",
  },
  {
    value: "down",
    label: "Not helpful",
    path: "M17 14V3h4v11h-4Zm-2-11v11.5l-4.6 7.2a1.6 1.6 0 0 1-2.9-1.2L8.6 15H4a2 2 0 0 1-2-2.3l1.4-8A2 2 0 0 1 5.4 3H15Z",
  },
];

/** 👍/👎 under a reply. Clicking the active thumb removes the vote. */
export function FeedbackButtons({ rating, onRate }: Props) {
  return (
    <div className="feedback" role="group" aria-label="Rate this answer">
      {OPTIONS.map(({ value, label, path }) => {
        const active = rating === value;
        return (
          <button
            key={value}
            type="button"
            className={`feedback__button${active ? " feedback__button--active" : ""}`}
            aria-label={label}
            aria-pressed={active}
            title={label}
            onClick={() => onRate(active ? null : value)}
          >
            <svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true">
              <path d={path} />
            </svg>
          </button>
        );
      })}
    </div>
  );
}
