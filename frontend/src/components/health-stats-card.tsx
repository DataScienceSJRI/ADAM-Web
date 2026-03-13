import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Activity, Droplets, Scale, User } from "lucide-react";

export type BasicDetails = {
  id: number;
  user_id: string | null;
  Age: number | null;
  Gender: string | null;
  Weight: number | null;
  Hba1c: number | null;
  Activity_levels: string | null;
  
};

export function HealthStatsCard({ details }: { details: BasicDetails }) {
  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="text-base font-semibold">Health Overview</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <Stat
            icon={<User className="h-4 w-4 text-blue-500" />}
            label="Age"
            value={details.Age ? `${details.Age} yrs` : "—"}
          />
          <Stat
            icon={<Scale className="h-4 w-4 text-green-500" />}
            label="Weight"
            value={details.Weight ? `${details.Weight} kg` : "—"}
          />
          <Stat
            icon={<Droplets className="h-4 w-4 text-red-500" />}
            label="HbA1c"
            value={details.Hba1c ? `${details.Hba1c}%` : "—"}
          />
          <Stat
            icon={<Activity className="h-4 w-4 text-orange-500" />}
            label="Activity"
            value={details.Activity_levels ?? "—"}
          />
        </div>
      </CardContent>
    </Card>
  );
}

function Stat({
  icon,
  label,
  value,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
}) {
  return (
    <div className="flex flex-col items-center gap-1.5 rounded-lg bg-muted/50 px-3 py-3 text-center">
      {icon}
      <span className="text-sm font-semibold">{value}</span>
      <span className="text-[11px] text-muted-foreground">{label}</span>
    </div>
  );
}
