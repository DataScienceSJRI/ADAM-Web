import { backendJson } from "@/lib/backend";
import { createClient } from "@/lib/supabase/server";
import { OutsideFoodClient, type FlaggedParticipant } from "./outside-food-client";

export default async function OutsideFoodPage() {
  const supabase = await createClient();
  const {
    data: { session },
  } = await supabase.auth.getSession();
  const auth = session?.access_token ? { Authorization: `Bearer ${session.access_token}` } : undefined;

  let flagged: FlaggedParticipant[] = [];
  let error: string | null = null;

  try {
    flagged = await backendJson<FlaggedParticipant[]>("/api/v1/outside-foods/flagged", { headers: auth });
  } catch {
    error = "Failed to load flagged participants";
  }

  return <OutsideFoodClient initialFlagged={flagged} initialError={error} />;
}
