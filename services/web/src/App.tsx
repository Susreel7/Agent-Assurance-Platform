/**
 * Route table for the console and the trust portal.
 *
 * Everything under `<Shell />` is the operator console, which is one audience behind one
 * navigation. The portal sits outside the shell deliberately: it is the only route a
 * customer's own staff reach, and it must not render the console's navigation,
 * estate-wide counts or tenant switcher.
 *
 * **This table is longer than the navigation, and stays that way.** A ledger install
 * does not show Clients, Engagements, Accreditations, Service levels or the graph in
 * its sidebar, but every one of those URLs still resolves — the bootstrap's
 * `capability_flags` decide what is *offered*, never what exists. Deleting a route to
 * match a manifest turns somebody's bookmark into a redirect to Home, which is the
 * failure `inv_existing_urls_survive` exists to catch.
 *
 * The portal path carries both the customer and the engagement because an engagement
 * slug is only unique within one customer — one slug matched five clients in the seeded
 * estate and the page was a 500 for all of them. See D-035.
 *
 * Heavy or audience-specific screens are lazily loaded — see declarations below.
 */

import { Suspense, lazy } from "react";
import { Navigate, Route, Routes, useParams } from "react-router-dom";
import { Shell } from "@/components/Shell";
import { TableSkeleton } from "@/components/Skeleton";
import { AuthGate } from "@/features/auth/AuthGate";
import LoginScreen from "@/features/auth/LoginScreen";
import LoginCallbackScreen from "@/features/auth/LoginCallbackScreen";
import HomeRoute from "@/features/dashboard/HomeRoute";
import AgentsListScreen from "@/features/agents/AgentsListScreen";
import AgentDetailScreen from "@/features/agents/AgentDetailScreen";
import AgentVersionScreen from "@/features/agents/AgentVersionScreen";
import RunsScreen from "@/features/operations/RunsScreen";
import RunDetailScreen from "@/features/operations/RunDetailScreen";
import CostScreen from "@/features/operations/CostScreen";
import ToolsScreen from "@/features/operations/ToolsScreen";
import ReleasesListScreen from "@/features/releases/ReleasesListScreen";
import ReleaseDetailScreen from "@/features/releases/ReleaseDetailScreen";
import EvidenceExplorerScreen from "@/features/evidence/EvidenceExplorerScreen";
import CustomersListScreen from "@/features/customers/CustomersListScreen";
import CustomerDetailScreen from "@/features/customers/CustomerDetailScreen";
import EngagementsListScreen from "@/features/engagements/EngagementsListScreen";
import EngagementDetailScreen from "@/features/engagements/EngagementDetailScreen";
import AccreditationsListScreen from "@/features/accreditation/AccreditationsListScreen";
import AccreditationDetailScreen from "@/features/accreditation/AccreditationDetailScreen";
import FindingsTriageScreen from "@/features/findings/FindingsTriageScreen";
import PolicyScreen from "@/features/policy/PolicyScreen";
import ModelRoutingScreen from "@/features/model-routing/ModelRoutingScreen";
import SlaScreen from "@/features/sla/SlaScreen";
import AssuranceScreen from "@/features/assurance/AssuranceScreen";

const DiscoveryScreen = lazy(() => import("@/features/discovery/DiscoveryScreen"));
const GraphExplorerScreen = lazy(() => import("@/features/graph/GraphExplorerScreen"));
const TrustPortalScreen = lazy(() => import("@/features/trust-portal/TrustPortalScreen"));

const RouterSuiteLayout = lazy(() => import("@/features/router/RouterSuiteLayout"));
const RouterDeploymentsPanel = lazy(() => import("@/features/router/RouterDeploymentsPanel"));
const RouterRoutesPanel = lazy(() => import("@/features/router/RouterRoutesPanel"));
const RouterSimulatePanel = lazy(() => import("@/features/router/RouterSimulatePanel"));
const RouterCompilePanel = lazy(() => import("@/features/router/RouterCompilePanel"));

const ObserveSuiteLayout = lazy(() => import("@/features/observe/ObserveSuiteLayout"));
const ObserveOverviewPanel = lazy(() => import("@/features/observe/ObserveTracesPanel"));
const ObserveExecutionsPanel = lazy(
  () => import("@/features/observe/ObserveExecutionsPanel"),
);
const ObserveTraceListPanel = lazy(
  () => import("@/features/observe/ObserveTraceListPanel"),
);
const ObserveExecutionDetailScreen = lazy(
  () => import("@/features/observe/ObserveExecutionDetailScreen"),
);
const ObserveTraceDetailScreen = lazy(() => import("@/features/observe/ObserveTraceDetailScreen"));
const ObserveSessionsPanel = lazy(() => import("@/features/observe/ObserveSessionsPanel"));
const ObserveSessionDetailScreen = lazy(
  () => import("@/features/observe/ObserveSessionDetailScreen"),
);
const ObserveLiveTailPanel = lazy(() => import("@/features/observe/ObserveLiveTailPanel"));
const ObserveAnalyticsPanel = lazy(() => import("@/features/observe/ObserveAnalyticsPanel"));

const PromptSuiteLayout = lazy(() => import("@/features/prompt/PromptSuiteLayout"));

function ObserveDeepLinkRedirect({
  collection,
  parameter,
}: {
  collection: "sessions" | "traces" | "executions";
  parameter: "sessionId" | "traceId" | "executionId";
}) {
  const params = useParams();
  const id = params[parameter] ?? "";
  return (
    <Navigate
      to={`/observe/${collection}/${encodeURIComponent(id)}${window.location.search}`}
      replace
    />
  );
}
const PromptArtifactsPanel = lazy(() => import("@/features/prompt/PromptArtifactsPanel"));
const PromptArtifactDetailScreen = lazy(
  () => import("@/features/prompt/PromptArtifactDetailScreen"),
);
const PromptPlaygroundPanel = lazy(() => import("@/features/prompt/PromptPlaygroundPanel"));

const EvaluateSuiteLayout = lazy(() => import("@/features/evaluate/EvaluateSuiteLayout"));

// The administration section is lazy for a different reason from the suites above: it is not
// optional, but most sessions never open it, and its screens pull in forms nothing else uses.
const AdminLayout = lazy(() => import("@/features/admin/AdminLayout"));
const AdminOverviewScreen = lazy(() => import("@/features/admin/AdminOverviewScreen"));
const PeopleScreen = lazy(() => import("@/features/admin/PeopleScreen"));
const AccessScreen = lazy(() => import("@/features/admin/AccessScreen"));
const ConnectionsScreen = lazy(() => import("@/features/admin/ConnectionsScreen"));
const McpRegistryScreen = lazy(() => import("@/features/admin/McpRegistryScreen"));
const McpServerDetailScreen = lazy(() => import("@/features/admin/McpServerDetailScreen"));
const AuditScreen = lazy(() => import("@/features/admin/AuditScreen"));
const ProfileScreen = lazy(() => import("@/features/admin/ProfileScreen"));
const ControlCenterScreen = lazy(() => import("@/features/control/ControlCenterScreen"));
const PlatformKeysScreen = lazy(() => import("@/features/control/PlatformKeysScreen"));

export default function App() {
  return (
    <Suspense fallback={<TableSkeleton rows={8} cols={4} />}>
      <AuthGate>
      <Routes>
        <Route path="login" element={<LoginScreen />} />
        {/* A separate screen from the one above, not the same one reading `?code`. The
            callback has exactly one job and one failure mode, and sharing a component
            with the provider list meant a failed exchange re-rendered sign-in buttons
            over the top of the error. */}
        <Route path="login/callback" element={<LoginCallbackScreen />} />
        <Route element={<Shell />}>
          <Route index element={<HomeRoute />} />
          <Route path="agents" element={<AgentsListScreen />} />
          <Route path="agents/:agentId" element={<AgentDetailScreen />} />
          <Route path="agents/:agentId/versions/:versionId" element={<AgentVersionScreen />} />
          {/* Placeholder for M4. A nav entry pointing at a route that does not exist
              falls through to the catch-all and silently lands on Home, which reads as
              a broken link rather than as work not done yet. */}
          <Route path="discovery" element={<DiscoveryScreen />} />
          <Route path="runs" element={<RunsScreen />} />
          <Route path="runs/:runId" element={<RunDetailScreen />} />
          <Route path="cost" element={<CostScreen />} />
          <Route path="tools" element={<ToolsScreen />} />
          <Route path="releases" element={<ReleasesListScreen />} />
          <Route path="releases/:releaseId" element={<ReleaseDetailScreen />} />
          <Route path="evidence" element={<EvidenceExplorerScreen />} />
          <Route path="graph" element={<GraphExplorerScreen />} />
          <Route path="customers" element={<CustomersListScreen />} />
          <Route path="customers/:customerId" element={<CustomerDetailScreen />} />
          <Route path="engagements" element={<EngagementsListScreen />} />
          <Route path="engagements/:engagementId" element={<EngagementDetailScreen />} />
          <Route path="accreditations" element={<AccreditationsListScreen />} />
          <Route
            path="accreditations/:accreditationId"
            element={<AccreditationDetailScreen />}
          />
          <Route path="findings" element={<FindingsTriageScreen />} />
          <Route path="policy" element={<PolicyScreen />} />
          <Route path="model-routing" element={<ModelRoutingScreen />} />
          <Route path="control" element={<ControlCenterScreen />} />
          <Route path="platform-keys" element={<PlatformKeysScreen />} />
          <Route path="assurance" element={<AssuranceScreen />} />
          <Route path="sla" element={<SlaScreen />} />
          <Route
            path="sessions/:sessionId"
            element={<ObserveDeepLinkRedirect collection="sessions" parameter="sessionId" />}
          />
          <Route
            path="traces/:traceId"
            element={<ObserveDeepLinkRedirect collection="traces" parameter="traceId" />}
          />
          <Route
            path="executions/:executionId"
            element={<ObserveDeepLinkRedirect collection="executions" parameter="executionId" />}
          />

          <Route path="router" element={<RouterSuiteLayout />}>
            <Route index element={<RouterDeploymentsPanel />} />
            <Route path="routes" element={<RouterRoutesPanel />} />
            <Route path="simulate" element={<RouterSimulatePanel />} />
            <Route path="compile" element={<RouterCompilePanel />} />
          </Route>

          <Route path="observe" element={<ObserveSuiteLayout />}>
            <Route index element={<ObserveOverviewPanel />} />
            <Route path="executions" element={<ObserveExecutionsPanel />} />
            <Route path="executions/:executionId" element={<ObserveExecutionDetailScreen />} />
            <Route path="traces" element={<ObserveTraceListPanel />} />
            <Route path="traces/:traceId" element={<ObserveTraceDetailScreen />} />
            <Route path="sessions" element={<ObserveSessionsPanel />} />
            <Route path="sessions/:sessionId" element={<ObserveSessionDetailScreen />} />
            <Route path="analytics" element={<ObserveAnalyticsPanel />} />
            <Route path="live" element={<ObserveLiveTailPanel />} />
          </Route>

          <Route path="prompt" element={<PromptSuiteLayout />}>
            <Route index element={<PromptArtifactsPanel />} />
            <Route path="artifacts/:artifactKey" element={<PromptArtifactDetailScreen />} />
            <Route path="playground" element={<PromptPlaygroundPanel />} />
          </Route>

          <Route path="evaluate" element={<EvaluateSuiteLayout />} />

          <Route path="admin" element={<AdminLayout />}>
            <Route index element={<AdminOverviewScreen />} />
            <Route path="people" element={<PeopleScreen />} />
            <Route path="access" element={<AccessScreen />} />
            <Route path="connections" element={<ConnectionsScreen />} />
            <Route path="mcp" element={<McpRegistryScreen />} />
            {/* Outside the /admin/mcp index so the server page gets the whole width
                rather than sitting under the registry's filters. */}
            <Route path="mcp/:serverId" element={<McpServerDetailScreen />} />
            <Route path="audit" element={<AuditScreen />} />
          </Route>

          {/* Not under /admin: your own profile is not an administrative act, and it is the
              one page in this group that every member can reach. */}
          <Route path="profile" element={<ProfileScreen />} />
        </Route>
        <Route
          path="portal/:customerSlug/:engagementSlug"
          element={<TrustPortalScreen />}
        />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
      </AuthGate>
    </Suspense>
  );
}
