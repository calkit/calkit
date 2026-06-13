/**
 * Pipeline status indicator for the JupyterLab status bar.
 */
import { Widget } from "@lumino/widgets";
import { useEffect, useState } from "react";
import React from "react";
import { createRoot } from "react-dom/client";
import { requestAPI } from "../request";
import type { IPipelineStatus } from "../hooks/useQueries";
import { pipelineState, type IPipelineOperationState } from "../pipeline-state";

/**
 * React component for pipeline status display
 */
interface IPipelineStatusIndicatorProps {
  onStatusClick?: () => void;
}

const PipelineStatusIndicator: React.FC<IPipelineStatusIndicatorProps> = ({
  onStatusClick,
}) => {
  const [status, setStatus] = useState<IPipelineStatus | null>(null);
  const [operationState, setOperationState] = useState<IPipelineOperationState>(
    pipelineState.getState(),
  );

  // Poll pipeline status every 2 seconds
  useEffect(() => {
    let isMounted = true;
    const pollStatus = async () => {
      try {
        const data = await requestAPI<IPipelineStatus>("pipeline/status");
        if (isMounted) {
          setStatus(data);
        }
      } catch (error) {
        console.warn("Failed to fetch pipeline status:", error);
      }
    };

    // Initial fetch
    void pollStatus();

    // Poll every 2 seconds
    const interval = setInterval(() => {
      void pollStatus();
    }, 2000);

    return () => {
      isMounted = false;
      clearInterval(interval);
    };
  }, []);

  // Subscribe to operation state changes
  useEffect(() => {
    const unsubscribe = pipelineState.subscribe((newState) => {
      setOperationState(newState);
    });
    return unsubscribe;
  }, []);

  // If pipeline is running, show that immediately
  if (operationState.isRunning) {
    return (
      <div
        className="calkit-status-bar-item"
        title={operationState.currentOperation || "Pipeline is running..."}
        onClick={onStatusClick}
        role="button"
        tabIndex={0}
      >
        <span className="calkit-status-indicator running">⟳</span>
        <span className="calkit-status-label">Pipeline: Running</span>
      </div>
    );
  }

  // If session is in progress, show that
  if (operationState.isSessionInProgress) {
    return (
      <div
        className="calkit-status-bar-item"
        title={operationState.currentOperation || "Session in progress..."}
        onClick={onStatusClick}
        role="button"
        tabIndex={0}
      >
        <span className="calkit-status-indicator running">⟳</span>
        <span className="calkit-status-label">Pipeline: Session Active</span>
      </div>
    );
  }

  if (!status) {
    return (
      <div
        className="calkit-status-bar-item"
        onClick={onStatusClick}
        role="button"
        tabIndex={0}
      >
        <span className="calkit-status-label">Pipeline: —</span>
      </div>
    );
  }

  // Determine status and icon
  let statusText = "";
  let statusClass = "";
  let title = "";

  if (status.error) {
    statusText = "Failed";
    statusClass = "error";
    title = `Pipeline failed: ${status.error}`;
  } else if (status.is_outdated) {
    statusText = "Stale";
    statusClass = "stale";
    const staleCount = status.stale_stages
      ? Object.keys(status.stale_stages).length
      : 0;
    title =
      staleCount > 0
        ? `${staleCount} stage${staleCount === 1 ? "" : "s"} out of date`
        : "Pipeline is out of date";
  } else {
    statusText = "Up-to-date";
    statusClass = "uptodate";
    title = "Pipeline is up-to-date";
  }

  return (
    <div
      className="calkit-status-bar-item"
      title={title}
      onClick={onStatusClick}
      role="button"
      tabIndex={0}
    >
      <span className={`calkit-status-indicator ${statusClass}`}>●</span>
      <span className="calkit-status-label">Pipeline: {statusText}</span>
    </div>
  );
};

/**
 * A widget for displaying pipeline status in the JupyterLab status bar.
 */
export class PipelineStatusWidget extends Widget {
  private _onStatusClick: (() => void) | null = null;

  constructor(onStatusClick?: () => void) {
    super();
    this._onStatusClick = onStatusClick || null;
    this.addClass("calkit-pipeline-status");
    this.node.style.display = "flex";
    this.node.style.alignItems = "center";
    this.node.style.paddingRight = "8px";
    this.node.style.cursor = "pointer";

    // Render the React component
    const root = createRoot(this.node);
    root.render(
      <PipelineStatusIndicator
        onStatusClick={this._onStatusClick || undefined}
      />,
    );
  }

  dispose(): void {
    super.dispose();
  }
}
