import { NetworkShell } from "@/components/dashboard/network-shell";
export default function OperationsLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return <NetworkShell>{children}</NetworkShell>;
}
