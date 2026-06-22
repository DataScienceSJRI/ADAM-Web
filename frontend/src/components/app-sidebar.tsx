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
      <SidebarHeader className="p-4">
        <div className="flex items-center gap-2">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary text-primary-foreground">
            <UtensilsCrossed className="h-4 w-4" />
          </div>
          <div>
            <span className="text-lg font-semibold tracking-tight">ADAM</span>
            {isCoordinator && (
              <p className="text-[10px] text-muted-foreground capitalize">{role}</p>
            )}
          </div>
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

      <SidebarFooter className="p-4 space-y-3">
        <UserNav />
        {process.env.NEXT_PUBLIC_APP_VERSION && (
          <p className="text-[10px] text-muted-foreground text-center select-none">
            v{process.env.NEXT_PUBLIC_APP_VERSION}
          </p>
        )}
      </SidebarFooter>
    </Sidebar>
  );
}
