"use client";

import { usePathname } from "next/navigation";
import { SidebarTrigger } from "@/components/ui/sidebar";
import { Separator } from "@/components/ui/separator";
import { ThemeToggle } from "@/components/theme-toggle";

const PAGE_TITLES: Record<string, string> = {
  "/dashboard/recommendations": "Recommendations",
  "/dashboard/plan": "My Plans",
  "/dashboard/preferences": "Preferences",
  "/dashboard/sessions": "Session History",
  "/onboarding": "Onboarding",
};

export function DashboardHeader() {
  const pathname = usePathname();
  const title = PAGE_TITLES[pathname] ?? "Dashboard";

  return (
    <header className="flex h-14 shrink-0 items-center gap-2 border-b px-4">
      <SidebarTrigger className="-ml-1" />
      <Separator orientation="vertical" className="mr-2 h-4" />
      <span className="text-sm font-medium">{title}</span>
      <div className="ml-auto">
        <ThemeToggle />
      </div>
    </header>
  );
}
