interface ExplorerPlaceholderProps {
  sourceCount: number;
  hasData: boolean;
}

export function ExplorerPlaceholder({
  sourceCount,
  hasData,
}: ExplorerPlaceholderProps): JSX.Element {
  return (
    <div className="placeholder-panel explorer-placeholder">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">Explorer</p>
          <h2>Sources</h2>
        </div>
        <span className="count-badge">{sourceCount}</span>
      </div>
      <button className="upload-placeholder" type="button" disabled>
        <span className="upload-placeholder-icon" aria-hidden="true">
          ↑
        </span>
        <span>
          <strong>Upload data</strong>
          <small>CSV and Excel ingestion arrives in M4</small>
        </span>
      </button>
      <div className="placeholder-tree">
        {hasData ? (
          <div className="tree-row active">
            <span className="tree-icon" aria-hidden="true">
              ◈
            </span>
            <span>Project sources</span>
          </div>
        ) : (
          <p className="muted-copy">No Sources in this Project yet.</p>
        )}
      </div>
      <div className="explorer-divider" />
      <div className="panel-heading compact">
        <div>
          <p className="eyebrow">Operations</p>
          <h2>Palette</h2>
        </div>
      </div>
      <div className="operation-palette" aria-label="Operation palette">
        {[
          ["derive_column", "Derive", "Add a declared column"],
          ["filter", "Filter", "Create a Snapshot subset"],
          ["join", "Join", "Combine two Snapshots"],
          ["terminal", "Terminal", "Produce evidence"],
        ].map(([kind, label, description]) => (
          <div className="operation-palette-item" key={kind}>
            <span className={`operation-icon operation-${kind}`} aria-hidden="true">
              {kind === "terminal" ? "◆" : kind === "join" ? "⇄" : kind === "filter" ? "⌁" : "＋"}
            </span>
            <span>
              <strong>{label}</strong>
              <small>{description}</small>
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
