import Link from "next/link";

export function AppShell({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-screen flex-col">
      <header className="border-border border-b">
        <div className="mx-auto flex h-12 max-w-5xl items-center justify-between px-8">
          <Link href="/" className="flex items-center gap-2">
            <span className="bg-primary size-1.5 rounded-full" aria-hidden />
            <span className="font-heading text-sm font-medium tracking-tight">bahlily</span>
          </Link>
          <span className="eyebrow text-muted-foreground hidden sm:inline">
            meeting intelligence
          </span>
        </div>
      </header>
      <div className="flex-1">{children}</div>
    </div>
  );
}
