"use client";

import { usePathname } from "next/navigation";
import Link from "next/link";
import { ThemeToggle } from "@/components/theme-toggle";
import { ClipboardList, Heart, History, LayoutDashboard, Utensils, UtensilsCrossed, Users } from "lucide-react";
import { UserNav } from "@/components/user-nav";

const mainNav = [
  { title: "Participants", href: "/dashboard/users", icon: Users },
  { title: "Diet Logs", href: "/dashboard/logs/food", icon: Utensils },
  { title: "Image Review", href: "/dashboard/feedback", icon: Heart },
  { title: "Sessions", href: "/dashboard/sessions", icon: History },
];

export function DashboardHeader({ role }: { role: string }) {
  const pathname = usePathname();
  const isCoordinator = role === "coordinator" || role === "admin";
  const isRecommendations = pathname === "/dashboard/recommendations";
  const isPreferences = pathname === "/dashboard/preferences";

  return (
    <header className="shrink-0 border-b bg-card/90 backdrop-blur-xl">
      <div className="flex min-h-16 items-center gap-4 px-4 sm:px-6 lg:px-8">
        <Link href="/dashboard/users" className="flex shrink-0 items-center gap-3">
          <span className="flex h-10 w-10 items-center justify-center rounded-2xl bg-primary text-primary-foreground shadow-sm shadow-black/10">
            <UtensilsCrossed className="h-4 w-4" />
          </span>
          <span className="min-w-0">
            <span className="block text-base font-semibold tracking-tight">ADAM</span>
            <span className="block text-[10px] font-medium uppercase tracking-[0.18em] text-muted-foreground">{role}</span>
          </span>
        </Link>

        {isCoordinator && (
          <nav className="hidden min-w-0 flex-1 items-center justify-center gap-1 lg:flex">
            {mainNav.map((item) => {
              const active = pathname === item.href;
              return (
                <Link
                  key={item.href}
                  href={item.href}
                className={`inline-flex h-9 items-center gap-2 rounded-lg px-3 text-sm font-medium transition-colors ${
                  active
                      ? "bg-accent text-accent-foreground"
                      : "text-muted-foreground hover:bg-muted hover:text-foreground"
                  }`}
                >
                  <item.icon className="h-4 w-4" />
                  {item.title}
                </Link>
              );
            })}
            {isRecommendations && (
              <span className="inline-flex h-9 items-center gap-2 rounded-lg bg-accent px-3 text-sm font-medium text-accent-foreground">
                <LayoutDashboard className="h-4 w-4" />
                View Plan
              </span>
            )}
            {isPreferences && (
              <span className="inline-flex h-9 items-center gap-2 rounded-lg bg-accent px-3 text-sm font-medium text-accent-foreground">
                <ClipboardList className="h-4 w-4" />
                Preferences
              </span>
            )}
          </nav>
        )}

        <div className="ml-auto flex items-center gap-2">
          <ThemeToggle />
          <UserNav />
        </div>
      </div>

      {isCoordinator && (
        <div className="overflow-x-auto border-t px-4 py-2 lg:hidden">
          <nav className="flex w-max gap-1">
            {mainNav.map((item) => {
              const active = pathname === item.href;
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  className={`inline-flex h-9 items-center gap-2 rounded-lg px-3 text-sm font-medium transition-colors ${
                    active
                      ? "bg-accent text-accent-foreground"
                      : "text-muted-foreground hover:bg-muted hover:text-foreground"
                  }`}
                >
                  <item.icon className="h-4 w-4" />
                  {item.title}
                </Link>
              );
            })}
          </nav>
        </div>
      )}

    </header>
  );
}
