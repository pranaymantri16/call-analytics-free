import AuditHistory from "@/components/AuditHistory";
export default function CallAudit({ params }: { params: { id: string } }) {
  return <AuditHistory key={params.id} callId={params.id} />;
}
