export const human = (s: string) => s.replace(/[_-]/g, " ");
export const liters = (n?: number | null) =>
  n == null
    ? "—"
    : `${n.toLocaleString("en-BD", { maximumFractionDigits: 0 })} L`;
export function Panel({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-5 sm:p-6">
      <h2 className="mb-4 text-lg font-semibold">{title}</h2>
      {children}
    </section>
  );
}
