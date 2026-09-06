import { backendJson } from "@/lib/backend";
import { createClient } from "@/lib/supabase/server";
import { UsersClient, type UsersPageParticipant } from "./users-client";

export default async function UsersPage() {
  const supabase = await createClient();
  const {
    data: { session },
  } = await supabase.auth.getSession();
  const isAdmin = session?.user.email === "test@example.com";
  const auth = session?.access_token ? { Authorization: `Bearer ${session.access_token}` } : undefined;

  let participants: UsersPageParticipant[] = [];
  let error: string | null = null;

  try {
    const data = await backendJson<UsersPageParticipant[]>("/api/v1/users", { headers: auth });
    participants = isAdmin ? data : data.filter((p) => p.participant_id?.toUpperCase().startsWith("A"));
  } catch {
    error = "Failed to load participants";
  }

  return (
    <UsersClient
      initialParticipants={participants}
      initialIsAdmin={isAdmin}
      initialError={error}
    />
  );
}
