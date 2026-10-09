/**
 * Which landing page `/` is.
 *
 * The one place in the console that branches on `product_mode`. Keeping it to one place
 * is the point: the alternative is the same conditional in the route table, the shell,
 * the home screen and three feature layouts, which is how two navigations came to
 * disagree about which product was primary.
 *
 * Both screens are lazy so that an assurance install does not download the ledger home
 * and a ledger install does not download the charting the assurance overview needs.
 */

import { Suspense, lazy } from "react";
import { TableSkeleton } from "@/components/Skeleton";
import { useProductMode } from "@/features/auth/bootstrapContext";

const LedgerHomeScreen = lazy(() => import("./LedgerHomeScreen"));
const AssuranceHomeScreen = lazy(() => import("./HomeScreen"));

export default function HomeRoute() {
  const mode = useProductMode();
  const Screen = mode === "assurance" ? AssuranceHomeScreen : LedgerHomeScreen;

  return (
    <Suspense fallback={<TableSkeleton rows={6} cols={4} />}>
      <Screen />
    </Suspense>
  );
}
