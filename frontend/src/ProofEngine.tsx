import React, { useEffect, useState } from 'react';

export const proofStages = [
  'Question',
  'Proposal',
  'Validation',
  'Quote',
  'Acceptance',
  'Execution',
  'Result',
] as const;

export type ProofStage = (typeof proofStages)[number];
export type ProofEvidence = Partial<Record<ProofStage, React.ReactNode>>;

export default function ProofEngine({
  activeStage,
  state,
  evidence,
  stopped = false,
  complete = false,
  statusOverrides = {},
}: {
  activeStage: number;
  state: string;
  evidence: ProofEvidence;
  stopped?: boolean;
  complete?: boolean;
  statusOverrides?: Partial<Record<ProofStage, string>>;
}) {
  const [selected, setSelected] = useState<ProofStage>(proofStages[0]);

  useEffect(() => {
    setSelected(proofStages[Math.max(0, Math.min(activeStage, proofStages.length - 1))]);
  }, [activeStage, state]);

  const selectedIndex = proofStages.indexOf(selected);
  const selectedEvidence = evidence[selected];
  const statusFor = (index: number) => {
    const override = statusOverrides[proofStages[index]];
    if (override) return override;
    if (complete && index <= activeStage) return 'Recorded';
    if (stopped && index === activeStage) return 'Stopped';
    if (index < activeStage) return 'Recorded';
    if (index === activeStage) return 'Current';
    return 'Pending';
  };

  return (
    <section className="proof-engine" aria-labelledby="proof-engine-title">
      <div className="proof-engine-head">
        <div>
          <span className="eyebrow">THE PROOF ENGINE</span>
          <h2 id="proof-engine-title">One decision, traceable end to end</h2>
        </div>
        <span className={`proof-state ${stopped ? 'is-stopped' : complete ? 'is-complete' : ''}`}>
          {stopped ? 'Stopped' : complete ? 'Result recorded' : state}
        </span>
      </div>

      <ol className="proof-stage-list" aria-label="Research decision stages">
        {proofStages.map((stage, index) => {
          const status = statusFor(index);
          const selectedStage = selected === stage;
          return (
            <li key={stage} className={`proof-stage ${status.toLowerCase().replace(/[^a-z0-9]+/g, '-')} ${selectedStage ? 'selected' : ''}`}>
              <button
                type="button"
                aria-pressed={selectedStage}
                aria-current={index === activeStage ? 'step' : undefined}
                aria-label={`${stage}: ${status}. ${evidence[stage] ? 'Inspect recorded evidence.' : 'No evidence recorded.'}`}
                onClick={() => setSelected(stage)}
              >
                <span className="proof-step-index">{String(index + 1).padStart(2, '0')}</span>
                <span className="proof-stage-name">{stage}</span>
                <span className="proof-stage-status">{status}</span>
              </button>
            </li>
          );
        })}
      </ol>

      <div className="proof-mobile-control">
        <label htmlFor="proof-stage-select">Inspect a decision stage</label>
        <select id="proof-stage-select" value={selected} onChange={(event) => setSelected(event.target.value as ProofStage)}>
          {proofStages.map((stage, index) => (
            <option key={stage} value={stage}>
              {String(index + 1).padStart(2, '0')} · {stage} · {statusFor(index)}
            </option>
          ))}
        </select>
      </div>

      <p className="proof-current-summary" aria-live="polite">
        {stopped
          ? `Stopped at ${proofStages[activeStage].toLowerCase()} · no later stage ran.`
          : `Current stage · ${proofStages[activeStage]}`}
      </p>

      <div className="proof-evidence" aria-live="polite" aria-atomic="true">
        <div className="proof-evidence-label">
          <span>{String(selectedIndex + 1).padStart(2, '0')}</span>
          <div>
            <h3>{selected} evidence</h3>
            <p>{statusFor(selectedIndex)} stage · {state}</p>
          </div>
        </div>
        <div className="proof-evidence-content">
          {selectedEvidence ?? (
            <p className="proof-no-evidence">
              {selectedIndex > activeStage || stopped
                ? 'No evidence was recorded for this stage.'
                : 'No supporting detail is available for this stage.'}
            </p>
          )}
        </div>
      </div>
      {stopped && <p className="proof-stop-note" role="status">Stopped at {proofStages[activeStage].toLowerCase()} · no later stage ran.</p>}
    </section>
  );
}
