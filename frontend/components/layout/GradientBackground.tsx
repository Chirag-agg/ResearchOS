interface GradientBackgroundProps {
  children: React.ReactNode;
}

export function GradientBackground({ children }: GradientBackgroundProps) {
  return (
    <div className="relative min-h-screen overflow-hidden bg-black">
      <div
        className="animate-gradient-shift pointer-events-none absolute inset-0 bg-gradient-to-br from-purple-900/80 via-blue-900/60 to-black"
        aria-hidden="true"
      />
      <div
        className="animate-float-orb-1 pointer-events-none absolute -left-32 top-1/4 h-96 w-96 rounded-full bg-purple-600/30 blur-3xl"
        aria-hidden="true"
      />
      <div
        className="animate-float-orb-2 pointer-events-none absolute -right-32 bottom-1/4 h-96 w-96 rounded-full bg-blue-600/25 blur-3xl"
        aria-hidden="true"
      />
      <div
        className="pointer-events-none absolute inset-0 bg-[radial-gradient(ellipse_at_center,transparent_0%,rgba(0,0,0,0.4)_70%,rgba(0,0,0,0.8)_100%)]"
        aria-hidden="true"
      />
      <div className="relative z-10">{children}</div>
    </div>
  );
}
