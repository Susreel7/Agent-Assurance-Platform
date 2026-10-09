import { useAgents } from "@/api/queries";

/** Resolves an agent id to its display name, for tables that only carry the id.
 *
 * Findings, evidence events and policy decisions all reference an agent by id and
 * nothing else — the API returns no name alongside them. Rendering the raw UUID is the
 * kind of thing that makes a console unusable for anyone who did not build it, and three
 * screens had each been about to solve it differently.
 *
 * The estate is small enough (tens of agents, not thousands) that one cached list serves
 * every lookup on the page, and TanStack Query dedupes it across components. If the
 * estate grows past a single page this stops being the right answer and the names belong
 * on the API responses instead — see tasks.md, "denormalise agent name onto list rows".
 */

// Above any realistic single-tenant estate, and one request rather than one per row.
const LOOKUP_LIMIT = "500";

export function useAgentNames() {
  const query = useAgents({ limit: LOOKUP_LIMIT });
  const byId = new Map((query.data?.items ?? []).map((a) => [a.id, a]));
  return {
    isLoading: query.isLoading,
    nameFor: (agentId: string | null | undefined) => {
      if (!agentId) return null;
      const agent = byId.get(agentId);
      // Falling back to a short id beats an empty cell: it is still selectable and
      // still greppable in the API, it just is not a name.
      return agent?.display_name ?? `${agentId.slice(0, 8)}…`;
    },
  };
}
