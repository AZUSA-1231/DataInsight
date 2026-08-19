import { useEffect, useMemo, useState } from "react";

import { WorkspaceUnitPatch } from "../../../api/client";
import { DataCatalog, PublicColumn } from "../../../api/dataApi";
import {
  isDeriveUnit,
  isFilterUnit,
  isJoinUnit,
  isTerminalUnit,
  PlanUnit,
} from "../../../domain/plan";
import { unitToPayload } from "./operationSchemas";

export interface ValidationIssue {
  unitId: number | null;
  field: string | null;
  message: string;
}

export interface DeleteConflict {
  unitId: number;
  dependentUnitIds: number[];
}

interface OperationInspectorProps {
  unit: PlanUnit;
  catalog: DataCatalog | null;
  busy: boolean;
  error: string | null;
  issues: ValidationIssue[];
  deleteConflict: DeleteConflict | null;
  onSave: (payload: WorkspaceUnitPatch) => Promise<void>;
  onDelete: () => Promise<void>;
  onCascadeDelete: () => Promise<void>;
  onCancelDeleteConflict: () => void;
  onClose: () => void;
}

function snapshotNames(catalog: DataCatalog | null, current: string | undefined): string[] {
  const names = catalog?.snapshots.map((snapshot) => snapshot.name) ?? [];
  return current && !names.includes(current) ? [current, ...names] : names;
}

function columnsForSnapshot(
  catalog: DataCatalog | null,
  snapshot: string | undefined,
  current: string[] = [],
): PublicColumn[] {
  const values = catalog?.columns.filter((column) => column.snapshot === snapshot) ?? [];
  const existing = new Set(values.map((column) => column.ref));
  const fallback = current
    .filter((ref) => !existing.has(ref))
    .map((ref) => ({
      name: ref.split(".").pop() ?? ref,
      dtype: null,
      nullCount: null,
      nullPct: null,
      ref,
      snapshot: snapshot ?? ref.split(".")[0] ?? "",
      sourceColumn: null,
      createdByUnitId: null,
      availability: "planned" as const,
    }));
  return [...values, ...fallback];
}

function selectedColumns(value: string[] | undefined): string[] {
  return Array.isArray(value) ? value : [];
}

function joinInputs(value: WorkspaceUnitPatch["inputs"]): { role: "left" | "right"; snapshot: string }[] {
  return Array.isArray(value)
    ? value.map((item) => ({ role: item.role, snapshot: item.snapshot }))
    : [];
}

function joinKeys(value: WorkspaceUnitPatch["keys"]): { left: string; right: string }[] {
  return Array.isArray(value) ? value.map((item) => ({ left: item.left, right: item.right })) : [];
}

function joinSelects(value: WorkspaceUnitPatch["select"]): { from: string; as: string }[] {
  return Array.isArray(value) ? value.map((item) => ({ from: item.from, as: item.as })) : [];
}

function FieldIssue({ issue }: { issue: ValidationIssue | undefined }): JSX.Element | null {
  return issue ? <small className="inspector-field-error">{issue.message}</small> : null;
}

function ColumnSummary({
  values,
  label,
}: {
  values: string[];
  label: string;
}): JSX.Element {
  return (
    <div className="inspector-chip-field" aria-label={label}>
      <div className="inspector-chips">
        {values.map((ref) => (
          <span className="inspector-chip" key={ref} title={ref}>
            {ref}
          </span>
        ))}
        {values.length === 0 ? <span className="inspector-empty-chip">No columns selected</span> : null}
      </div>
      <small className="inspector-help">Drag columns from Explorer into this Unit&apos;s slot to change them.</small>
    </div>
  );
}

function SnapshotSelect({
  label,
  value,
  values,
  onChange,
}: {
  label: string;
  value: string;
  values: string[];
  onChange: (value: string) => void;
}): JSX.Element {
  return (
    <label className="inspector-field">
      <span>{label}</span>
      <select value={value} onChange={(event) => onChange(event.target.value)}>
        <option value="">Select Snapshot...</option>
        {values.map((name) => (
          <option key={name} value={name}>
            {name}
          </option>
        ))}
      </select>
    </label>
  );
}

export function OperationInspector({
  unit,
  catalog,
  busy,
  error,
  issues,
  deleteConflict,
  onSave,
  onDelete,
  onCascadeDelete,
  onCancelDeleteConflict,
  onClose,
}: OperationInspectorProps): JSX.Element {
  const initialDraft = useMemo(() => unitToPayload(unit) ?? {}, [unit]);
  const [draft, setDraft] = useState<WorkspaceUnitPatch>(initialDraft);
  const [templateText, setTemplateText] = useState(() =>
    initialDraft.template_params ? JSON.stringify(initialDraft.template_params, null, 2) : "",
  );
  const [dirty, setDirty] = useState(false);
  const [localError, setLocalError] = useState<string | null>(null);
  const [deleteConfirm, setDeleteConfirm] = useState(false);

  useEffect(() => {
    const nextDraft = unitToPayload(unit) ?? {};
    setDraft(nextDraft);
    setTemplateText(nextDraft.template_params ? JSON.stringify(nextDraft.template_params, null, 2) : "");
    setDirty(false);
    setLocalError(null);
    setDeleteConfirm(false);
  }, [unit]);

  const issueFor = (field: string): ValidationIssue | undefined =>
    issues.find((issue) => issue.field === field || issue.field?.startsWith(`${field}.`));
  const snapshots = snapshotNames(catalog, typeof draft.input_snapshot === "string" ? draft.input_snapshot : undefined);
  const inputSnapshot = typeof draft.input_snapshot === "string" ? draft.input_snapshot : "";
  const inputColumns = selectedColumns(draft.input_columns);

  const setField = <K extends keyof WorkspaceUnitPatch>(field: K, value: WorkspaceUnitPatch[K]): void => {
    setDraft((current) => ({ ...current, [field]: value }));
    setDirty(true);
    setLocalError(null);
  };

  const setInputSnapshot = (snapshot: string): void => {
    const options = columnsForSnapshot(catalog, snapshot);
    setDraft((current) => ({
      ...current,
      input_snapshot: snapshot,
      input_columns: selectedColumns(current.input_columns).filter((ref) => ref.startsWith(`${snapshot}.`)).length
        ? selectedColumns(current.input_columns).filter((ref) => ref.startsWith(`${snapshot}.`))
        : options[0]
          ? [options[0].ref]
          : [],
    }));
    setDirty(true);
  };

  const inputs = joinInputs(draft.inputs);
  const leftSnapshot = inputs.find((input) => input.role === "left")?.snapshot ?? "";
  const rightSnapshot = inputs.find((input) => input.role === "right")?.snapshot ?? "";
  const leftOptions = columnsForSnapshot(catalog, leftSnapshot);
  const rightOptions = columnsForSnapshot(catalog, rightSnapshot);
  const keys = joinKeys(draft.keys);
  const selects = joinSelects(draft.select);
  const joinHow = typeof draft.how === "string" ? draft.how : "left";
  const updateJoinInputs = (role: "left" | "right", snapshot: string): void => {
    const next = [
      { role: "left" as const, snapshot: role === "left" ? snapshot : leftSnapshot },
      { role: "right" as const, snapshot: role === "right" ? snapshot : rightSnapshot },
    ];
    setField("inputs", next);
  };

  const updateJoinHow = (how: string): void => {
    setDraft((current) => ({
      ...current,
      how,
      keys: how === "cross" ? [] : joinKeys(current.keys),
      select:
        how === "semi" || how === "anti"
          ? joinSelects(current.select).filter((selected) => selected.from.startsWith(`${leftSnapshot}.`))
          : joinSelects(current.select),
    }));
    setDirty(true);
  };

  const handleSave = async (): Promise<void> => {
    let templateParams: Record<string, unknown> | null = null;
    if (templateText.trim()) {
      try {
        const parsed: unknown = JSON.parse(templateText);
        if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
          setLocalError("Template parameters must be a JSON object.");
          return;
        }
        templateParams = parsed as Record<string, unknown>;
      } catch {
        setLocalError("Template parameters must contain valid JSON.");
        return;
      }
    }
    setLocalError(null);
    try {
      await onSave({
        ...draft,
        operation: unit.operation,
        purpose: typeof draft.purpose === "string" ? draft.purpose : unit.purpose,
        model: typeof draft.model === "string" && draft.model.trim() ? draft.model.trim() : null,
        execution_mode: draft.execution_mode ?? unit.execution_mode ?? "llm",
        depends_on: Array.isArray(draft.depends_on) ? draft.depends_on : [...unit.depends_on],
        template_name:
          typeof draft.template_name === "string" && draft.template_name.trim()
            ? draft.template_name.trim()
            : null,
        template_params: templateParams,
      });
      setDirty(false);
    } catch {
      // The parent keeps the server-confirmed Plan and exposes its validation issues here.
    }
  };

  const renderInputColumns = (label: string): JSX.Element => (
    <div className="inspector-field inspector-field-wide">
      <span>{label}</span>
      <ColumnSummary
        label={label}
        values={inputColumns}
      />
      <FieldIssue issue={issueFor("input_columns")} />
    </div>
  );

  return (
    <section className="operation-inspector" aria-label={`Edit Unit ${unit.unit_id}`}>
      <div className="inspector-scroll">
        <div className="inspector-heading">
        <div>
          <p className="eyebrow">Unit inspector</p>
          <h2>#{unit.unit_id} {unit.operation.replace("_", " ")}</h2>
        </div>
        <div className="inspector-heading-actions">
          <span className={`inspector-state ${dirty ? "dirty" : "confirmed"}`}>
            {dirty ? "Unsaved changes" : "Server confirmed"}
          </span>
          <button
            aria-label="Close Unit inspector"
            className="icon-button inspector-close-button"
            title="Close inspector"
            type="button"
            onClick={onClose}
          >
            x
          </button>
        </div>
        </div>
        {error ? <div className="inspector-alert" role="alert">{error}</div> : null}
        {localError ? <div className="inspector-alert" role="alert">{localError}</div> : null}
        {issues.length > 0 ? (
          <div className="inspector-issues" role="alert">
            {issues.map((issue, index) => <span key={`${issue.field ?? "issue"}-${index}`}>{issue.message}</span>)}
          </div>
        ) : null}
        <div className="inspector-form">
        <label className="inspector-field inspector-field-wide">
          <span>Purpose</span>
          <input
            value={typeof draft.purpose === "string" ? draft.purpose : ""}
            onChange={(event) => setField("purpose", event.target.value)}
          />
          <FieldIssue issue={issueFor("purpose")} />
        </label>
        <div className="inspector-field-grid">
          <label className="inspector-field">
            <span>Execution mode</span>
            <select
              value={draft.execution_mode ?? "llm"}
              onChange={(event) => setField("execution_mode", event.target.value)}
            >
              <option value="llm">LLM</option>
              <option value="template">Template</option>
            </select>
          </label>
          <label className="inspector-field">
            <span>Model hint</span>
            <input
              value={typeof draft.model === "string" ? draft.model : ""}
              onChange={(event) => setField("model", event.target.value)}
              placeholder="Optional"
            />
          </label>
        </div>
        <label className="inspector-field inspector-field-wide">
          <span>Caution</span>
          <textarea
            rows={2}
            value={typeof draft.cautious === "string" ? draft.cautious : ""}
            onChange={(event) => setField("cautious", event.target.value)}
          />
        </label>

        {isDeriveUnit(unit) ? (
          <div className="inspector-operation-fields">
            <SnapshotSelect label="Input Snapshot" onChange={setInputSnapshot} value={inputSnapshot} values={snapshots} />
            <FieldIssue issue={issueFor("input_snapshot")} />
            {renderInputColumns("Input columns")}
            <label className="inspector-field inspector-field-wide">
              <span>Output column name</span>
              <input
                value={selectedColumns(draft.output_columns)[0] ?? ""}
                onChange={(event) => setField("output_columns", [event.target.value])}
                placeholder={`${inputSnapshot || "snapshot"}.new_column`}
              />
              <small className="inspector-help">Use a qualified name in the input Snapshot, for example orders.revenue.</small>
              <FieldIssue issue={issueFor("output_columns")} />
            </label>
          </div>
        ) : null}

        {isFilterUnit(unit) ? (
          <div className="inspector-operation-fields">
            <SnapshotSelect label="Input Snapshot" onChange={setInputSnapshot} value={inputSnapshot} values={snapshots} />
            <FieldIssue issue={issueFor("input_snapshot")} />
            {renderInputColumns("Predicate columns")}
            <label className="inspector-field inspector-field-wide">
              <span>Output Snapshot name</span>
              <input
                value={typeof draft.output_snapshot === "string" ? draft.output_snapshot : ""}
                onChange={(event) => setField("output_snapshot", event.target.value)}
              />
              <FieldIssue issue={issueFor("output_snapshot")} />
            </label>
          </div>
        ) : null}

        {isTerminalUnit(unit) ? (
          <div className="inspector-operation-fields">
            <SnapshotSelect label="Input Snapshot" onChange={setInputSnapshot} value={inputSnapshot} values={snapshots} />
            <FieldIssue issue={issueFor("input_snapshot")} />
            {renderInputColumns("Analysis columns")}
          </div>
        ) : null}

        {isJoinUnit(unit) ? (
          <div className="inspector-operation-fields">
            <div className="inspector-field-grid">
              <SnapshotSelect
                label="Left Snapshot"
                onChange={(value) => updateJoinInputs("left", value)}
                value={leftSnapshot}
                values={snapshotNames(catalog, leftSnapshot)}
              />
              <SnapshotSelect
                label="Right Snapshot"
                onChange={(value) => updateJoinInputs("right", value)}
                value={rightSnapshot}
                values={snapshotNames(catalog, rightSnapshot)}
              />
            </div>
            <FieldIssue issue={issueFor("inputs")} />
            <label className="inspector-field">
              <span>Join mode</span>
              <select value={joinHow} onChange={(event) => updateJoinHow(event.target.value)}>
                {['left', 'right', 'inner', 'outer', 'cross', 'semi', 'anti'].map((how) => <option key={how} value={how}>{how}</option>)}
              </select>
              {joinHow === "cross" ? <small className="inspector-help">Cross joins do not use key pairs.</small> : null}
              {joinHow === "semi" || joinHow === "anti" ? <small className="inspector-help">{joinHow} joins select columns only from the left Snapshot.</small> : null}
              <FieldIssue issue={issueFor("how")} />
            </label>
            <div className="inspector-field inspector-field-wide">
              <span>Key pairs</span>
              <div className="join-pair-list">
                {keys.map((key, index) => (
                  <div className="join-pair" key={`${index}-${key.left}-${key.right}`}>
                    <span className="join-readonly-column" title={key.left}>{key.left || "Left key..."}</span>
                    <span aria-hidden="true">↔</span>
                    <span className="join-readonly-column" title={key.right}>{key.right || "Right key..."}</span>
                    <button aria-label={`Remove key pair ${index + 1}`} title="Remove key pair" type="button" onClick={() => setField("keys", keys.filter((_, itemIndex) => itemIndex !== index))}>×</button>
                  </div>
                ))}
              </div>
              <button
                className="inspector-add-button"
                disabled={draft.how === "cross" || leftOptions.length === 0 || rightOptions.length === 0}
                type="button"
                onClick={() => setField("keys", [...keys, { left: leftOptions[0]?.ref ?? "", right: rightOptions[0]?.ref ?? "" }])}
              >
                + Add key pair
              </button>
              <FieldIssue issue={issueFor("keys")} />
            </div>
            <div className="inspector-field inspector-field-wide">
              <span>Selected outputs</span>
              <div className="join-select-list">
                {selects.map((selected, index) => (
                  <div className="join-select-row" key={`${index}-${selected.from}`}>
                    <span className="join-readonly-column" title={selected.from}>{selected.from || "Column..."}</span>
                    <input
                      aria-label={`Alias for selected output ${index + 1}`}
                      value={selected.as}
                      onChange={(event) => setField("select", selects.map((item, itemIndex) => itemIndex === index ? { ...item, as: event.target.value } : item))}
                      placeholder="Output alias"
                    />
                  </div>
                ))}
              </div>
              <small className="inspector-help">Drag columns into the Selected outputs slot on the Unit.</small>
              <FieldIssue issue={issueFor("select")} />
            </div>
            <label className="inspector-field inspector-field-wide">
              <span>Output Snapshot name</span>
              <input
                value={typeof draft.output_snapshot === "string" ? draft.output_snapshot : ""}
                onChange={(event) => setField("output_snapshot", event.target.value)}
              />
              <FieldIssue issue={issueFor("output_snapshot")} />
            </label>
          </div>
        ) : null}

        <div className="inspector-template-fields">
          <label className="inspector-field">
            <span>Template name</span>
            <input
              value={typeof draft.template_name === "string" ? draft.template_name : ""}
              onChange={(event) => setField("template_name", event.target.value)}
              placeholder="Optional"
            />
          </label>
          <label className="inspector-field inspector-field-wide">
            <span>Template parameters (JSON)</span>
            <textarea
              rows={2}
              value={templateText}
              onChange={(event) => {
                setTemplateText(event.target.value);
                setDirty(true);
              }}
              placeholder='{"key": "value"}'
            />
          </label>
        </div>
        </div>
      </div>
      <div className="inspector-actions">
        <button className="primary-button" disabled={busy || !dirty} type="button" onClick={() => void handleSave()}>
          {busy ? "Saving..." : "Save Unit"}
        </button>
        <div className="inspector-delete-action">
          {deleteConflict ? (
            <div className="delete-conflict" role="alert">
              <span>Unit #{deleteConflict.unitId} has downstream Units: {deleteConflict.dependentUnitIds.join(", ")}.</span>
              <button className="danger-button" disabled={busy} type="button" onClick={() => void onCascadeDelete()}>Delete cascade</button>
              <button className="small-button" disabled={busy} type="button" onClick={onCancelDeleteConflict}>Keep Units</button>
            </div>
          ) : deleteConfirm ? (
            <div className="delete-confirm">
              <span>Delete Unit #{unit.unit_id}?</span>
              <button className="danger-button" disabled={busy} type="button" onClick={() => void onDelete()}>Confirm delete</button>
              <button className="small-button" disabled={busy} type="button" onClick={() => setDeleteConfirm(false)}>Cancel</button>
            </div>
          ) : (
            <button className="danger-outline-button" disabled={busy} type="button" onClick={() => setDeleteConfirm(true)}>Delete Unit</button>
          )}
        </div>
      </div>
    </section>
  );
}
