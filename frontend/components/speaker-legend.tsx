import { Badge } from "@/components/ui/badge";

export interface SpeakerLegendCluster {
  label: string;
  name: string | null;
}

export function SpeakerLegend({ clusters }: { clusters: SpeakerLegendCluster[] }) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      {clusters.map((cluster) => (
        <Badge key={cluster.label} variant="outline">
          {cluster.name ?? cluster.label}
        </Badge>
      ))}
    </div>
  );
}
