export default function UnauthorizedPage() {
  return (
    <div className="min-h-screen flex items-center justify-center bg-background">
      <div className="text-center space-y-3 max-w-sm px-4">
        <p className="text-4xl font-bold">403</p>
        <p className="text-lg font-semibold">Access restricted</p>
        <p className="text-sm text-muted-foreground">
          This web portal is for study coordinators only. Please use the ADAM mobile app to view your meal plan.
        </p>
      </div>
    </div>
  );
}
