import { useStreamContext } from "@/providers/Stream";

type Proposal = {
  proposal_id: string;
  namespace: string;
  kind: string;
  name: string;
  before_replicas: number;
  target_replicas: number;
  impact: string;
  simulated: boolean;
};

/** The server rechecks this ID and ignores all client-supplied resource parameters. */
export function RepairApprovalView({ proposal }: { proposal: Proposal }) {
  const stream = useStreamContext();
  const decide = (decision: "approve" | "reject") => {
    stream.submit(
      {},
      {
        command: { resume: { decision, proposal_id: proposal.proposal_id } },
        streamMode: ["values"],
        streamResumable: true,
      },
    );
  };

  return (
    <div className="rounded-lg border border-amber-500 bg-amber-50 p-4">
      <h3 className="font-semibold">{proposal.simulated ? "离线模拟审批" : "Kubernetes 受控恢复审批"}</h3>
      <p className="mt-1 text-sm">
        {proposal.namespace}/{proposal.kind}/{proposal.name}：
        {proposal.before_replicas} → {proposal.target_replicas} 副本
      </p>
      <p className="mt-1 text-sm">{proposal.impact}</p>
      <p className="mt-1 text-xs">提案 ID：{proposal.proposal_id}</p>
      <p className="mt-1 text-xs">{proposal.simulated
        ? "simulated=true：批准后仅修改独立 Mock 的内存状态，不会写入 Kubernetes。"
        : "批准后会请求真实 Kubernetes 写入；副本数达到 1 仍需单独核查 Pod Ready。"}</p>
      <div className="mt-3 flex gap-2">
        <button type="button" disabled={stream.isLoading} onClick={() => decide("approve")}
          className="rounded bg-red-700 px-3 py-1 text-white disabled:opacity-50">
          批准扩容到 1
        </button>
        <button type="button" disabled={stream.isLoading} onClick={() => decide("reject")}
          className="rounded bg-gray-700 px-3 py-1 text-white disabled:opacity-50">
          拒绝
        </button>
      </div>
    </div>
  );
}
