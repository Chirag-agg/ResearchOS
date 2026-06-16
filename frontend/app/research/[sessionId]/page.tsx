import { ResearchWorkspace } from "@/components/research/ResearchWorkspace";
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
      <main className="mx-auto flex min-h-screen w-full flex-col items-center px-4 py-12 sm:px-6 lg:px-8">
        <ResearchWorkspace sessionId={sessionId} />
      </main>
    </GradientBackground>
  );
}
