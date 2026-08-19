export function DashboardPlaceholder(): JSX.Element {
  return (
    <div className="output-empty-state dashboard-placeholder">
      <span className="output-empty-icon" aria-hidden="true">
        --
      </span>
      <strong>Dashboard is deferred</strong>
      <p>Charts remain available in Results. Dashboard pinning is planned for a later cycle.</p>
    </div>
  );
}
