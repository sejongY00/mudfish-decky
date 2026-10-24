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
}

export const getState = callable<[], VpnState>("get_state");
export const connect = callable<[], VpnState>("connect");
export const disconnect = callable<[], VpnState>("disconnect");
export const setNode = callable<[choice: string], VpnState>("set_node");
export const listNodes = callable<[], NodeInfo[]>("list_nodes");
export const startLogin = callable<[], VpnState>("start_login");
export const stopLogin = callable<[], VpnState>("stop_login");
