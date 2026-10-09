import { Link } from "react-router-dom";
import { useAgentNames } from "@/lib/useAgentNames";

type AgentRefProps = {
  agentId: string | null | undefined;
  /** Rendered when there is no agent to point at, rather than an empty cell. */
  fallback?: string;
};

/** An agent, named and linked, given only its id. See `useAgentNames` for why. */
export function AgentRef({ agentId, fallback = "—" }: AgentRefProps) {
  const { nameFor } = useAgentNames();
  const name = nameFor(agentId);
  if (!agentId || !name) return <span className="text-ink-400">{fallback}</span>;
  return (
    <Link to={`/agents/${agentId}`} className="text-info-fg hover:underline">
      {name}
    </Link>
  );
}
