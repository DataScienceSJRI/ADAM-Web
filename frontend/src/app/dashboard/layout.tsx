import { SidebarInset, SidebarProvider } from "@/components/ui/sidebar";
import { AppSidebar } from "@/components/app-sidebar";
import { DashboardHeader } from "@/components/dashboard-header";
import { createClient } from "@/lib/supabase/server";
import { redirect } from "next/navigation";

export default async function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const supabase = await createClient();
  let user = null;
  try {
    const { data } = await supabase.auth.getUser();
    user = data.user;
  } catch {
    try {
      const { data } = await supabase.auth.getSession();
      user = data.session?.user ?? null;
    } catch {}
  }

  if (!user) {
    redirect("/login");
  }

  const { data: roleData } = await supabase
    .from("UserRoles")
    .select("role")
    .eq("user_id", user.email!)
    .limit(1)
    .maybeSingle();

  const role = roleData?.role ?? "participant";

  if (role === "participant") {
    redirect("/unauthorized");
  }

  return (
    <SidebarProvider className="h-screen overflow-hidden">
      <AppSidebar role={role} />
      <SidebarInset className="flex flex-col min-h-0">
        <DashboardHeader />
        <main className="flex-1 overflow-y-auto p-6">{children}</main>
      </SidebarInset>
    </SidebarProvider>
  );
}
