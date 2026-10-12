import { useCallback } from "react";
import { api } from "../services/api";
import { useAsync } from "./useAsync";
import type {
  IncidentDetail,
  IncidentGraph,
  StateHistoryResponse,
  TimelineResponse,
} from "../types/incident";

export interface IncidentBundle {
  detail: IncidentDetail | null;
  timeline: TimelineResponse | null;
  graph: IncidentGraph | null;
  history: StateHistoryResponse | null;
  loading: boolean;
  error: Error | null;
  /** Re-fetch every piece (after a lifecycle transition). */
  reload: () => void;
}

/**
 * Loads the four read models behind an incident in parallel. Each piece has
 * its own error tolerance: a failing secondary view (e.g. graph) does not
 * block the primary detail.
 */
export function useIncidentBundle(incidentId: number): IncidentBundle {
  const detail = useAsync(() => api.getIncident(incidentId), [incidentId]);
  const timeline = useAsync(() => api.getTimeline(incidentId), [incidentId]);
  const graph = useAsync(() => api.getGraph(incidentId), [incidentId]);
  const history = useAsync(() => api.getStateHistory(incidentId), [incidentId]);

  const reload = useCallback(() => {
    detail.reload();
    timeline.reload();
    graph.reload();
    history.reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [incidentId]);

  return {
    detail: detail.data,
    timeline: timeline.data,
    graph: graph.data,
    history: history.data,
    loading: detail.loading && detail.data == null,
    error: detail.error,
    reload,
  };
}
