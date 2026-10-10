import { useStreamContext } from "@/providers/Stream";

/** Approval is a structured resume command; chat text never decides it. */
export function DemoApprovalView({ question }: { question: string }) {
  const stream = useStreamContext();

  const decide = (decision: "approve" | "reject") => {
    stream.submit(
      {},
      {
        command: { resume: { decision } },
        streamMode: ["values"],
        streamResumable: true,
      },
    );
  };

  return (
    <div className="rounded-lg border border-amber-300 bg-amber-50 p-4">
      <h3 className="font-semibold">Mock approval required</h3>
      <p className="mt-1 text-sm">{question}</p>
      <p className="mt-1 text-xs">Simulation only. No Kubernetes action will run.</p>
      <div className="mt-3 flex gap-2">
        <button
          type="button"
          disabled={stream.isLoading}
          onClick={() => decide("approve")}
          className="rounded bg-green-700 px-3 py-1 text-white disabled:opacity-50"
        >
          Approve mock
        </button>
        <button
          type="button"
          disabled={stream.isLoading}
          onClick={() => decide("reject")}
          className="rounded bg-gray-700 px-3 py-1 text-white disabled:opacity-50"
        >
          Reject mock
        </button>
      </div>
    </div>
  );
}
