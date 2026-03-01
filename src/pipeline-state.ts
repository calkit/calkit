/**
 * Pipeline operation state for tracking client-side operations.
 * This allows different parts of the UI to subscribe to pipeline activity.
 */

type Listener = (state: IPipelineOperationState) => void;

export interface IPipelineOperationState {
  isRunning: boolean;
  isSessionInProgress: boolean;
  currentOperation?: string;
}

class PipelineState {
  private state: IPipelineOperationState = {
    isRunning: false,
    isSessionInProgress: false,
  };

  private listeners = new Set<Listener>();

  /**
   * Subscribe to pipeline operation state changes
   */
  subscribe(listener: Listener): () => void {
    this.listeners.add(listener);
    // Return unsubscribe function
    return () => {
      this.listeners.delete(listener);
    };
  }

  /**
   * Get current state
   */
  getState(): IPipelineOperationState {
    return { ...this.state };
  }

  /**
   * Set running state
   */
  setRunning(isRunning: boolean, operation?: string): void {
    if (
      this.state.isRunning === isRunning &&
      this.state.currentOperation === operation
    ) {
      return;
    }
    this.state.isRunning = isRunning;
    if (operation) {
      this.state.currentOperation = operation;
    } else if (isRunning === false) {
      this.state.currentOperation = undefined;
    }
    this.notifyListeners();
  }

  /**
   * Set session in progress state
   */
  setSessionInProgress(inProgress: boolean, operation?: string): void {
    if (
      this.state.isSessionInProgress === inProgress &&
      this.state.currentOperation === operation
    ) {
      return;
    }
    this.state.isSessionInProgress = inProgress;
    if (operation) {
      this.state.currentOperation = operation;
    } else if (inProgress === false) {
      this.state.currentOperation = undefined;
    }
    this.notifyListeners();
  }

  /**
   * Notify all listeners of state change
   */
  private notifyListeners(): void {
    this.listeners.forEach((listener) => {
      listener(this.getState());
    });
  }
}

// Export singleton instance
export const pipelineState = new PipelineState();
