import Route53Console from "@/components/Route53Console";

export const instant = false;

export default async function HostedZoneDetailPage({
  params,
}: {
  params: Promise<{ zoneId: string }>;
}) {
  const { zoneId } = await params;
  return <Route53Console key={`zone-${zoneId}`} view="detail" zoneId={zoneId} />;
}
