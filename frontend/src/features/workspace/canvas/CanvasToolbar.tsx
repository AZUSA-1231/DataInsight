export type CanvasSaveState = "saved" | "saving" | "rejected";

interface CanvasToolbarProps {
  zoom: number;
  saveState: CanvasSaveState;
  semanticBusy: boolean;
  onZoomOut: () => void;
  onZoomIn: () => void;
  onFitView: () => void;
}

function saveLabel(saveState: CanvasSaveState): string {
  switch (saveState) {
    case "saving":
      return "Saving layout";
    case "rejected":
      return "Layout rejected";
    default:
      return "Layout saved";
  }
}

export function CanvasToolbar({
  zoom,
  saveState,
  semanticBusy,
  onZoomOut,
  onZoomIn,
  onFitView,
}: CanvasToolbarProps): JSX.Element {
  return (
    <div className="plan-canvas-toolbar" aria-label="Plan Canvas controls">
      <div className="canvas-toolbar-actions">
        <button aria-label="Zoom out" title="Zoom out" type="button" onClick={onZoomOut}>
          -
        </button>
        <span>{Math.round(zoom * 100)}%</span>
        <button aria-label="Zoom in" title="Zoom in" type="button" onClick={onZoomIn}>
          +
        </button>
        <button className="fit-view-button" type="button" onClick={onFitView}>
          Fit view
        </button>
      </div>
      <div className="canvas-toolbar-status" aria-live="polite">
        <span className={`canvas-save-dot ${saveState}`} />
        <span>{semanticBusy ? "Updating Plan" : saveLabel(saveState)}</span>
      </div>
    </div>
  );
}
