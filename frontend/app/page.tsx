import { Microscope } from "lucide-react";
import { ResearchForm } from "@/components/research/ResearchForm";
import { GradientBackground } from "@/components/layout/GradientBackground";

export default function HomePage() {
  return (
    <GradientBackground>
      <main className="mx-auto flex min-h-screen w-full max-w-[1200px] flex-col items-center justify-center px-4 py-12 sm:px-6 lg:px-8">
        <div className="w-full max-w-3xl space-y-8">
          <header className="space-y-4 text-center">
            <div className="mx-auto flex w-fit items-center gap-2 rounded-full border border-white/10 bg-white/5 px-4 py-2 backdrop-blur-md">
              <Microscope className="h-5 w-5 text-primary" />
              <span className="text-sm font-semibold tracking-wide text-foreground">
                ResearchOS
              </span>
            </div>

            <div className="space-y-3">
              <h1 className="text-3xl font-semibold tracking-tight text-foreground sm:text-4xl md:text-5xl">
                What do you want to research?
              </h1>
              <p className="mx-auto max-w-xl text-base text-muted-foreground sm:text-lg">
                Run autonomous multi-step research locally with complete
                transparency.
              </p>
            </div>
          </header>

          <section className="glass-card p-6 sm:p-8">
            <ResearchForm />
          </section>
        </div>
      </main>
    </GradientBackground>
  );
}
