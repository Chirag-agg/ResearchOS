import { LiveResearchMonitor } from "@/components/research/LiveResearchMonitor";
import { GradientBackground } from "@/components/layout/GradientBackground";

interface SessionPageProps {
  params: Promise<{
    sessionId: string;
  }>;
}

export default async function SessionPage({ params }: SessionPageProps) {
  const { sessionId } = await params;

  return (
    <GradientBackground>
      <main className="mx-auto flex min-h-screen w-full flex-col items-center justify-center px-4 py-12 sm:px-6 lg:px-8">
        <LiveResearchMonitor sessionId={sessionId} />
      </main>
    </GradientBackground>
  );
}
