import { useState } from "react";

import { DashboardPlaceholder } from "./DashboardPlaceholder";
import { ReportTab } from "./ReportTab";
import { ResultsTab } from "./ResultsTab";

type OutputTab = "results" | "report" | "dashboard";

interface OutputDockProps {
  projectId: string;
  onWorkspaceChanged: () => Promise<void> | void;
}

const TABS: { id: OutputTab; label: string }[] = [
  { id: "results", label: "Results" },
  { id: "report", label: "Report" },
  { id: "dashboard", label: "Dashboard" },
];

export function OutputDock({ projectId, onWorkspaceChanged }: OutputDockProps): JSX.Element {
  const [collapsed, setCollapsed] = useState(false);
  const [tab, setTab] = useState<OutputTab>("results");

  return (
    <section className={`output-dock ${collapsed ? "collapsed" : ""}`} aria-label="Output dock">
      <div className="output-dock-bar">
        <div className="output-tabs" role="tablist" aria-label="Output views">
          {TABS.map((item) => (
            <button
              aria-selected={tab === item.id}
              className={tab === item.id ? "active" : ""}
              role="tab"
              type="button"
              onClick={() => {
                setTab(item.id);
                setCollapsed(false);
              }}
              key={item.id}
            >
              {item.label}
            </button>
          ))}
        </div>
        <button
          aria-expanded={!collapsed}
          className="dock-toggle"
          type="button"
          onClick={() => setCollapsed((current) => !current)}
        >
          {collapsed ? "Open output" : "Collapse"}
        </button>
      </div>
      {!collapsed ? (
        <div className="output-dock-content" role="tabpanel">
          {tab === "results" ? (
            <ResultsTab onWorkspaceChanged={onWorkspaceChanged} projectId={projectId} />
          ) : null}
          {tab === "report" ? (
            <ReportTab onProjectChanged={onWorkspaceChanged} projectId={projectId} />
          ) : null}
          {tab === "dashboard" ? <DashboardPlaceholder /> : null}
        </div>
      ) : null}
    </section>
  );
}
