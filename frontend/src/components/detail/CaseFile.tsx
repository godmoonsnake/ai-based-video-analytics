import type { IncidentDetail } from "../../types/incident";

export function CaseFile({ detail }: { detail: IncidentDetail }) {
  return <div className="case-reasons">
    {detail.case_study && <div className="case-study-context">
      <strong>{detail.case_study.type.replace(/_/g, " ")}</strong>
      {detail.case_study.synthetic && <span> · DEMO DATA</span>}
      <dl>
        <div><dt>Site</dt><dd>{detail.case_study.site}</dd></div>
        <div><dt>Zone</dt><dd>{detail.case_study.zone}</dd></div>
        <div><dt>Observed</dt><dd>{new Date(detail.case_study.observed_at * 1000).toLocaleString()}</dd></div>
        <div><dt>Source</dt><dd>{detail.case_study.source} ({detail.case_study.source_instance})</dd></div>
        <div><dt>Decision</dt><dd>{detail.case_study.decision}</dd></div>
        <div><dt>Policy</dt><dd>{detail.case_study.policy_ids.join(", ") || "No matching policy"} ({detail.case_study.policy_version})</dd></div>
        <div><dt>Detector score</dt><dd>{detail.case_study.detector_confidence == null ? "Not supplied" : detail.case_study.detector_confidence.toFixed(2)}</dd></div>
        <div><dt>Evidence</dt><dd>{Object.entries(detail.case_study.evidence_status).map(([kind, status]) => `${kind}: ${status}`).join(", ") || "Not supplied"}</dd></div>
      </dl>
      <p>{detail.case_study.reason}</p>
    </div>}
    {detail.explanation.why_created.length ? detail.explanation.why_created.map((reason, index) =>
      <div className="why-reason" data-testid="why-reason" key={index}><span className="why-n">{index + 1}</span><span className="why-text">{reason}</span></div>)
      : <p>No explanation has been recorded for this incident.</p>}
    <p className="decision-note">These signals support operator review. Correlation describes a possible movement path, not a verified identity.</p>
  </div>;
}
