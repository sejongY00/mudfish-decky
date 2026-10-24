import { DialogButton, ModalRoot } from "@decky/ui";
import qrcode from "qrcode-generator";
import { ReactElement, useEffect, useState } from "react";
import { getState, startLogin, stopLogin, VpnState } from "./backend";

const POLL_MS = 2000;

function QrSvg({ text, size }: { text: string; size: number }) {
  const qr = qrcode(0, "M");
  qr.addData(text);
  qr.make();
  const count = qr.getModuleCount();
  const quiet = 2;
  const cells: ReactElement[] = [];
  for (let r = 0; r < count; r++) {
    for (let c = 0; c < count; c++) {
      if (qr.isDark(r, c)) cells.push(<rect key={`${r}-${c}`} x={c + quiet} y={r + quiet} width={1} height={1} />);
    }
  }
  const dim = count + quiet * 2;
  return (
    <svg width={size} height={size} viewBox={`0 0 ${dim} ${dim}`} shapeRendering="crispEdges">
      <rect width={dim} height={dim} fill="#fff" />
      <g fill="#000">{cells}</g>
    </svg>
  );
}

function remaining(expiresAt: number): string {
  const s = Math.max(0, Math.round(expiresAt - Date.now() / 1000));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

export function LoginModal({ closeModal }: { closeModal?: () => void }) {
  const [state, setState] = useState<VpnState | null>(null);
  const [, tick] = useState(0);

  useEffect(() => {
    let alive = true;
    startLogin().then((s) => alive && setState(s));
    const id = setInterval(async () => {
      try {
        const s = await getState();
        if (!alive) return;
        setState(s);
        if (!s.need_login) closeModal?.(); // logged in: backend already closed the relay
      } catch (e) {
        console.error("mudfish: getState failed", e);
      }
      tick((n) => n + 1);
    }, POLL_MS);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, []);

  const cancel = () => {
    stopLogin();
    closeModal?.();
  };

  const login = state?.login;
  return (
    <ModalRoot onCancel={cancel} closeModal={cancel}>
      <div style={{ display: "flex", gap: "24px", alignItems: "center" }}>
        <div style={{ flex: "0 0 auto" }}>
          {login ? <QrSvg text={login.url} size={240} /> : <div style={{ width: 240, height: 240 }} />}
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: "10px" }}>
          <div style={{ fontSize: "20px", fontWeight: "bold" }}>휴대폰으로 미꾸라지 로그인</div>
          {login ? (
            <>
              <div>1. 스팀덱과 같은 와이파이에 연결된 휴대폰으로 QR을 찍으세요.</div>
              <div>2. 열린 미꾸라지 화면에서 <b>'로그인 기억하기'를 체크</b>하고 로그인하세요.</div>
              <div>3. 로그인이 확인되면 이 창은 자동으로 닫혀요.</div>
              <div style={{ opacity: 0.6, fontSize: "12px", wordBreak: "break-all" }}>{login.url}</div>
              <div style={{ opacity: 0.8 }}>{`남은 시간 ${remaining(login.expires_at)} · 처음 QR을 찍은 휴대폰만 접속할 수 있어요`}</div>
            </>
          ) : (
            <div>{state?.message ?? "로그인 창을 여는 중…"}</div>
          )}
          <DialogButton onClick={cancel}>닫기</DialogButton>
        </div>
      </div>
    </ModalRoot>
  );
}
