import { StoryList } from "@/components/StoryList";

export default function HomePage() {
  return (
    <main className="relative mx-auto flex min-h-screen w-full max-w-4xl flex-col px-6 py-12 md:py-16">
      <div className="pointer-events-none absolute inset-0 -z-10 overflow-hidden">
        <div className="absolute left-[-10%] top-[20%] h-72 w-72 rounded-full bg-primary/10 blur-3xl" />
        <div className="absolute bottom-[10%] right-[-5%] h-80 w-80 rounded-full bg-accent/10 blur-3xl" />
      </div>
      <StoryList />
    </main>
  );
}
