import { useEffect, useRef } from "react";
import { useStreamContext } from "@/providers/Stream";

type Candidate = {
  memory_id: string;
  namespace: string;
  resource_kind: "Pod";
  resource_name: string;
  observed_uid: string | null;
  symptom: string;
  observations: string[];
  cause_hypothesis: null;
  uncertainties: string[];
  source: { thread_id: string; evidence_types: string[] };
};

export type MemoryReview = {
  kind: "incident_memory_review";
  candidate_id: string;
  candidate_hash: string;
  schema_version: number;
  preview: Candidate;
};

export type RevokeReview = {
  kind: "incident_memory_revoke_review";
  memory_id: string;
  record_hash: string;
  schema_version: number;
};

function useDecision() {
  const stream = useStreamContext();
  const pending = useRef(false);
  useEffect(() => {
    if (!stream.isLoading) pending.current = false;
  }, [stream.isLoading]);
  const submit = (resume: Record<string, string | number>) => {
    if (pending.current || stream.isLoading) return;
    pending.current = true;
    try {
      stream.submit(
        {},
        {
          command: { resume },
          streamMode: ["values"],
          streamResumable: true,
        },
      );
    } catch {
      pending.current = false;
    }
  };
  return { submit, disabled: stream.isLoading };
}

function Actions({
  onDecision,
  disabled,
  approveText,
}: {
  onDecision: (decision: "approve" | "reject") => void;
  disabled: boolean;
  approveText: string;
}) {
  return (
    <div className="mt-3 flex gap-2">
      <button
        type="button"
        disabled={disabled}
        onClick={() => onDecision("approve")}
        className="rounded bg-blue-700 px-3 py-1 text-white disabled:opacity-50"
      >
        {approveText}
      </button>
      <button
        type="button"
        disabled={disabled}
        onClick={() => onDecision("reject")}
        className="rounded bg-gray-700 px-3 py-1 text-white disabled:opacity-50"
      >
        拒绝
      </button>
    </div>
  );
}

export function IncidentMemoryReviewView({ review }: { review: MemoryReview }) {
  const { submit, disabled } = useDecision();
  const candidate = review.preview;
  const decide = (decision: "approve" | "reject") =>
    submit({
      kind: review.kind,
      candidate_id: review.candidate_id,
      candidate_hash: review.candidate_hash,
      schema_version: review.schema_version,
      decision,
    });
  return (
    <section className="rounded-lg border border-blue-500 bg-blue-50 p-4">
      <h3 className="font-semibold">Incident Memory 历史案例审阅</h3>
      <p className="mt-1 text-sm">
        {candidate.namespace}/Pod/{candidate.resource_name}
        {candidate.observed_uid
          ? ` · UID ${candidate.observed_uid}`
          : " · UID 未知"}
      </p>
      <p className="mt-1 text-sm">当时症状：{candidate.symptom}</p>
      <ul className="mt-1 list-disc pl-5 text-sm">
        {candidate.observations.map((fact) => (
          <li key={fact}>{fact}</li>
        ))}
      </ul>
      <p className="mt-1 text-sm">
        根因：未知。{candidate.uncertainties.join(" ")}
      </p>
      <p className="mt-1 text-xs">
        来源 Thread：{candidate.source.thread_id}；证据：
        {candidate.source.evidence_types.join(", ")}
      </p>
      <p className="mt-2 text-xs font-semibold">
        DEMO_WORKFLOW_ONLY：保存的是历史参考，不是当前 Kubernetes
        证据，也不授权修复。同一 Demo Key 可自行发起 Run 并批准。
      </p>
      <Actions
        onDecision={decide}
        disabled={disabled}
        approveText="批准保存历史案例"
      />
    </section>
  );
}

export function IncidentMemoryRevokeView({ review }: { review: RevokeReview }) {
  const { submit, disabled } = useDecision();
  const decide = (decision: "approve" | "reject") =>
    submit({
      kind: review.kind,
      memory_id: review.memory_id,
      record_hash: review.record_hash,
      schema_version: review.schema_version,
      decision,
    });
  return (
    <section className="rounded-lg border border-blue-500 bg-blue-50 p-4">
      <h3 className="font-semibold">确认撤销 Incident Memory</h3>
      <p className="mt-1 text-sm">案例 ID：{review.memory_id}</p>
      <p className="mt-1 text-xs">
        撤销后不再用于后续检索；已有 Thread History 和 Checkpoint 不会被清除。
      </p>
      <p className="mt-1 text-xs font-semibold">
        DEMO_WORKFLOW_ONLY：同一 Demo Key 可自行确认撤销。
      </p>
      <Actions
        onDecision={decide}
        disabled={disabled}
        approveText="确认撤销"
      />
    </section>
  );
}
