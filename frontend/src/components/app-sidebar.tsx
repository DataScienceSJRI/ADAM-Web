"use client";

import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
} from "@/components/ui/sidebar";
import {
  UtensilsCrossed,
  ClipboardList,
  History,
  Users,
  LayoutDashboard,
  Heart,
  Utensils,
  Activity,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { UserNav } from "./user-nav";

const participantItems = [
  { title: "Participants", href: "/dashboard/users", icon: Users },
];

const logItems = [
  { title: "Diet Logs", href: "/dashboard/logs/food", icon: Utensils },
  { title: "Image Review", href: "/dashboard/feedback", icon: Heart },
  { title: "Session History", href: "/dashboard/sessions", icon: History },
];

export function AppSidebar({ role }: { role: string }) {
  const pathname = usePathname();
  const isCoordinator = role === "coordinator" || role === "admin";

  // These pages are reached via in-page links, not sidebar nav directly.
  const isRecommendations = pathname === "/dashboard/recommendations";
  const isPreferences = pathname === "/dashboard/preferences";

  return (
    <Sidebar>
      <SidebarHeader className="border-b border-sidebar-border/70 p-4">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-2xl bg-sidebar-primary text-sidebar-primary-foreground shadow-sm shadow-black/20">
            <UtensilsCrossed className="h-4 w-4" />
          </div>
          <div className="min-w-0">
            <span className="block text-lg font-semibold tracking-tight">ADAM</span>
            {isCoordinator && (
              <p className="text-[10px] font-medium uppercase tracking-[0.18em] text-sidebar-foreground/55">{role}</p>
            )}
          </div>
        </div>
        <div className="mt-5 rounded-2xl border border-sidebar-border/80 bg-sidebar-accent/80 p-3">
          <div className="flex items-center gap-2 text-xs font-semibold text-sidebar-accent-foreground">
            <Activity className="h-3.5 w-3.5 text-sidebar-primary" />
            Care overview
          </div>
          <p className="mt-1 text-xs leading-relaxed text-sidebar-foreground/65">
            Participant plans, recalls, and signals at a glance.
          </p>
        </div>
      </SidebarHeader>

      <SidebarContent>
        {isCoordinator && (
          <>
            <SidebarGroup>
              <SidebarGroupLabel>Participants</SidebarGroupLabel>
              <SidebarGroupContent>
                <SidebarMenu>
                  {participantItems.map((item) => (
                    <SidebarMenuItem key={item.href}>
                      <SidebarMenuButton asChild isActive={pathname === item.href}>
                        <Link href={item.href}>
                          <item.icon className="h-4 w-4" />
                          <span>{item.title}</span>
                        </Link>
                      </SidebarMenuButton>
                    </SidebarMenuItem>
                  ))}
                  {/* Ghost entries — highlighted when navigated to via in-page links */}
                  {isRecommendations && (
                    <SidebarMenuItem>
                      <SidebarMenuButton isActive>
                        <LayoutDashboard className="h-4 w-4" />
                        <span>View Plan</span>
                      </SidebarMenuButton>
                    </SidebarMenuItem>
                  )}
                  {isPreferences && (
                    <SidebarMenuItem>
                      <SidebarMenuButton isActive>
                        <ClipboardList className="h-4 w-4" />
                        <span>Preferences</span>
                      </SidebarMenuButton>
                    </SidebarMenuItem>
                  )}
                </SidebarMenu>
              </SidebarGroupContent>
            </SidebarGroup>

            <SidebarGroup>
              <SidebarGroupLabel>Logs</SidebarGroupLabel>
              <SidebarGroupContent>
                <SidebarMenu>
                  {logItems.map((item) => (
                    <SidebarMenuItem key={item.href}>
                      <SidebarMenuButton asChild isActive={pathname === item.href}>
                        <Link href={item.href}>
                          <item.icon className="h-4 w-4" />
                          <span>{item.title}</span>
                        </Link>
                      </SidebarMenuButton>
                    </SidebarMenuItem>
                  ))}
                </SidebarMenu>
              </SidebarGroupContent>
            </SidebarGroup>
          </>
        )}
      </SidebarContent>

      <SidebarFooter className="space-y-3 border-t border-sidebar-border/70 p-4">
        <UserNav />
        {process.env.NEXT_PUBLIC_APP_VERSION && (
          <p className="select-none text-center text-[10px] text-sidebar-foreground/45">
            v{process.env.NEXT_PUBLIC_APP_VERSION}
          </p>
        )}
      </SidebarFooter>
    </Sidebar>
  );
}
