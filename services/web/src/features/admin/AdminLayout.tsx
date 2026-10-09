/**
 * Administration section chrome. Child screens (Nexus People, MCP registry, …)
 * own their own PageHeader — this layout only provides the section subnav.
 */

import { Outlet, useLocation } from "react-router-dom";
import { SuiteSubNav } from "@/features/suite/SuiteSubNav";

const SUB_NAV = [
  { to: "/admin", label: "Overview", end: true },
  { to: "/admin/people", label: "People & teams" },
  { to: "/admin/access", label: "Roles & access" },
  { to: "/admin/connections", label: "Credentials" },
  { to: "/admin/mcp", label: "MCP registry" },
  { to: "/admin/audit", label: "Security & audit" },
];

export default function AdminLayout() {
  const location = useLocation();
  // Detail pages get the full width without the section subnav competing with
  // the Nexus tool-detail tab strip.
  const hideSubNav = /\/admin\/mcp\/[^/]+/.test(location.pathname);

  return (
    <>
      {hideSubNav ? null : <SuiteSubNav items={SUB_NAV} ariaLabel="Administration sections" />}
      <Outlet />
    </>
  );
}
