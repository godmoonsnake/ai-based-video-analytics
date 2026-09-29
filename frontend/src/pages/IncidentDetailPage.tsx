import { api } from "../services/api";
import { useAsync } from "../hooks/useAsync";
import { fmtTime, fmtDuration, incidentType, priorityClass } from "../lib/format";
import { Loading, Empty, ErrorState } from "../components/common/States";
import { Section } from "../components/common/Section";
import { ConfidenceBadge, StateBadge } from "../components/incidents/Badges";
import {
  WhyCreated,
  SupportingTracks,
  SupportingEvents,
  BehaviourSignals,
} from "../components/incidents/ExplanationParts";
import { Correlations } from "../components/incidents/Correlations";
import { Timeline } from "../components/timeline/Timeline";
import { IncidentGraph } from "../components/graph/IncidentGraph";
import { Evidence } from "../components/evidence/Evidence";
import { LifecycleControls } from "../components/lifecycle/LifecycleControls";
import { StateHistory } from "../components/lifecycle/StateHistory";

interface Props {
  incidentId: number;
  onStateChanged?: () => void; // let the list refresh after a transition
}

export function IncidentDetailPage({ incidentId, onStateChanged }: Props) {
  const detail = useAsync(() => api.getIncident(incidentId), [incidentId]);
  const timeline = useAsync(() => api.getTimeline(incidentId), [incidentId]);
  const graph = useAsync(() => api.getGraph(incidentId), [incidentId]);
  const history = useAsync(() => api.getStateHistory(incidentId), [incidentId]);

  if (detail.loading) return <Loading label="Loading incident…" />;
  if (detail.error) return <ErrorState error={detail.error} onRetry={detail.reload} />;
  if (!detail.data) return <Empty label="Incident not found." />;

  const inc = detail.data;

  function refreshAfterTransition() {
    detail.reload();
    history.reload();
    onStateChanged?.();
  }

  return (
    <div className="incident-detail" data-testid="incident-detail">
      <header className="detail-header">
        <div className="detail-title">
          <h2>Incident #{inc.id}</h2>
          <span className={`type-pill ${priorityClass(inc.priority)}`}>
            {incidentType(inc.priority)}
          </span>
          <StateBadge state={inc.state} />
          <ConfidenceBadge confidence={inc.confidence} band={inc.confidence_band} />
        </div>
        <div className="detail-when">
          <span>{fmtTime(inc.start_time)} → {fmtTime(inc.end_time)}</span>
          <span className="muted"> · {fmtDuration(inc.start_time, inc.end_time)}</span>
          <span className="muted"> · {inc.cameras.length} cameras · {inc.tracks.length} tracks</span>
        </div>
        {inc.summary_text && <p className="detail-summary">{inc.summary_text}</p>}
        <p className="detail-disclaimer">
          Confidence is a system-derived signal from correlation and behaviour
          evidence — decision support for human review, not a verdict or an
          identity claim.
        </p>
      </header>

      <Section title="Why this incident exists" count={inc.explanation.why_created.length}>
        <WhyCreated reasons={inc.explanation.why_created} />
      </Section>

      <Section title="Operator actions">
        <LifecycleControls
          incidentId={inc.id}
          state={inc.state}
          allowedActions={inc.allowed_actions}
          onTransitioned={refreshAfterTransition}
        />
        <div className="history-block">
          <h4>History</h4>
          {history.loading ? (
            <Loading />
          ) : history.error ? (
            <ErrorState error={history.error} onRetry={history.reload} />
          ) : (
            <StateHistory history={history.data?.history ?? []} />
          )}
        </div>
      </Section>

      <Section title="Timeline" count={timeline.data?.timeline.length}>
        {timeline.loading ? (
          <Loading />
        ) : timeline.error ? (
          <ErrorState error={timeline.error} onRetry={timeline.reload} />
        ) : (timeline.data?.timeline.length ?? 0) === 0 ? (
          <Empty label="No timeline events." />
        ) : (
          <Timeline steps={timeline.data!.timeline} />
        )}
      </Section>

      <Section title="Correlations" count={inc.explanation.correlations.length}>
        {inc.explanation.correlations.length === 0 ? (
          <Empty label="No cross-camera correlations for this incident." />
        ) : (
          <Correlations correlations={inc.explanation.correlations} />
        )}
      </Section>

      <Section title="Graph" defaultOpen={false}>
        {graph.loading ? (
          <Loading />
        ) : graph.error ? (
          <ErrorState error={graph.error} onRetry={graph.reload} />
        ) : graph.data ? (
          <IncidentGraph graph={graph.data} />
        ) : (
          <Empty />
        )}
      </Section>

      <Section title="Evidence" defaultOpen={false}>
        <Evidence events={inc.events} />
      </Section>

      <Section title="Supporting tracks" count={inc.tracks.length} defaultOpen={false}>
        <SupportingTracks tracks={inc.tracks} />
      </Section>

      <Section title="Supporting events" count={inc.explanation.supporting_events.length} defaultOpen={false}>
        <SupportingEvents events={inc.explanation.supporting_events} />
      </Section>

      <Section title="Behaviour signals" count={inc.explanation.behaviour_signals.length} defaultOpen={false}>
        <BehaviourSignals signals={inc.explanation.behaviour_signals} />
      </Section>
    </div>
  );
}
