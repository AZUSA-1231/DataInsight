import {
  Background,
  BackgroundVariant,
  ConnectionLineType,
  MiniMap,
  ReactFlow,
  ReactFlowProvider,
  useReactFlow,
} from "@xyflow/react";
import type { Connection, Edge, NodeChange, OnNodeDrag } from "@xyflow/react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import "@xyflow/react/dist/style.css";

import {
  createWorkspaceUnit,
  deleteWorkspaceUnit,
  getWorkspace,
  updateWorkspaceUnit,
  WorkspaceUnitPatch,
} from "../../../api/client";
import { DataCatalog } from "../../../api/dataApi";
import { Plan, WorkspaceLayout } from "../../../domain/plan";
import { ApiError } from "../../../domain/types";
import { getWorkspaceLayout, putWorkspaceLayout } from "../layoutApi";
import {
  DeleteConflict,
  OperationInspector,
  ValidationIssue,
} from "../operations/OperationInspector";
import {
  buildInitialUnitPayload,
  OperationKind,
} from "../operations/operationSchemas";
import {
  ColumnDropSlot,
  DragPayload,
  parseDragPayload,
  QualifiedColumnDrag,
  resolveColumnDrop,
  resolveColumnRemove,
  resolveEmptyCanvasDrop,
} from "../operations/dropIntents";
import { CanvasSaveState, CanvasToolbar } from "./CanvasToolbar";
import {
  isValidWorkspaceLayout,
  layoutWithNodePosition,
  layoutWithPositions,
} from "./layoutPersistence";
import { OperationNode } from "./OperationNode";
import {
  CANVAS_NODE_WIDTH,
  PlanCanvasNode,
  PlanCanvasNodeData,
  toPlanCanvas,
} from "./planMapper";

type LoadPhase = "loading" | "ready" | "error";

interface ActiveLayoutWrite {
  controller: AbortController;
  generation: number;
  layout: WorkspaceLayout;
  revision: number;
  sequence: number;
}

interface PendingLayoutWrite {
  layout: WorkspaceLayout;
  revision: number;
}

const EMPTY_LAYOUT: WorkspaceLayout = {
  version: 1,
  viewport: { x: 0, y: 0, zoom: 1 },
  nodes: [],
};

const nodeTypes = { operation: OperationNode };

function errorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (typeof error.detail === "object" && error.detail !== null) {
      const detail = error.detail as Record<string, unknown>;
      if (typeof detail.message === "string") {
        return typeof detail.code === "string"
          ? `${detail.message} (${detail.code})`
          : detail.message;
      }
    }
    return error.message;
  }
  return error instanceof Error ? error.message : "The Plan Canvas request failed.";
}

function unitIdFromNodeId(nodeId: string): number | null {
  const match = /^unit:(\d+)$/.exec(nodeId);
  if (!match) {
    return null;
  }
  const unitId = Number(match[1]);
  return Number.isSafeInteger(unitId) && unitId > 0 ? unitId : null;
}

function validationIssues(error: unknown): ValidationIssue[] {
  if (!(error instanceof ApiError) || typeof error.detail !== "object" || error.detail === null) {
    return [];
  }
  const detail = error.detail as Record<string, unknown>;
  if (!Array.isArray(detail.issues)) {
    return [];
  }
  return detail.issues.flatMap((value) => {
    if (typeof value !== "object" || value === null) {
      return [];
    }
    const issue = value as Record<string, unknown>;
    return [{
      unitId: typeof issue.unit_id === "number" ? issue.unit_id : null,
      field: typeof issue.field === "string" ? issue.field : null,
      message: typeof issue.message === "string" ? issue.message : "Plan validation failed",
    }];
  });
}

function downstreamUnitIds(error: unknown): number[] {
  if (!(error instanceof ApiError) || typeof error.detail !== "object" || error.detail === null) {
    return [];
  }
  const detail = error.detail as Record<string, unknown>;
  return Array.isArray(detail.dependent_unit_ids)
    ? detail.dependent_unit_ids.filter(
        (value): value is number => typeof value === "number" && Number.isInteger(value) && value > 0,
      )
    : [];
}

function newUnitId(previous: Plan | null, next: Plan | null): number | null {
  if (!next) {
    return null;
  }
  const previousIds = new Set(previous?.units.map((unit) => unit.unit_id) ?? []);
  return next.units.find((unit) => !previousIds.has(unit.unit_id))?.unit_id ?? null;
}

interface CanvasViewportProps {
  nodes: PlanCanvasNode[];
  edges: Edge[];
  layout: WorkspaceLayout;
  selectedUnitId: number | null;
  inspector: JSX.Element | null;
  onNodesChange: (changes: NodeChange[]) => void;
  onNodeDragStop: OnNodeDrag<PlanCanvasNode>;
  onConnect: (connection: Connection) => void;
  onEdgesDelete: (edges: Edge[]) => void;
  onToggleUnit: (unitId: number) => void;
  onDropColumn: (unitId: number, slot: ColumnDropSlot, payload: QualifiedColumnDrag) => void;
  onRemoveColumn: (unitId: number, slot: ColumnDropSlot, ref: string) => void;
  onCanvasDrop: (payload: DragPayload) => void;
  onSelectUnit: (unitId: number | null) => void;
  saveState: CanvasSaveState;
  semanticBusy: boolean;
  empty: boolean;
}

function CanvasViewport({
  nodes,
  edges,
  layout,
  selectedUnitId,
  inspector,
  onNodesChange,
  onNodeDragStop,
  onConnect,
  onEdgesDelete,
  onToggleUnit,
  onDropColumn,
  onRemoveColumn,
  onCanvasDrop,
  onSelectUnit,
  saveState,
  semanticBusy,
  empty,
}: CanvasViewportProps): JSX.Element {
  const canvasRef = useRef<HTMLDivElement>(null);
  const [canvasWidth, setCanvasWidth] = useState(0);
  useEffect(() => {
    const element = canvasRef.current;
    if (!element) {
      return;
    }
    const updateWidth = (): void => setCanvasWidth(element.clientWidth);
    updateWidth();
    if (typeof ResizeObserver === "undefined") {
      return;
    }
    const observer = new ResizeObserver(updateWidth);
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  const inspectorPosition = useMemo<"left" | "right">(() => {
    const selectedNode = nodes.find((node) => node.data.unit.unit_id === selectedUnitId);
    if (!selectedNode || !inspector) {
      return "right";
    }
    const nodeRight = layout.viewport.x + (selectedNode.position.x + CANVAS_NODE_WIDTH) * layout.viewport.zoom;
    const availableWidth = canvasWidth > 0 ? canvasWidth : 760;
    return nodeRight + 380 > availableWidth - 18 ? "left" : "right";
  }, [canvasWidth, inspector, layout.viewport, nodes, selectedUnitId]);
  const decoratedNodes = useMemo(
    () =>
      nodes.map((node) => ({
        ...node,
        selected: node.data.unit.unit_id === selectedUnitId,
        data: {
          ...node.data,
          onToggle: onToggleUnit,
          onDropColumn,
          onRemoveColumn,
          inspector: node.data.unit.unit_id === selectedUnitId ? inspector : null,
          inspectorPosition,
        },
      })),
    [inspector, inspectorPosition, nodes, onDropColumn, onRemoveColumn, onToggleUnit, selectedUnitId],
  );
  const reactFlow = useReactFlow<PlanCanvasNode, Edge>();

  const handleCanvasDrop = (event: React.DragEvent<HTMLDivElement>): void => {
    event.preventDefault();
    const payload = parseDragPayload(
      event.dataTransfer.getData("application/x-datainsight") || event.dataTransfer.getData("text/plain"),
    );
    if (!payload) {
      return;
    }
    onCanvasDrop(payload);
  };

  return (
    <div
      className="plan-canvas-viewport"
      ref={canvasRef}
      onDragOver={(event) => {
        event.preventDefault();
        event.dataTransfer.dropEffect = "copy";
      }}
      onDrop={handleCanvasDrop}
    >
      <CanvasToolbar
        onFitView={() => reactFlow.fitView({ padding: 0.2, duration: 180 })}
        onZoomIn={() => reactFlow.zoomIn({ duration: 160 })}
        onZoomOut={() => reactFlow.zoomOut({ duration: 160 })}
        saveState={saveState}
        semanticBusy={semanticBusy}
        zoom={layout.viewport.zoom}
      />
      <ReactFlow
        connectionLineType={ConnectionLineType.SmoothStep}
        defaultViewport={layout.viewport}
        deleteKeyCode={["Backspace", "Delete"]}
        edges={edges}
        fitView={false}
        maxZoom={4}
        minZoom={0.25}
        nodeTypes={nodeTypes}
        nodes={decoratedNodes}
        onConnect={onConnect}
        onEdgesDelete={onEdgesDelete}
        onNodeClick={(_, node) => onSelectUnit(node.data.unit.unit_id)}
        onNodeDragStop={onNodeDragStop}
        onNodesChange={onNodesChange}
        onPaneClick={() => onSelectUnit(null)}
        panOnDrag
        proOptions={{ hideAttribution: true }}
        zoomOnDoubleClick={false}
      >
        <Background color="#d7deea" gap={24} size={1} variant={BackgroundVariant.Lines} />
        <MiniMap
          className="plan-canvas-minimap"
          nodeColor={(node) => (node.data as PlanCanvasNodeData).readOnly ? "#c6ccd8" : "#5b5bd6"}
          pannable
          zoomable
        />
      </ReactFlow>
      {empty ? (
        <div className="canvas-empty-overlay">
          <div className="canvas-orbit">
            <span />
            <span />
            <span />
          </div>
          <h2>Drop an operation to start</h2>
          <p>Choose an operation in Explorer, then drop columns into its Unit slots.</p>
        </div>
      ) : null}
    </div>
  );
}

export interface PlanCanvasProps {
  projectId: string;
  refreshKey?: number;
  catalog: DataCatalog | null;
  requestedOperation: OperationKind | null;
  onRequestedOperationHandled: () => void;
  onPlanChanged?: () => void;
}

export function PlanCanvas({
  projectId,
  refreshKey = 0,
  catalog,
  requestedOperation,
  onRequestedOperationHandled,
  onPlanChanged,
}: PlanCanvasProps): JSX.Element {
  const [plan, setPlan] = useState<Plan | null>(null);
  const [layout, setLayout] = useState<WorkspaceLayout>(EMPTY_LAYOUT);
  const [phase, setPhase] = useState<LoadPhase>("loading");
  const [error, setError] = useState<string | null>(null);
  const [selectedUnitId, setSelectedUnitId] = useState<number | null>(null);
  const [saveState, setSaveState] = useState<CanvasSaveState>("saved");
  const [semanticBusy, setSemanticBusy] = useState(false);
  const [semanticError, setSemanticError] = useState<string | null>(null);
  const [validationErrorIssues, setValidationErrorIssues] = useState<ValidationIssue[]>([]);
  const [deleteConflict, setDeleteConflict] = useState<DeleteConflict | null>(null);
  const layoutRef = useRef(layout);
  const confirmedLayoutRef = useRef(layout);
  const loadGeneration = useRef(0);
  const layoutRevision = useRef(0);
  const layoutWriteQueue = useRef<PendingLayoutWrite | null>(null);
  const layoutWriteInFlight = useRef<ActiveLayoutWrite | null>(null);
  const layoutWriteSequence = useRef(0);
  const semanticController = useRef<AbortController | null>(null);
  const semanticBusyRef = useRef(false);
  const planRef = useRef(plan);

  useEffect(() => {
    layoutRef.current = layout;
  }, [layout]);

  useEffect(() => {
    planRef.current = plan;
  }, [plan]);

  const rejectLayout = useCallback((message: string): void => {
    setSaveState("rejected");
    setError(message);
  }, []);

  const flushLayoutWrite = useCallback((): void => {
    if (layoutWriteInFlight.current !== null || layoutWriteQueue.current === null) {
      return;
    }
    const nextWrite = layoutWriteQueue.current;
    layoutWriteQueue.current = null;
    const controller = new AbortController();
    const generation = loadGeneration.current;
    const sequence = layoutWriteSequence.current + 1;
    layoutWriteSequence.current = sequence;
    layoutWriteInFlight.current = {
      controller,
      generation,
      layout: nextWrite.layout,
      revision: nextWrite.revision,
      sequence,
    };

    void putWorkspaceLayout(projectId, nextWrite.layout, controller.signal)
      .then((savedLayout) => {
        if (controller.signal.aborted || generation !== loadGeneration.current) {
          return;
        }
        if (!isValidWorkspaceLayout(savedLayout)) {
          if (
            nextWrite.revision === layoutRevision.current
            && layoutWriteQueue.current === null
          ) {
            rejectLayout("Layout could not be saved: the server returned an invalid layout.");
          }
          return;
        }
        confirmedLayoutRef.current = savedLayout;
        if (
          nextWrite.revision === layoutRevision.current
          && layoutWriteQueue.current === null
        ) {
          setSaveState("saved");
        }
      })
      .catch((requestError: unknown) => {
        if (controller.signal.aborted || generation !== loadGeneration.current) {
          return;
        }
        if (
          nextWrite.revision === layoutRevision.current
          && layoutWriteQueue.current === null
        ) {
          rejectLayout(`Layout could not be saved: ${errorMessage(requestError)}`);
        }
      })
      .finally(() => {
        if (layoutWriteInFlight.current?.sequence !== sequence) {
          return;
        }
        layoutWriteInFlight.current = null;
        if (layoutWriteQueue.current !== null && generation === loadGeneration.current) {
          flushLayoutWrite();
        }
      });
  }, [projectId, rejectLayout]);

  const applyLocalLayout = useCallback(
    (nextLayout: WorkspaceLayout, persist: boolean): PendingLayoutWrite | null => {
      if (!isValidWorkspaceLayout(nextLayout)) {
        rejectLayout("Layout was rejected locally: Unit positions must be finite and bounded.");
        return null;
      }
      const revision = layoutRevision.current + 1;
      layoutRevision.current = revision;
      layoutRef.current = nextLayout;
      setLayout(nextLayout);
      const pending = { layout: nextLayout, revision };
      if (persist) {
        setSaveState("saving");
        layoutWriteQueue.current = pending;
      }
      return pending;
    },
    [rejectLayout],
  );

  const enqueueLayoutSave = useCallback(
    (nextLayout: WorkspaceLayout): void => {
      if (applyLocalLayout(nextLayout, true) === null) {
        return;
      }
      flushLayoutWrite();
    },
    [applyLocalLayout, flushLayoutWrite],
  );

  useEffect(() => {
    const generation = loadGeneration.current + 1;
    loadGeneration.current = generation;
    const controller = new AbortController();
    layoutWriteInFlight.current?.controller.abort();
    layoutWriteInFlight.current = null;
    layoutWriteQueue.current = null;
    layoutRevision.current = 0;
    semanticController.current?.abort();
    setPhase("loading");
    setError(null);
    setSemanticError(null);
    setSelectedUnitId(null);
    setSaveState("saved");
    void Promise.all([
      getWorkspace(projectId, controller.signal),
      getWorkspaceLayout(projectId, controller.signal),
    ])
      .then(([workspace, serverLayout]) => {
        if (controller.signal.aborted || generation !== loadGeneration.current) {
          return;
        }
      const mapped = toPlanCanvas(workspace.plan, serverLayout);
      confirmedLayoutRef.current = serverLayout;
      layoutRef.current = mapped.layout;
        setPlan(workspace.plan);
        setLayout(mapped.layout);
        setPhase("ready");
      })
      .catch((requestError: unknown) => {
        if (controller.signal.aborted || generation !== loadGeneration.current) {
          return;
        }
        setPhase("error");
        setError(errorMessage(requestError));
      });
    return () => {
      controller.abort();
      layoutWriteInFlight.current?.controller.abort();
      layoutWriteInFlight.current = null;
      layoutWriteQueue.current = null;
      semanticController.current?.abort();
    };
  }, [projectId, refreshKey]);

  const mapping = useMemo(() => toPlanCanvas(plan, layout), [layout, plan]);

  const toggleUnit = useCallback(
    (unitId: number): void => {
      const nextLayout: WorkspaceLayout = {
        ...layoutRef.current,
        nodes: layoutRef.current.nodes.map((node) =>
          node.unit_id === unitId ? { ...node, collapsed: !node.collapsed } : node,
        ),
      };
      enqueueLayoutSave(nextLayout);
    },
    [enqueueLayoutSave],
  );

  const handleNodesChange = useCallback(
    (changes: NodeChange[]): void => {
      const positionChanges = changes.filter(
        (change): change is Extract<NodeChange, { type: "position" }> =>
          change.type === "position" && change.position !== undefined,
      );
      if (positionChanges.length === 0) {
        return;
      }
      const positions = new Map(
        positionChanges
          .map((change) => [unitIdFromNodeId(change.id), change.position] as const)
          .filter((entry): entry is [number, { x: number; y: number }] => entry[0] !== null),
      );
      const nextLayout = layoutWithPositions(layoutRef.current, positions);
      if (nextLayout === null) {
        rejectLayout("Layout was rejected locally: Unit positions must be finite and bounded.");
        return;
      }
      applyLocalLayout(nextLayout, false);
    },
    [applyLocalLayout, rejectLayout],
  );

  const handleNodeDragStop = useCallback<OnNodeDrag<PlanCanvasNode>>(
    (_event, node) => {
      const unitId = unitIdFromNodeId(node.id);
      if (unitId === null) {
        return;
      }
      const nextLayout = layoutWithNodePosition(layoutRef.current, unitId, node.position);
      if (nextLayout === null) {
        rejectLayout("Layout was rejected locally: Unit positions must be finite and bounded.");
        return;
      }
      enqueueLayoutSave(nextLayout);
    },
    [enqueueLayoutSave, rejectLayout],
  );

  const reconcileServerPlan = useCallback(
    (nextPlan: Plan | null): void => {
      const mapped = toPlanCanvas(nextPlan, layoutRef.current);
      const nextLayout = mapped.layout;
      planRef.current = nextPlan;
      setPlan(nextPlan);
      if (mapped.layoutChanged) {
        enqueueLayoutSave(nextLayout);
      }
      onPlanChanged?.();
    },
    [enqueueLayoutSave, onPlanChanged],
  );

  const updateUnit = useCallback(
    async (unitId: number, patch: WorkspaceUnitPatch): Promise<void> => {
      if (semanticBusyRef.current) {
        return;
      }
      const generation = loadGeneration.current;
      const controller = new AbortController();
      semanticController.current?.abort();
      semanticController.current = controller;
      semanticBusyRef.current = true;
      setSemanticBusy(true);
      setSemanticError(null);
      setValidationErrorIssues([]);
      setDeleteConflict(null);
      try {
        const response = await updateWorkspaceUnit(projectId, unitId, patch, controller.signal);
        if (controller.signal.aborted || generation !== loadGeneration.current) {
          return;
        }
        reconcileServerPlan(response.plan);
      } catch (requestError: unknown) {
        if (!controller.signal.aborted && generation === loadGeneration.current) {
          setValidationErrorIssues(validationIssues(requestError));
          setSemanticError(`Plan update rejected: ${errorMessage(requestError)}`);
        }
        throw requestError;
      } finally {
        semanticBusyRef.current = false;
        if (!controller.signal.aborted && generation === loadGeneration.current) {
          setSemanticBusy(false);
        }
      }
    },
    [projectId, reconcileServerPlan],
  );

  const createOperation = useCallback(
    async (
      operation: OperationKind,
      selectedRef?: string,
    ): Promise<void> => {
      if (semanticBusyRef.current) {
        return;
      }
      if (!catalog) {
        setSemanticError("Upload at least one Source before adding an operation.");
        return;
      }
      const initial = buildInitialUnitPayload(operation, catalog, selectedRef, planRef.current);
      if (!initial.payload) {
        setSemanticError(initial.reason ?? "This operation is not available for the current data.");
        return;
      }
      const generation = loadGeneration.current;
      const controller = new AbortController();
      semanticController.current?.abort();
      semanticController.current = controller;
      semanticBusyRef.current = true;
      setSemanticBusy(true);
      setSemanticError(null);
      setValidationErrorIssues([]);
      try {
        const previousPlan = planRef.current;
        const response = await createWorkspaceUnit(projectId, initial.payload, controller.signal);
        if (controller.signal.aborted || generation !== loadGeneration.current) {
          return;
        }
        const createdId = newUnitId(previousPlan, response.plan);
        reconcileServerPlan(response.plan);
        if (createdId !== null) {
          setSelectedUnitId(createdId);
        }
      } catch (requestError: unknown) {
        if (!controller.signal.aborted && generation === loadGeneration.current) {
          setValidationErrorIssues(validationIssues(requestError));
          setSemanticError(`Operation could not be created: ${errorMessage(requestError)}`);
        }
      } finally {
        semanticBusyRef.current = false;
        if (!controller.signal.aborted && generation === loadGeneration.current) {
          setSemanticBusy(false);
        }
      }
    },
    [catalog, projectId, reconcileServerPlan],
  );

  useEffect(() => {
    if (!requestedOperation || !catalog || semanticBusy) {
      return;
    }
    void createOperation(requestedOperation).finally(onRequestedOperationHandled);
  }, [catalog, createOperation, onRequestedOperationHandled, requestedOperation, semanticBusy]);

  const handleDropColumn = useCallback(
    (unitId: number, slot: ColumnDropSlot, payload: QualifiedColumnDrag): void => {
      const unit = planRef.current?.units.find((item) => item.unit_id === unitId);
      if (!unit) {
        return;
      }
      const intent = resolveColumnDrop(payload, slot, unit);
      if (intent.kind === "patch") {
        void updateUnit(unitId, intent.patch).catch(() => undefined);
        return;
      }
      if (intent.kind === "rejected") {
        setValidationErrorIssues([]);
        setSemanticError(intent.reason);
      }
    },
    [updateUnit],
  );

  const handleRemoveColumn = useCallback(
    (unitId: number, slot: ColumnDropSlot, ref: string): void => {
      const unit = planRef.current?.units.find((item) => item.unit_id === unitId);
      if (!unit) {
        return;
      }
      const intent = resolveColumnRemove(slot, unit, ref);
      if (intent.kind === "patch") {
        void updateUnit(unitId, intent.patch).catch(() => undefined);
        return;
      }
      setValidationErrorIssues([]);
      setSemanticError(intent.reason);
    },
    [updateUnit],
  );

  const handleCanvasDrop = useCallback(
    (payload: DragPayload): void => {
      const intent = resolveEmptyCanvasDrop(payload);
      if (intent.kind === "rejected") {
        setSemanticError(intent.reason);
      }
    },
    [],
  );

  const deleteUnit = useCallback(
    async (unitId: number, cascade: boolean): Promise<void> => {
      if (semanticBusyRef.current) {
        return;
      }
      const generation = loadGeneration.current;
      const controller = new AbortController();
      semanticController.current?.abort();
      semanticController.current = controller;
      semanticBusyRef.current = true;
      setSemanticBusy(true);
      setSemanticError(null);
      setValidationErrorIssues([]);
      try {
        const response = await deleteWorkspaceUnit(projectId, unitId, cascade, controller.signal);
        if (controller.signal.aborted || generation !== loadGeneration.current) {
          return;
        }
        reconcileServerPlan(response.plan);
        setDeleteConflict(null);
        setSelectedUnitId(null);
      } catch (requestError: unknown) {
        if (!controller.signal.aborted && generation === loadGeneration.current) {
          const dependentIds = downstreamUnitIds(requestError);
          if (dependentIds.length > 0) {
            setDeleteConflict({ unitId, dependentUnitIds: dependentIds });
            setSemanticError(null);
          } else {
            setSemanticError(`Unit could not be deleted: ${errorMessage(requestError)}`);
          }
        }
      } finally {
        semanticBusyRef.current = false;
        if (!controller.signal.aborted && generation === loadGeneration.current) {
          setSemanticBusy(false);
        }
      }
    },
    [projectId, reconcileServerPlan],
  );

  const selectedUnit = useMemo(
    () => plan?.units.find((unit) => unit.unit_id === selectedUnitId) ?? null,
    [plan, selectedUnitId],
  );

  useEffect(() => {
    if (selectedUnitId !== null && !selectedUnit) {
      setSelectedUnitId(null);
    }
  }, [selectedUnit, selectedUnitId]);

  useEffect(() => {
    if (selectedUnitId === null) {
      return;
    }
    const handleKeyDown = (event: KeyboardEvent): void => {
      if (event.key === "Escape") {
        setSelectedUnitId(null);
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [selectedUnitId]);

  const handleConnect = useCallback(
    (connection: Connection): void => {
      const sourceUnitId = connection.source ? unitIdFromNodeId(connection.source) : null;
      const targetUnitId = connection.target ? unitIdFromNodeId(connection.target) : null;
      if (sourceUnitId === null || targetUnitId === null || sourceUnitId === targetUnitId) {
        return;
      }
      const target = planRef.current?.units.find((unit) => unit.unit_id === targetUnitId);
      if (!target || target.depends_on.includes(sourceUnitId)) {
        return;
      }
      void updateUnit(targetUnitId, { depends_on: [...target.depends_on, sourceUnitId] }).catch(() => undefined);
    },
    [updateUnit],
  );

  const handleEdgesDelete = useCallback(
    (deletedEdges: Edge[]): void => {
      if (deletedEdges.length !== 1) {
        return;
      }
      const edge = deletedEdges[0];
      const sourceUnitId = unitIdFromNodeId(edge.source);
      const targetUnitId = unitIdFromNodeId(edge.target);
      if (sourceUnitId === null || targetUnitId === null) {
        return;
      }
      const target = planRef.current?.units.find((unit) => unit.unit_id === targetUnitId);
      if (!target || !target.depends_on.includes(sourceUnitId)) {
        return;
      }
      void updateUnit(
        targetUnitId,
        { depends_on: target.depends_on.filter((dependencyId) => dependencyId !== sourceUnitId) },
      ).catch(() => undefined);
    },
    [updateUnit],
  );

  if (phase === "loading") {
    return (
      <div className="plan-canvas-state" role="status">
        Loading Plan Canvas
      </div>
    );
  }

  if (phase === "error") {
    return (
      <div className="plan-canvas-state plan-canvas-error" role="alert">
        <strong>Plan Canvas unavailable</strong>
        <span>{error}</span>
      </div>
    );
  }

  return (
    <div className="placeholder-panel workspace-placeholder plan-canvas-panel">
      <div className="workspace-topline">
        <div>
          <p className="eyebrow">Workspace</p>
          <h1>Plan Canvas</h1>
          <p className="workspace-subtitle">
            A visual view of the server-confirmed Plan v2 DAG. Positions and collapse state are
            presentation-only.
          </p>
        </div>
        <div className="canvas-unit-count">
          <strong>{mapping.nodes.length}</strong>
          <span>{mapping.nodes.length === 1 ? "Unit" : "Units"}</span>
        </div>
      </div>
      {error || semanticError ? (
        <div className="canvas-inline-alert" role="alert">
          <span>{semanticError ?? error}</span>
          <button
            aria-label="Dismiss Canvas message"
            title="Dismiss"
            type="button"
            onClick={() => {
              setError(null);
              setSemanticError(null);
            }}
          >
            ×
          </button>
        </div>
      ) : null}
      <ReactFlowProvider>
        <CanvasViewport
          edges={mapping.edges}
          empty={mapping.nodes.length === 0}
          layout={mapping.layout}
          nodes={mapping.nodes}
          onCanvasDrop={handleCanvasDrop}
          onConnect={handleConnect}
          onDropColumn={handleDropColumn}
          onEdgesDelete={handleEdgesDelete}
          onNodeDragStop={handleNodeDragStop}
          onNodesChange={handleNodesChange}
          onRemoveColumn={handleRemoveColumn}
          onSelectUnit={setSelectedUnitId}
          onToggleUnit={toggleUnit}
          inspector={selectedUnit ? (
            <OperationInspector
              busy={semanticBusy}
              catalog={catalog}
              deleteConflict={deleteConflict?.unitId === selectedUnit.unit_id ? deleteConflict : null}
              error={semanticError}
              issues={validationErrorIssues.filter(
                (issue) => issue.unitId === null || issue.unitId === selectedUnit.unit_id,
              )}
              onCancelDeleteConflict={() => setDeleteConflict(null)}
              onCascadeDelete={() => deleteUnit(selectedUnit.unit_id, true)}
              onClose={() => setSelectedUnitId(null)}
              onDelete={() => deleteUnit(selectedUnit.unit_id, false)}
              onSave={(payload) => updateUnit(selectedUnit.unit_id, payload)}
              unit={selectedUnit}
            />
          ) : null}
          saveState={saveState}
          semanticBusy={semanticBusy}
          selectedUnitId={selectedUnitId}
        />
      </ReactFlowProvider>
    </div>
  );
}
