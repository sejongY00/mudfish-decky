import { callable } from "@decky/api";

export type Phase = "off" | "connecting" | "on" | "error" | "missing";

export interface NodeInfo {
  sid: number;
  label: string;
  rtt: number | null;
}

export interface VpnState {
  phase: Phase;
  message: string | null;
  node_mode: "auto" | "manual";
  node: NodeInfo | null;
  ip: string | null;
  country: string | null;
  connected_since: number | null;
  tunnel: boolean;
  need_login: boolean;
  login: { url: string; expires_at: number } | null;
  mudfish: { version: string | null; latest: string | null } | null;
}

export const getState = callable<[], VpnState>("get_state");
export const connect = callable<[], VpnState>("connect");
export const disconnect = callable<[], VpnState>("disconnect");
export const setNode = callable<[choice: string], VpnState>("set_node");
export const listNodes = callable<[], NodeInfo[]>("list_nodes");
export const startLogin = callable<[], VpnState>("start_login");
export const stopLogin = callable<[], VpnState>("stop_login");
export const installMudfish = callable<[], VpnState>("install_mudfish");
export const updateMudfish = callable<[], VpnState>("update_mudfish");
export const uninstallMudfish = callable<[], VpnState>("uninstall_mudfish");

/** True when version `a` is newer than `b` (dotted numeric versions). */
export function isNewer(a: string | null | undefined, b: string | null | undefined): boolean {
  if (!a || !b) return false;
  const pa = a.split(".").map(Number);
  const pb = b.split(".").map(Number);
  for (let i = 0; i < Math.max(pa.length, pb.length); i++) {
    const d = (pa[i] ?? 0) - (pb[i] ?? 0);
    if (d !== 0) return d > 0;
  }
  return false;
}
