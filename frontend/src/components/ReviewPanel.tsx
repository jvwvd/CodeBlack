/**
 * Reviewer correction form for a NEEDS_REVIEW email.
 *
 * The reviewer edits the extracted SI/BL values and saves; the backend
 * re-verifies with pipeline.compare / pipeline.reliability and returns the
 * new record. This component never computes a status, a defect list or a
 * review reason — it renders whatever came back.
 *
 * Per backend/models.py, `si` and `bl` are WHOLE-SIDE replacements: a side
 * that is sent replaces the stored side entirely, and a side that is omitted
 * is left untouched. So only a side the reviewer actually edited is sent.
 */
import { useMemo, useState } from "react";

import { FIELD_KEYS, type EmailRecord, type FieldKey, type ReviewCorrectionRequest, type ShipmentFields } from "../types";
import { FIELD_LABELS } from "./labels";
import { useSubmitReview } from "./queries";
import { useToast } from "./Toast";
import { Button, ErrorState, Panel } from "./ui";

type SideDraft = Record<FieldKey, string>;

const NUMERIC_KEYS: FieldKey[] = ["container_count", "gross_weight_kg"];

function toDraft(side: ShipmentFields | null): SideDraft {
  const draft = {} as SideDraft;
  for (const key of FIELD_KEYS) {
    const value = side ? side[key] : null;
    draft[key] = value === null || value === undefined ? "" : String(value);
  }
  return draft;
}

/** Input validation only — this decides nothing about the documents. */
function validate(draft: SideDraft): Partial<Record<FieldKey, string>> {
  const errors: Partial<Record<FieldKey, string>> = {};
  const count = draft.container_count.trim();
  if (count && !/^\d+$/.test(count)) {
    errors.container_count = "Enter a whole number of containers, or leave it empty.";
  }
  const weight = draft.gross_weight_kg.trim();
  if (weight && !Number.isFinite(Number(weight))) {
    errors.gross_weight_kg = "Enter a number in kilograms, or leave it empty.";
  }
  return errors;
}

function toShipmentFields(draft: SideDraft): ShipmentFields {
  const built = {} as ShipmentFields;
  for (const key of FIELD_KEYS) {
    const raw = draft[key].trim();
    if (key === "container_count") {
      built.container_count = raw === "" ? null : Number.parseInt(raw, 10);
    } else if (key === "gross_weight_kg") {
      built.gross_weight_kg = raw === "" ? null : Number(raw);
    } else {
      built[key] = raw === "" ? null : raw;
    }
  }
  return built;
}

function SideEditor({
  heading,
  draft,
  errors,
  onChange,
  disabled,
  idPrefix,
}: {
  heading: string;
  draft: SideDraft;
  errors: Partial<Record<FieldKey, string>>;
  onChange: (key: FieldKey, value: string) => void;
  disabled: boolean;
  idPrefix: string;
}) {
  return (
    <div>
      <h3 className="mb-3 text-sm font-semibold">{heading}</h3>
      <div className="flex flex-col gap-3">
        {FIELD_KEYS.map((key) => {
          const id = `${idPrefix}-${key}`;
          const error = errors[key];
          const numeric = NUMERIC_KEYS.includes(key);
          return (
            <div key={key}>
              <label className="field-label" htmlFor={id}>
                {FIELD_LABELS[key]}
              </label>
              {key === "shipper" || key === "consignee" || key === "notify_party" ? (
                <textarea
                  id={id}
                  className="control min-h-[4.5rem] resize-y"
                  value={draft[key]}
                  disabled={disabled}
                  onChange={(event) => onChange(key, event.target.value)}
                />
              ) : (
                <input
                  id={id}
                  type={numeric ? "text" : "text"}
                  inputMode={numeric ? "decimal" : undefined}
                  className="control"
                  value={draft[key]}
                  disabled={disabled}
                  aria-invalid={error ? true : undefined}
                  aria-describedby={error ? `${id}-error` : undefined}
                  onChange={(event) => onChange(key, event.target.value)}
                />
              )}
              {error ? (
                <p id={`${id}-error`} className="mt-1 text-2xs text-danger">
                  {error}
                </p>
              ) : null}
            </div>
          );
        })}
      </div>
    </div>
  );
}

export function ReviewPanel({ record }: { record: EmailRecord }) {
  const toast = useToast();
  const submit = useSubmitReview(record.email_id);

  const initialSi = useMemo(() => toDraft(record.si), [record.si]);
  const initialBl = useMemo(() => toDraft(record.bl), [record.bl]);

  const [si, setSi] = useState<SideDraft>(initialSi);
  const [bl, setBl] = useState<SideDraft>(initialBl);
  const [notes, setNotes] = useState(record.reviewer_notes ?? "");

  const siErrors = validate(si);
  const blErrors = validate(bl);
  const hasErrors = Object.keys(siErrors).length > 0 || Object.keys(blErrors).length > 0;

  const siChanged = FIELD_KEYS.some((key) => si[key] !== initialSi[key]);
  const blChanged = FIELD_KEYS.some((key) => bl[key] !== initialBl[key]);
  const notesChanged = notes !== (record.reviewer_notes ?? "");
  const nothingToSend = !siChanged && !blChanged && !notesChanged;

  const save = async () => {
    const body: ReviewCorrectionRequest = {};
    if (siChanged) body.si = toShipmentFields(si);
    if (blChanged) body.bl = toShipmentFields(bl);
    if (notesChanged) body.reviewer_notes = notes;

    try {
      await submit.mutateAsync(body);
      toast.success("Review saved");
    } catch {
      toast.error("The review could not be saved.");
    }
  };

  return (
    <Panel
      title="Review this email"
      description="Correct the extracted values, then let the backend check them again."
    >
      <div className="grid gap-6 md:grid-cols-2">
        <SideEditor
          heading="SI (reference)"
          draft={si}
          errors={siErrors}
          disabled={submit.isPending}
          idPrefix="review-si"
          onChange={(key, value) => setSi((current) => ({ ...current, [key]: value }))}
        />
        <SideEditor
          heading="BL (draft)"
          draft={bl}
          errors={blErrors}
          disabled={submit.isPending}
          idPrefix="review-bl"
          onChange={(key, value) => setBl((current) => ({ ...current, [key]: value }))}
        />
      </div>

      <div className="mt-6">
        <label className="field-label" htmlFor="reviewer-notes">
          Reviewer notes
        </label>
        <textarea
          id="reviewer-notes"
          className="control min-h-[5rem] resize-y"
          placeholder="What did you check, and what did you change?"
          value={notes}
          disabled={submit.isPending}
          onChange={(event) => setNotes(event.target.value)}
        />
      </div>

      {submit.isError ? (
        <div className="mt-4">
          <ErrorState title="Could not save the review" message={submit.error.message} />
        </div>
      ) : null}

      <div className="mt-5 flex flex-wrap items-center gap-3">
        <Button
          variant="primary"
          onClick={() => void save()}
          busy={submit.isPending}
          disabled={hasErrors || nothingToSend}
        >
          Save and re-check
        </Button>
        <p className="text-xs text-muted">
          {hasErrors
            ? "Fix the highlighted fields first."
            : nothingToSend
              ? "Change a value or add a note to save."
              : "The backend re-checks the documents and returns the new result."}
        </p>
      </div>

      <p className="mt-3 text-2xs text-muted">
        An empty field is saved as no value. Leaving a side untouched keeps whatever the pipeline
        extracted for it.
      </p>
    </Panel>
  );
}
