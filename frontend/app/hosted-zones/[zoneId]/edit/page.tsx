import Route53Console from "@/components/Route53Console";

export const instant = false;

export default async function EditHostedZonePage({
  params,
}: {
  params: Promise<{ zoneId: string }>;
}) {
  const { zoneId } = await params;
  return <Route53Console key={`edit-zone-${zoneId}`} view="edit-zone" zoneId={zoneId} />;
}
