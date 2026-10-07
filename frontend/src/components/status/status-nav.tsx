import Link from "next/link";

const LINKS = [
  { key: "compliance", label: "Compliance", href: "/status" },
  { key: "recipe-issues", label: "Recipe Issues", href: "/status/recipe-issues" },
] as const;

export function StatusNav({ active }: { active: (typeof LINKS)[number]["key"] }) {
  return (
    <header className="border-b bg-card">
      <nav className="max-w-7xl mx-auto px-6 h-12 flex items-center gap-6">
        <span className="text-sm font-semibold tracking-tight">ADAM</span>
        <div className="flex items-center gap-1">
          {LINKS.map((link) => {
            const isActive = link.key === active;
            return (
              <Link
                key={link.key}
                href={link.href}
                aria-current={isActive ? "page" : undefined}
                className={`px-2.5 py-1 text-xs font-medium rounded-md transition-colors ${
                  isActive
                    ? "bg-muted text-foreground"
                    : "text-muted-foreground hover:bg-muted/60 hover:text-foreground"
                }`}
              >
                {link.label}
              </Link>
            );
          })}
        </div>
      </nav>
    </header>
  );
}
