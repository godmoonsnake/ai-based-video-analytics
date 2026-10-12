/**
 * Camera "kind" chips derived from the registry display name, e.g.
 * "Gate 3 (Entry)" -> entry, "Restricted 2" -> restricted.
 * Pure heuristic for presentation only.
 */
export function camKindChip(name: string): string {
  const n = name.toLowerCase();
  if (n.includes("restrict") || n.includes("vault") || n.includes("server")) return "restricted";
  if (n.includes("entry") || n.includes("gate") || n.includes("entrance")) return "entry";
  if (n.includes("exit")) return "exit";
  if (n.includes("transit") || n.includes("corridor") || n.includes("hall")) return "transit";
  return "area";
}
