/**
 * SI vs BL comparison table — the one bold element in the product.
 *
 * Rows are highlighted ONLY when their key appears in `defect_fields`, which
 * the backend produced. This component never compares the two values: the
 * backend normalises before comparing ("ABC CO., LTD" equals "ABC CO LTD"),
 * so two strings that look different on screen may legitimately be a match
 * (PROJECT_RULES.md §8 — comparison is pipeline/compare.py's job alone).
 */
import { AlertTriangle, Check } from "lucide-react";

import { FIELD_KEYS, type EmailRecord, type FieldKey, type ShipmentFields } from "../types";
import { formatFieldValue, NOT_FOUND_TEXT } from "./format";
import { FIELD_LABELS } from "./labels";

function valueOf(side: ShipmentFields | null, key: FieldKey): string | number | null {
  if (!side) return null;
  return side[key];
}

function Cell({
  side,
  fieldKey,
  strong,
}: {
  side: ShipmentFields | null;
  fieldKey: FieldKey;
  strong: boolean;
}) {
  const raw = valueOf(side, fieldKey);
  const text = formatFieldValue(fieldKey, raw);
  const missing = text === NOT_FOUND_TEXT;

  return (
    <td
      className={`px-3 py-3 align-top text-sm break-words whitespace-pre-line ${
        missing ? "text-muted italic" : strong ? "font-semibold text-text" : "text-text"
      }`}
    >
      {text}
    </td>
  );
}

export function ComparisonView({ record }: { record: EmailRecord }) {
  const defects = new Set(record.defect_fields ?? []);
  // NEEDS_REVIEW means verification did not complete, so the backend made no
  // per-field finding. Claiming "Matches" would be inventing a verdict.
  const showCheckColumn = record.status !== "NEEDS_REVIEW";

  return (
    <section className="panel overflow-hidden">
      <header className="border-b border-line px-4 py-3 sm:px-5">
        <h2 className="text-md font-semibold">Document comparison</h2>
        <p className="text-xs text-muted">
          The shipping instruction is the reference; the draft bill of lading is checked against it.
        </p>
      </header>

      {/* Scrolls inside its own container so the page never moves sideways. */}
      <div className="overflow-x-auto">
        <table className="w-full min-w-[39rem] border-collapse text-left">
          <thead>
            <tr className="bg-canvas text-xs text-muted">
              <th scope="col" className="w-36 px-3 py-2.5 font-medium">Field</th>
              <th scope="col" className="px-4 py-2.5 font-medium">SI (reference)</th>
              <th scope="col" className="px-4 py-2.5 font-medium">BL (draft)</th>
              <th scope="col" className="w-24 px-3 py-2.5 font-medium">Check</th>
            </tr>
          </thead>
          <tbody>
            {FIELD_KEYS.map((key) => {
              const differs = defects.has(key);
              return (
                <tr
                  key={key}
                  className={`border-t border-line ${
                    differs ? "border-l-4 border-l-danger bg-danger-tint" : ""
                  }`}
                >
                  <th
                    scope="row"
                    className={`px-3 py-3 align-top text-sm font-medium ${
                      differs ? "text-danger" : "text-muted"
                    }`}
                  >
                    {FIELD_LABELS[key]}
                  </th>
                  <Cell side={record.si} fieldKey={key} strong={differs} />
                  <Cell side={record.bl} fieldKey={key} strong={differs} />
                  <td className="px-3 py-3 align-top">
                    {!showCheckColumn ? null : differs ? (
                      <span className="inline-flex items-center gap-1.5 rounded-full border border-danger-line bg-surface px-2 py-0.5 text-2xs font-semibold text-danger whitespace-nowrap">
                        <AlertTriangle aria-hidden className="size-3.5" />
                        Differs
                      </span>
                    ) : (
                      <span className="inline-flex items-center gap-1.5 text-2xs text-muted whitespace-nowrap">
                        <Check aria-hidden className="size-3.5" />
                        Matches
                      </span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {!showCheckColumn ? (
        <p className="border-t border-line bg-canvas px-4 py-2.5 text-xs text-muted sm:px-5">
          The backend did not complete this comparison, so no field is marked as matching. The values
          shown are whatever it managed to read.
        </p>
      ) : null}
    </section>
  );
}
