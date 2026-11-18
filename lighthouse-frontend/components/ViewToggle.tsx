"use client";

import { useId, type ReactNode } from "react";

import styles from "./ViewToggle.module.css";

/**
 * Which view the table panel is showing.
 *
 * "data"   -> the rows in the lkp_ table
 * "source" -> the DDL / source for that table
 */
export type TableView = "data" | "source";

interface ViewToggleProps {
  /** Currently engaged view. */
  value: TableView;
  /** Called with the newly engaged view. */
  onChange: (value: TableView) => void;
  /** Optional extra class on the outer housing, for sidebar spacing. */
  className?: string;
}

interface Option {
  value: TableView;
  label: string;
  /** Tooltip / screen-reader detail. */
  hint: string;
  icon: ReactNode;
}

function DataIcon() {
  return (
    <svg className={styles.glyph} viewBox="0 0 16 16" aria-hidden="true" focusable="false">
      <rect x="1.75" y="2.75" width="12.5" height="10.5" rx="1.25" />
      <path d="M1.75 6.25h12.5M6.25 6.25v7" />
    </svg>
  );
}

function SourceIcon() {
  return (
    <svg className={styles.glyph} viewBox="0 0 16 16" aria-hidden="true" focusable="false">
      <path d="M5.75 4.25 2.25 8l3.5 3.75M10.25 4.25 13.75 8l-3.5 3.75" />
    </svg>
  );
}

const OPTIONS: Option[] = [
  { value: "data", label: "Data", hint: "Show the table's rows", icon: <DataIcon /> },
  { value: "source", label: "Source", hint: "Show the table's DDL", icon: <SourceIcon /> },
];

/**
 * Cassette-transport style view switch.
 *
 * Two mechanical keys in a recessed housing: pressing one latches it down and
 * releases the other. Built on real radio inputs rather than buttons + state,
 * so arrow-key navigation, focus handling, and screen-reader semantics all come
 * for free and the "only one can be down" rule is enforced by the browser
 * rather than by us.
 *
 * Controlled component -- the parent owns `value`, so this can later be driven
 * by a route param, a query string, or wherever the view state ends up living.
 *
 *   const [view, setView] = useState<TableView>("data");
 *   <ViewToggle value={view} onChange={setView} />
 */
export default function ViewToggle({ value, onChange, className }: ViewToggleProps) {
  // Unique per instance so two toggles on one page don't share a radio group.
  const groupName = useId();

  return (
    <div
      className={[styles.housing, className].filter(Boolean).join(" ")}
      role="radiogroup"
      aria-label="Table view"
    >
      {OPTIONS.map((option) => (
        <label key={option.value} className={styles.key} title={option.hint}>
          <input
            type="radio"
            className={styles.input}
            name={groupName}
            value={option.value}
            checked={value === option.value}
            onChange={() => onChange(option.value)}
          />

          {/* Order matters: every visual state below is driven by the
              `.input:checked + .cap` sibling selector. */}
          <span className={styles.cap}>
            <span className={styles.led} aria-hidden="true" />
            {option.icon}
            <span className={styles.label}>{option.label}</span>
          </span>
        </label>
      ))}
    </div>
  );
}
