import { Suspense } from "react";
import Workspace from "@/components/Workspace";

export default async function HouseholdPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return (
    <Suspense fallback={null}>
      <Workspace id={id} />
    </Suspense>
  );
}
