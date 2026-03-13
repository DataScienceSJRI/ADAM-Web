export default function OnboardingLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="min-h-screen bg-muted/40 flex items-start justify-center px-4 py-12">
      <div className="w-full max-w-2xl">{children}</div>
    </div>
  );
}
