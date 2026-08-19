import { DataCatalog } from "../../api/dataApi";
import { OperationKind } from "../workspace/operations/operationSchemas";

interface OperationPaletteProps {
  catalog: DataCatalog;
  onCreate: (operation: OperationKind) => void;
}

const OPERATIONS: Array<{
  operation: OperationKind;
  label: string;
  description: string;
  symbol: string;
}> = [
  { operation: "derive_column", label: "Derive", description: "Add a declared column", symbol: "D" },
  { operation: "filter", label: "Filter", description: "Create a Snapshot subset", symbol: "F" },
  { operation: "join", label: "Join", description: "Combine two Snapshots", symbol: "J" },
  { operation: "terminal", label: "Terminal", description: "Produce analysis evidence", symbol: "T" },
];

function operationEnabled(operation: OperationKind, catalog: DataCatalog): boolean {
  if (operation === "join") {
    return catalog.snapshots.length >= 2 && catalog.columns.length >= 2;
  }
  return catalog.snapshots.length > 0 && catalog.columns.length > 0;
}

export function OperationPalette({ catalog, onCreate }: OperationPaletteProps): JSX.Element {
  return (
    <div className="operation-palette" aria-label="Operation palette">
      {OPERATIONS.map((item) => {
        const enabled = operationEnabled(item.operation, catalog);
        return (
          <button
          className={`operation-palette-item ${enabled ? "" : "disabled"}`}
          disabled={!enabled}
            key={item.operation}
            title={enabled ? `Create a ${item.label} Unit` : "Upload compatible data first"}
            type="button"
            onClick={() => onCreate(item.operation)}
          >
            <span className={`operation-icon operation-${item.operation}`} aria-hidden="true">
              {item.symbol}
            </span>
            <span>
              <strong>{item.label}</strong>
              <small>{item.description}</small>
            </span>
          </button>
        );
      })}
    </div>
  );
}
