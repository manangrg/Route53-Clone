import Route53Console from "@/components/Route53Console";

export const instant = false;

export default async function CreateRecordPage({
  params,
}: {
  params: Promise<{ zoneId: string }>;
}) {
  const { zoneId } = await params;
  return <Route53Console key={`create-record-${zoneId}`} view="create-record" zoneId={zoneId} />;
}
