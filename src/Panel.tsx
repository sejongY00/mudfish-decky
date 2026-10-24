import {
  ButtonItem,
  ConfirmModal,
  DropdownItem,
  Field,
  PanelSection,
  PanelSectionRow,
  showModal,
  ToggleField,
} from "@decky/ui";
import { toaster } from "@decky/api";
import { LoginModal } from "./LoginModal";
import { useEffect, useRef, useState } from "react";
import {
  connect,
  disconnect,
  getState,
  installMudfish,
  isNewer,
  listNodes,
  uninstallMudfish,
  updateMudfish,
  NodeInfo,
  Phase,
  PluginRelease,
  pluginRelease,
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

/** Copy via a hidden textarea (works in Steam's CEF where navigator.clipboard is often blocked). */
function copyText(text: string): boolean {
  const el = document.createElement("textarea");
  el.value = text;
  el.style.position = "fixed";
  el.style.opacity = "0";
  document.body.appendChild(el);
  el.focus();
  el.select();
  let ok = false;
  try {
    ok = document.execCommand("copy");
  } catch {
    ok = false;
  }
  el.remove();
  if (!ok) navigator.clipboard?.writeText(text).catch(() => undefined);
  return ok;
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
  const [release, setRelease] = useState<PluginRelease | null>(null);
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
    // Fetch ahead of time so the copy happens synchronously inside the button press.
    if (advanced) pluginRelease().then(setRelease).catch(() => setRelease(null));
  }, [advanced]);

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
  const version = state.mudfish?.version ?? null;
  const latest = state.mudfish?.latest ?? null;
  const missing = state.phase === "missing";

  const confirmUninstall = () =>
    showModal(
      <ConfirmModal
        strTitle="미꾸라지 제거"
        strDescription="VPN을 끄고 미꾸라지(/opt/mudfish 전체, 로그인 정보 포함)와 이 플러그인의 설정을 지워요. 미꾸라지 계정은 그대로예요."
        strOKButtonText="제거"
        strCancelButtonText="취소"
        onOK={() => run(uninstallMudfish)}
      />,
    );

  const copyLatestUrl = () => {
    const latest = release?.latest;
    if (!latest) return;
    const copied = copyText(latest.url);
    toaster.toast({
      title: "Mudfish VPN",
      body: copied
        ? `v${latest.version} 주소를 복사했어요. 데키 설정 → Install Plugin from URL에 붙여 넣으세요`
        : `복사하지 못했어요: ${latest.url}`,
    });
  };

  if (missing) {
    return (
      <PanelSection>
        <PanelSectionRow>
          <Field label="상태" focusable={false}>
            <StatusValue state={state} />
          </Field>
        </PanelSectionRow>
        {state.message && (
          <PanelSectionRow>
            <Field focusable={false} description={state.message} />
          </PanelSectionRow>
        )}
        <PanelSectionRow>
          <ButtonItem layout="below" disabled={busy} onClick={() => run(installMudfish)}>
            {busy ? "설치 중… (1~2분)" : `미꾸라지 설치${latest ? ` (${latest})` : ""}`}
          </ButtonItem>
        </PanelSectionRow>
      </PanelSection>
    );
  }

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
      {state.need_login && (
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={() => showModal(<LoginModal />)}>
            휴대폰으로 로그인 (QR)
          </ButtonItem>
        </PanelSectionRow>
      )}
      <PanelSectionRow>
        <ButtonItem layout="below" onClick={() => setAdvanced(!advanced)}>
          {advanced ? "고급 ▾" : "고급 ▸"}
        </ButtonItem>
      </PanelSectionRow>
      {advanced && (
        <>
          <PanelSectionRow>
            <DropdownItem
              label="일본 노드"
              rgOptions={options}
              selectedOption={selected}
              disabled={busy || state.phase === "connecting"}
              onChange={(opt) => run(() => setNode(String(opt.data)))}
            />
          </PanelSectionRow>
          <PanelSectionRow>
            <Field label="미꾸라지" focusable={false}>
              {version ?? "?"}
              {latest && !isNewer(latest, version) ? " (최신)" : ""}
            </Field>
          </PanelSectionRow>
          {isNewer(latest, version) && (
            <PanelSectionRow>
              <ButtonItem layout="below" disabled={busy || active} onClick={() => run(updateMudfish)}>
                {busy ? "업데이트 중…" : `미꾸라지 업데이트 (${version} → ${latest})`}
              </ButtonItem>
            </PanelSectionRow>
          )}
          <PanelSectionRow>
            <ButtonItem layout="below" disabled={busy} onClick={confirmUninstall}>
              미꾸라지 제거
            </ButtonItem>
          </PanelSectionRow>
          <PanelSectionRow>
            <Field label="플러그인" focusable={false}>
              {release ? `v${release.current}` : "…"}
              {release?.latest
                ? isNewer(release.latest.version, release.current)
                  ? ` · 최신 v${release.latest.version}`
                  : " (최신)"
                : ""}
            </Field>
          </PanelSectionRow>
          <PanelSectionRow>
            <ButtonItem layout="below" disabled={!release?.latest} onClick={copyLatestUrl}>
              최신 플러그인 주소 복사
            </ButtonItem>
          </PanelSectionRow>
        </>
      )}
    </PanelSection>
  );
}
