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
  LayoutDashboard,
  UtensilsCrossed,
  Heart,
  ClipboardList,
  CalendarDays,
  History,
  Users,
  UserPlus,
  SlidersHorizontal,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { UserNav } from "./user-nav";

const studyItems = [
  { title: "Users", href: "/dashboard/users", icon: Users },
  { title: "Add New User", href: "/dashboard/users/new", icon: UserPlus },
  { title: "Preferences", href: "/dashboard/preferences", icon: SlidersHorizontal },
];

const planItems = [
  { title: "Recommendations", href: "/dashboard/recommendations", icon: LayoutDashboard },
  { title: "My Plans", href: "/dashboard/plan", icon: CalendarDays },
  { title: "Session History", href: "/dashboard/sessions", icon: History },
];

const setupItems = [
  { title: "Onboarding", href: "/onboarding", icon: ClipboardList },
  { title: "Preferences", href: "/dashboard/preferences", icon: Heart },
];

export function AppSidebar({ role }: { role: string }) {
  const pathname = usePathname();
  const isCoordinator = role === "coordinator" || role === "admin";

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
          <SidebarGroup>
            <SidebarGroupLabel>Study Management</SidebarGroupLabel>
            <SidebarGroupContent>
              <SidebarMenu>
                {studyItems.map((item) => (
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
        )}

        <SidebarGroup>
          <SidebarGroupLabel>Meal Plans</SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu>
              {planItems.map((item) => (
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

        {!isCoordinator && (
          <SidebarGroup>
            <SidebarGroupLabel>Profile & Setup</SidebarGroupLabel>
            <SidebarGroupContent>
              <SidebarMenu>
                {setupItems.map((item) => (
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
        )}
      </SidebarContent>

      <SidebarFooter className="p-4">
        <UserNav />
      </SidebarFooter>
    </Sidebar>
  );
}
