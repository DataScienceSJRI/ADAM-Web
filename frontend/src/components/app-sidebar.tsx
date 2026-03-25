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
import { LayoutDashboard, UtensilsCrossed, Heart, ClipboardList, CalendarDays, History } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { UserNav } from "./user-nav";

const navItems = [
  { title: "Onboarding", href: "/onboarding", icon: ClipboardList },
  { title: "Preferences", href: "/dashboard/preferences", icon: Heart },
  { title: "My Plans", href: "/dashboard/plan", icon: CalendarDays },
  { title: "Recommendations", href: "/dashboard/recommendations", icon: LayoutDashboard },
  { title: "Session History", href: "/dashboard/sessions", icon: History },
];

export function AppSidebar() {
  const pathname = usePathname();

  return (
    <Sidebar>
      <SidebarHeader className="p-4">
        <div className="flex items-center gap-2">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary text-primary-foreground">
            <UtensilsCrossed className="h-4 w-4" />
          </div>
          <span className="text-lg font-semibold tracking-tight">ADAM</span>
        </div>
      </SidebarHeader>

      <SidebarContent>
        <SidebarGroup>
          <SidebarGroupLabel>Navigation</SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu>
              {navItems.map((item) => (
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
      </SidebarContent>

      <SidebarFooter className="p-4">
        <UserNav />
      </SidebarFooter>
    </Sidebar>
  );
}
