import {
  ButtonItem,
  DropdownItem,
  Field,
  PanelSection,
  PanelSectionRow,
  ToggleField,
} from "@decky/ui";
import { useEffect, useRef, useState } from "react";
import {
  connect,
  disconnect,
  getState,
  listNodes,
  NodeInfo,
  Phase,
  setNode,
  VpnState,
} from "./backend";

const PHASE_TEXT: Record<Phase, string> = {
  off: "꺼짐",
  connecting: "연결 중…",
  on: "연결됨",
  error: "오류",
  missing: "미꾸라지 미설치",
};

const STATE_POLL_MS = 2000;
const NODES_POLL_MS = 10000;

function elapsed(since: number, nowMs: number): string {
  const minutes = Math.floor((nowMs / 1000 - since) / 60);
  if (minutes < 1) return "방금";
  if (minutes < 60) return `${minutes}분째`;
  return `${Math.floor(minutes / 60)}시간 ${minutes % 60}분째`;
}

function rttText(rtt: number | null): string {
  return rtt === null ? "측정 안 됨" : `${Math.round(rtt)}ms`;
}

function nodeLine(state: VpnState): string {
  const node = state.node;
  if (!node) return "핑 측정 중…";
  const body = node.rtt === null ? node.label : `${node.label} (${Math.round(node.rtt)}ms)`;
  return state.node_mode === "auto" ? `자동 · ${body}` : body;
}

function StatusValue({ state }: { state: VpnState }) {
  if (state.phase !== "on") return <span>{PHASE_TEXT[state.phase]}</span>;
  const jp = state.country === "JP";
  const flag = jp ? "🇯🇵 JP" : state.country ?? "?";
  const since = state.connected_since ? ` · ${elapsed(state.connected_since, Date.now())}` : "";
  return (
    <span style={{ color: jp ? undefined : "#ff6b6b" }}>
      {`${PHASE_TEXT.on} · ${flag}${state.ip ? ` · ${state.ip}` : ""}${since}`}
    </span>
  );
}

export function Panel() {
  const [state, setState] = useState<VpnState | null>(null);
  const [busy, setBusy] = useState(false);
  const [advanced, setAdvanced] = useState(false);
  const [nodes, setNodes] = useState<NodeInfo[]>([]);
  const polling = useRef(false);
  const acting = useRef(false);

  const refresh = async () => {
    if (polling.current) return;
    polling.current = true;
    try {
      const next = await getState();
      // A poll that started before a toggle press would overwrite the action's result.
      if (!acting.current) setState(next);
    } catch (e) {
      console.error("mudfish: getState failed", e);
    } finally {
      polling.current = false;
    }
  };

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, STATE_POLL_MS);
    return () => clearInterval(id);
  }, []);

  useEffect(() => {
    if (!advanced) return;
    const load = async () => {
      try {
        setNodes(await listNodes());
      } catch (e) {
        console.error("mudfish: listNodes failed", e);
      }
    };
    load();
    const id = setInterval(load, NODES_POLL_MS);
    return () => clearInterval(id);
  }, [advanced]);

  const run = async (action: () => Promise<VpnState>, pending?: Phase) => {
    acting.current = true;
    setBusy(true);
    if (pending && state) setState({ ...state, phase: pending, message: null });
    try {
      setState(await action());
    } catch (e) {
      if (state) setState({ ...state, phase: "error", message: `요청 실패: ${e}` });
    } finally {
      acting.current = false;
      setBusy(false);
    }
  };

  if (!state) {
    return (
      <PanelSection>
        <PanelSectionRow>
          <Field label="상태">불러오는 중…</Field>
        </PanelSectionRow>
      </PanelSection>
    );
  }

  // Checked whenever any tunnel exists (even a stuck one), so the toggle can always turn it off.
  const active = state.tunnel || state.phase === "on" || state.phase === "connecting";
  const options = [
    { data: "auto", label: "자동 (핑 최저)" },
    ...nodes.map((n) => ({ data: String(n.sid), label: `${n.label} · ${rttText(n.rtt)}` })),
  ];
  const selected = state.node_mode === "auto" ? "auto" : String(state.node?.sid ?? "auto");

  return (
    <PanelSection>
      <PanelSectionRow>
        <Field label="상태" focusable={false}>
          <StatusValue state={state} />
        </Field>
      </PanelSectionRow>
      <PanelSectionRow>
        <ToggleField
          label="미꾸라지 Full VPN"
          checked={active}
          disabled={busy || state.phase === "missing"}
          onChange={(on) => run(on ? connect : disconnect, on ? "connecting" : undefined)}
        />
      </PanelSectionRow>
      <PanelSectionRow>
        <Field label="노드" focusable={false}>
          {nodeLine(state)}
        </Field>
      </PanelSectionRow>
      {state.message && (
        <PanelSectionRow>
          <Field focusable={false} description={state.message} />
        </PanelSectionRow>
      )}
      <PanelSectionRow>
        <ButtonItem layout="below" onClick={() => setAdvanced(!advanced)}>
          {advanced ? "고급 ▾" : "고급 ▸"}
        </ButtonItem>
      </PanelSectionRow>
      {advanced && (
        <PanelSectionRow>
          <DropdownItem
            label="일본 노드"
            rgOptions={options}
            selectedOption={selected}
            disabled={busy || state.phase === "connecting"}
            onChange={(opt) => run(() => setNode(String(opt.data)))}
          />
        </PanelSectionRow>
      )}
    </PanelSection>
  );
}
