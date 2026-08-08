import Link from "next/link";

export function Nav() {
  return (
    <header className="border-border sticky top-0 z-10 border-b bg-background/95 backdrop-blur">
      <div className="mx-auto flex h-14 max-w-6xl items-center justify-between px-6">
        <Link href="/" className="flex items-center gap-2">
          <span className="bg-primary size-1.5 rounded-full" aria-hidden />
          <span className="font-heading text-sm font-medium tracking-tight">
            bahlily
          </span>
        </Link>
        <nav className="flex items-center gap-6">
          <a
            href="#features"
            className="text-muted-foreground hover:text-foreground text-sm transition-colors"
          >
            Features
          </a>
          <a
            href="https://github.com/harunnryd/bahlily"
            className="text-muted-foreground hover:text-foreground text-sm transition-colors"
          >
            GitHub
          </a>
          <a
            href="#waitlist"
            className="bg-primary text-primary-foreground hover:bg-primary/90 rounded-md px-3 py-1.5 text-sm font-medium transition-colors"
          >
            Join waitlist
          </a>
        </nav>
      </div>
    </header>
  );
}
