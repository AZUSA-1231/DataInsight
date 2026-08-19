import { ReactNode } from "react";

interface ThreePaneLayoutProps {
  explorer: ReactNode;
  workspace: ReactNode;
  agent: ReactNode;
  output: ReactNode;
}

export function ThreePaneLayout({
  explorer,
  workspace,
  agent,
  output,
}: ThreePaneLayoutProps): JSX.Element {
  return (
    <div className="workspace-layout">
      <aside className="pane explorer-pane" aria-label="Explorer">
        {explorer}
      </aside>
      <main className="pane center-pane">
        <section className="center-workspace">{workspace}</section>
        {output}
      </main>
      <aside className="pane agent-pane" aria-label="Agent panel">
        {agent}
      </aside>
    </div>
  );
}
