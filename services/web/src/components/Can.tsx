/**
 * Renders children only when the signed-in person holds a permission.
 *
 * There is no loading branch: permissions arrive with the bootstrap, before the shell
 * renders at all, so a guarded control is decided on first paint rather than appearing a
 * beat later. This used to return `null` while `/v1/access/me` was in flight.
 *
 * `fallback` is for the case where the absence needs explaining — an empty panel where a
 * form would be is confusing, so an approvals screen shows "you are not an approver"
 * instead of a blank.
 */

import { usePermissions } from "@/lib/permissions";

export function Can({
  permission,
  scope,
  fallback = null,
  children,
}: {
  permission: string;
  scope?: string;
  fallback?: React.ReactNode;
  children: React.ReactNode;
}) {
  const { can } = usePermissions();
  return can(permission, scope) ? <>{children}</> : <>{fallback}</>;
}
