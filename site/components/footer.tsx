export function Footer() {
  return (
    <footer className="border-border border-t">
      <div className="mx-auto flex h-14 max-w-6xl items-center justify-between px-6">
        <div className="flex items-center gap-2">
          <span className="bg-primary size-1.5 rounded-full" aria-hidden />
          <span className="font-heading text-sm font-medium tracking-tight">
            bahlily
          </span>
        </div>
        <div className="text-muted-foreground flex items-center gap-3 text-sm sm:gap-4">
          <a
            href="https://github.com/harunnryd/bahlily"
            className="hover:text-foreground transition-colors"
          >
            GitHub
          </a>
          <span className="hidden sm:inline">MIT licensed</span>
          <span>© 2026 Bahlily</span>
        </div>
      </div>
    </footer>
  );
}
