# 미꾸라지 Full VPN 데키 플러그인 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 게임모드 데키 패널에서 미꾸라지 Full VPN을 켜고 끄고, 일본 노드(기본 자동=핑 최저)를 고르는 플러그인을 만든다.

**Architecture:** Python 백엔드(`py_modules/mudfish_decky/`)가 미꾸라지 로컬 API(`127.0.0.1:8282`)와 클라우드 API(`api.mudfish.net`)를 호출해 데몬 상주, 자동 로그인, Full VPN 노드 지정, 연결/해제, 경로 정리를 맡는다. `main.py`는 이를 데키 `Plugin` 메서드로 노출한다. React 프론트엔드(`src/`)는 상태를 폴링해 그리고 사용자 조작을 전달하기만 한다. 순수 로직(노드 정렬, 경로 비교, 상태 판정)은 I/O와 분리해 단위 테스트한다.

**Tech Stack:** Decky Loader v3.3.0 플러그인 API v1 (`@decky/ui`, `@decky/api`, `@decky/rollup`, `import decky`), TypeScript/React, Python 3.11 호환 표준 라이브러리만, 테스트는 스팀덱의 `python3 -m unittest`.

**Spec:** `docs/superpowers/specs/2026-10-24-mudfish-decky-design.md`

## Global Constraints

- 스팀덱: `deck@192.168.1.50`(SSH 키 인증). 개발 중 sudo 비밀번호 없음 설정이 켜져 있다. 플러그인 코드는 sudo를 쓰지 않는다(백엔드는 root로 실행).
- `plugin.json`: `"name": "Mudfish VPN"`, `"flags": ["root"]`, `"api_version": 1`. 설치 폴더는 `~/homebrew/plugins/mudfish-decky/`.
- Python은 **3.11 문법까지만** 쓴다(데키 내장 파이썬 기준). 서드파티 패키지는 쓰지 않는다. `py_modules/`에는 우리 코드만 둔다.
- 미꾸라지 바이너리: `/opt/mudfish/<버전>/bin/mudrun-headless` 중 가장 높은 버전. 실행: `systemd-run --unit=mudfish-decky --collect <bin> -B`.
- 로컬 API 기본 주소는 `http://127.0.0.1:8282`. 실제 포트는 `/opt/mudfish/<버전>/var/.ipport`(`127.0.0.1:8282` 형식).
- 클라우드 API 호스트는 `status.api_server`(현재 `api.mudfish.net`), 인증 헤더는 `Authorization: <jwt>`(Bearer 없음).
- 일본 노드: `location`이 `"JP "`로 시작하는 staticNode. 표시 라벨은 괄호 안 문자열(예: `Tokyo - Linode3 IDC`).
- **코어(`/do/mudfish/start`)는 사용자가 켜기를 눌렀을 때만 시작한다.** `_main`, 절전 복귀, 상태 조회, 노드 선택 어떤 경로에서도 시작하지 않는다(노드 변경은 이미 연결된 상태에서만 재적용).
- 끄기를 눌러도 계정의 `mudfishFullvpnSid`는 지우지 않는다.
- 사용자에게 보이는 문구는 한국어다. 문구는 Task 6의 표에 있는 그대로 쓴다.
- 플러그인 설정 파일: `<DECKY_PLUGIN_SETTINGS_DIR>/settings.json`.

## Review Focus

1. **플러그인을 다시 불러오거나 재부팅했는데 VPN이 연결된 상태**: 자동으로 끄거나 켜지 않는다. 패널은 `on`과, 저장해 둔 연결 시각 기준의 경과 시간을 보여 준다. → Task 4 `test_state_on_survives_restart_uses_saved_since`
2. **부팅 직후 핑 측정 전에 자동 모드로 켜기**: 노드를 고를 수 없으면 코어를 시작하지 않고 안내 문구를 띄운다. → Task 4 `test_connect_auto_without_rtts_does_not_start`
3. **자동 로그인 토큰 만료**(signin이 200이 아님, 401 포함): 코어를 시작하지 않고 "데스크탑 모드에서 다시 로그인" 문구를 띄운다. → Task 4 `test_connect_signin_failure_shows_relogin`
4. **연결 시간 초과**(client_ready가 끝내 안 옴): 반쯤 켜진 상태로 남기지 않도록 stop을 호출하고 `error` 문구를 띄운다. → Task 4 `test_connect_timeout_stops_core`
5. **와이파이를 바꾼 뒤 끄기, 또는 시작 전 경로 스냅샷이 없을 때**: 스냅샷이 있으면 그 이후에 추가된 호스트 경로만 지우고, 없으면 아무것도 지우지 않는다. → Task 3 `test_leftover_routes_*`

---

## File Structure

```
mudfish-decky/
├─ plugin.json, package.json, rollup.config.js, tsconfig.json, .gitignore
├─ main.py                         # Decky Plugin 클래스: 비동기 래퍼만
├─ py_modules/mudfish_decky/
│  ├─ __init__.py
│  ├─ nodes.py                     # 일본 노드 필터·라벨·핑 정렬·자동 선택 (순수)
│  ├─ routes.py                    # `ip -4 route` 파싱·남은 경로 계산 (순수) + 삭제 실행
│  ├─ client.py                    # 로컬/클라우드 HTTP 호출 (주입 가능한 transport)
│  ├─ system.py                    # 바이너리 탐색, 데몬 기동, tap0 확인, 공인 IP 조회
│  ├─ store.py                     # settings.json 읽기/쓰기
│  └─ controller.py                # 연결/해제/상태/노드 선택 오케스트레이션
├─ tests/                          # unittest, 스팀덱에서 실행
│  ├─ test_nodes.py, test_routes.py, test_client.py, test_controller.py
├─ src/
│  ├─ index.tsx                    # definePlugin
│  ├─ Panel.tsx                    # 패널 UI
│  └─ backend.ts                   # callable 정의와 타입
└─ scripts/
   ├─ test.sh                      # py_modules+tests를 덱에 복사해 unittest 실행
   └─ deploy.sh                    # 빌드 산출물을 덱에 설치하고 plugin_loader 재시작
```

---

### Task 1: Full VPN 실측 (스파이크, 코드 없음)

스펙 9절의 검증 항목 1~3, 5~6을 덱에서 직접 확인한다. Task 4의 연결 절차가 이 결과에 의존한다. 미꾸라지 데몬은 현재 `mudfish-dev` unit으로 떠 있고 로그인된 상태다(로그인이 풀렸으면 스펙 4절 자동 로그인 절차를 덱에서 python3로 다시 실행).

**Files:**
- Modify: `docs/superpowers/specs/2026-10-24-mudfish-decky-design.md` (9절 아래에 "실측 결과" 하위 절 추가)

- [ ] **Step 1: 연결 전 기준값 기록**

Run (덱): `ip -4 route; resolvectl status | head -20; curl -s -m 8 https://ipinfo.io/json`
Expected: 기본 경로 `via 192.168.1.1 dev wlan0`, 국가 `KR`.

- [ ] **Step 2: sid를 핑 최저 일본 노드로 저장**

덱에서 python3 스크립트로 실행한다. graphql로 progConf 전체 필드(스펙 4절 목록)를 읽고 `mudfishFullvpnSid`만 바꿔 `POST https://api.mudfish.net/prog`로 보낸다. 노드는 `/do/rtt/staticnodes`의 `rttavg` 최저 일본 sid로 한다. 응답의 `status`, `msg`, `need_restart`를 기록한다.
Expected: `status == 200`, 이후 `GET /do/mudrun/status`의 `mudfish_fullvpn_sid`가 그 sid로 바뀐다(바뀌지 않으면 데몬 재로그인이 필요한지 기록).

- [ ] **Step 3: 연결 후 확인**

Run (덱): `curl -s -X POST http://127.0.0.1:8282/do/mudfish/start`를 실행하고 `client_ready`가 될 때까지 기다린 뒤, `ip -4 route; ip -br link; resolvectl status | head -20; curl -s -m 8 https://ipinfo.io/json; getent ahostsv4 login.nvidia.com; ip route get $(getent ahostsv4 login.nvidia.com | awk 'NR==1{print $1}'); tailscale status | head -3`
Expected: 공인 IP 국가 `JP`, `login.nvidia.com` 경로가 `dev tap0`. 기본 경로를 바꾸는 방식(0/1+128/1 분할인지 등), DNS 변화, Tailscale 상태를 그대로 기록한다.

- [ ] **Step 4: 연결 중 sid 변경**

다른 일본 sid로 Step 2를 반복하고 `need_restart`를 기록한다. `need_restart`가 false면 `POST /do/fullvpn/refresh`(form: `sid`, `exceptions`=progConf의 `mudfishFullvpnExceptions`)를 호출한 뒤 공인 IP가 바뀌는지 확인한다.
Expected: 어느 방법으로 새 노드가 적용되는지 기록한다.

- [ ] **Step 5: 해제 후 확인**

Run (덱): `curl -s -X POST http://127.0.0.1:8282/do/mudfish/stop`를 실행하고 6초 기다린 뒤 Step 3의 명령을 다시 실행한다.
Expected: 국가 `KR`, `tap0` 없음, 기본 경로가 Step 1과 같다. Step 1 대비 남은 경로를 기록한다.

- [ ] **Step 6: 게임모드 전환 시 데몬 유지 확인**

사용자에게 게임모드로 전환했다가 돌아와 달라고 요청한 뒤, `systemctl is-active mudfish-dev`를 실행한다.
Expected: `active`.

- [ ] **Step 7: 결과를 스펙에 기록하고, Task 4 절차와 다르면 사용자에게 보고**

Step 2~6의 결과를 스펙 9절 아래 "실측 결과"로 적는다. 다음 경우에는 Task 4로 넘어가기 전에 사용자에게 알린다: Full VPN이 일본 IP를 만들지 못함, `need_restart` 처리가 Task 4의 가정(아래 `apply_node`)과 다름, Tailscale이 끊김.

---

### Task 2: 프로젝트 골격과 덱 테스트 러너

**Files:**
- Create: `.gitignore`, `plugin.json`, `package.json`, `rollup.config.js`, `tsconfig.json`, `main.py`, `py_modules/mudfish_decky/__init__.py`, `src/index.tsx`, `scripts/test.sh`, `scripts/deploy.sh`, `tests/test_smoke.py`

**Interfaces:**
- Produces: `scripts/test.sh` (인자 없음, 덱에서 `python3 -m unittest discover -s tests -t .` 결과를 그대로 출력하고 종료코드 전달), `scripts/deploy.sh` (인자 없음, `pnpm build` 후 덱에 설치하고 `plugin_loader` 재시작)

- [ ] **Step 1: git 저장소와 도구 준비**

Run: `git init`, 그리고 Node가 없으므로 Chocolatey로 `choco install nodejs-lts -y`(관리자 권한이 필요하면 사용자에게 관리자 PowerShell에서 실행을 요청) 후 새 셸에서 `npm i -g pnpm@9`
Expected: `node -v`가 v20 이상, `pnpm -v`가 9.x.

- [ ] **Step 2: 템플릿 설정 파일 가져오기**

`SteamDeckHomebrew/decky-plugin-template`(main 브랜치)의 `package.json`, `rollup.config.js`, `tsconfig.json`, `.gitignore`를 그대로 가져와 `package.json`의 `name`을 `mudfish-decky`로 바꾼다. `plugin.json`은 Global Constraints 값으로 쓴다. `src/index.tsx`는 `definePlugin`으로 제목 "Mudfish VPN"과 빈 `PanelSection` 하나만 그린다. `main.py`는 `import decky` 후 빈 `Plugin` 클래스(`_main`, `_unload`는 `decky.logger.info`만)다. `main.py` 맨 위에서 `sys.path`에 `os.path.join(os.path.dirname(__file__), "py_modules")`를 추가한다(데키가 이미 추가해도 무해).

- [ ] **Step 3: 스모크 테스트와 test.sh 작성**

`tests/test_smoke.py`: `import mudfish_decky`가 되는지 확인한다(`self.assertTrue(hasattr(mudfish_decky, "__name__"))`).
`scripts/test.sh`: `tar -cf - py_modules tests | ssh deck@192.168.1.50 'rm -rf /tmp/mfd-test && mkdir /tmp/mfd-test && tar -xf - -C /tmp/mfd-test && cd /tmp/mfd-test && PYTHONPATH=py_modules python3 -m unittest discover -s tests -t . -v'`

- [ ] **Step 4: 테스트 실행**

Run: `bash scripts/test.sh`
Expected: `Ran 1 test ... OK`

- [ ] **Step 5: deploy.sh 작성과 첫 배포**

`scripts/deploy.sh`: `pnpm build`(실패하면 중단) → `tar -cf - dist main.py plugin.json package.json py_modules | ssh deck@192.168.1.50 'D=/home/deck/homebrew/plugins/mudfish-decky; sudo rm -rf "$D" && sudo mkdir -p "$D" && sudo tar -xf - -C "$D" && sudo systemctl restart plugin_loader'`
Run: `pnpm i && bash scripts/deploy.sh`, 그리고 `ssh deck@192.168.1.50 'journalctl -u plugin_loader --since "-1min" | grep -i mudfish'`
Expected: 로그에 플러그인 로드 메시지가 있고 오류가 없다. 사용자에게 게임모드 데키 목록에 "Mudfish VPN"이 보이는지 확인을 요청한다.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "chore: scaffold Mudfish VPN decky plugin"
```

---

### Task 3: 순수 로직 — 노드와 경로

**Files:**
- Create: `py_modules/mudfish_decky/nodes.py`, `py_modules/mudfish_decky/routes.py`
- Test: `tests/test_nodes.py`, `tests/test_routes.py`

**Interfaces:**
- Produces (`nodes.py`):
  - `@dataclass(frozen=True) class Node: sid: int; label: str; rtt: float | None`
  - `japan_nodes(static_nodes: list[dict], rtts: dict[int, float]) -> list[Node]` — 핑 오름차순, 핑 없는 노드는 라벨순으로 뒤에.
  - `pick_auto(nodes: list[Node]) -> Node | None` — 핑이 있는 첫 노드, 없으면 None.
  - `rtts_from_response(resp: dict) -> dict[int, float]` — `rtts` 중 `success > 0`인 항목의 `sid → rttavg`.
- Produces (`routes.py`):
  - `host_routes(route_text: str) -> set[str]` — `ip -4 route` 출력에서 `/`가 없는 목적지이고 `proto`가 없으며 `via`가 있는 줄을 공백 정규화해서 모은다.
  - `leftover_routes(before: set[str] | None, after_text: str) -> list[str]` — before가 None이면 `[]`. 아니면 `host_routes(after) - before` 중 `dev tap` 아닌 줄, 정렬해서.
  - `delete_routes(lines: list[str], run=subprocess.run) -> int` — 각 줄을 `["ip", "route", "del", *line.split()]`로 실행하고 성공한 개수를 돌려준다.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_nodes.py`:
```python
STATIC = [
    {"sid": 9, "location": "JP Asia (Tokyo - Linode3 IDC)"},
    {"sid": 11, "location": "JP Asia (Osaka - SakuraNet 4)"},
    {"sid": 46, "location": "JP Asia (Hokkaido - SakuraNet 6)"},
    {"sid": 300, "location": "US West (Los Angeles - HostUS)"},
]
RESP = {"status": 200, "rtts": [
    {"sid": 9, "rttavg": 38.5, "success": 4, "failure": 0},
    {"sid": 11, "rttavg": 31.0, "success": 4, "failure": 0},
    {"sid": 46, "rttavg": 0.0, "success": 0, "failure": 4},
    {"sid": 300, "rttavg": 5.0, "success": 4, "failure": 0},
]}

def test_rtts_skip_failed(self):
    self.assertEqual(rtts_from_response(RESP), {9: 38.5, 11: 31.0, 300: 5.0})

def test_japan_only_sorted_by_rtt_unmeasured_last(self):
    nodes = japan_nodes(STATIC, rtts_from_response(RESP))
    self.assertEqual([n.sid for n in nodes], [11, 9, 46])
    self.assertEqual(nodes[0].label, "Osaka - SakuraNet 4")
    self.assertIsNone(nodes[2].rtt)

def test_pick_auto_lowest(self):
    self.assertEqual(pick_auto(japan_nodes(STATIC, rtts_from_response(RESP))).sid, 11)

def test_pick_auto_none_without_rtts(self):
    self.assertIsNone(pick_auto(japan_nodes(STATIC, {})))
```

`tests/test_routes.py` (덱에서 관찰한 실제 형식):
```python
BEFORE = """default via 192.168.1.1 dev wlan0 proto dhcp src 192.168.1.50 metric 600
192.168.1.0/24 dev wlan0 proto kernel scope link src 192.168.1.50 metric 600
"""
AFTER = BEFORE + """1.201.174.247 via 192.168.1.1 dev wlan0
2.58.243.110 via 192.168.1.1 dev wlan0
10.254.100.5 via 10.254.100.1 dev tap0
"""

def test_host_routes_excludes_default_prefix_and_proto(self):
    self.assertEqual(host_routes(BEFORE), set())

def test_leftover_routes_only_new_non_tap(self):
    self.assertEqual(leftover_routes(host_routes(BEFORE), AFTER),
        ["1.201.174.247 via 192.168.1.1 dev wlan0", "2.58.243.110 via 192.168.1.1 dev wlan0"])

def test_leftover_routes_none_snapshot_deletes_nothing(self):
    self.assertEqual(leftover_routes(None, AFTER), [])

def test_leftover_routes_keeps_preexisting_host_routes(self):
    before = host_routes(AFTER.replace("2.58.243.110", "9.9.9.9"))
    self.assertNotIn("1.201.174.247 via 192.168.1.1 dev wlan0", leftover_routes(before, AFTER))

def test_delete_routes_runs_ip_route_del(self):
    calls = []
    def run(cmd, **kw):
        calls.append(cmd); return types.SimpleNamespace(returncode=0)
    self.assertEqual(delete_routes(["1.2.3.4 via 192.168.1.1 dev wlan0"], run=run), 1)
    self.assertEqual(calls, [["ip", "route", "del", "1.2.3.4", "via", "192.168.1.1", "dev", "wlan0"]])
```

- [ ] **Step 2: 실패 확인**

Run: `bash scripts/test.sh`
Expected: `ImportError`/`ModuleNotFoundError`로 FAIL

- [ ] **Step 3: `nodes.py`와 `routes.py`를 위 Interfaces대로 구현**

라벨은 `location`에서 첫 `(` 다음부터 마지막 `)` 전까지다. `delete_routes`는 `run(cmd, capture_output=True, timeout=5)`으로 부르고, 예외는 삼켜서 실패로 센다.

- [ ] **Step 4: 통과 확인**

Run: `bash scripts/test.sh`
Expected: 전부 OK

- [ ] **Step 5: Commit**

```bash
git add py_modules tests
git commit -m "feat: japan node ranking and leftover route detection"
```

---

### Task 4: 미꾸라지 클라이언트, 시스템 연동, 컨트롤러

**Files:**
- Create: `py_modules/mudfish_decky/client.py`, `py_modules/mudfish_decky/system.py`, `py_modules/mudfish_decky/store.py`, `py_modules/mudfish_decky/controller.py`
- Test: `tests/test_client.py`, `tests/test_controller.py`

**Interfaces:**
- Consumes: Task 3의 `Node`, `japan_nodes`, `pick_auto`, `rtts_from_response`, `host_routes`, `leftover_routes`, `delete_routes`
- Produces (`client.py`):
  - `class MudfishError(Exception)`, `class SigninError(MudfishError)`
  - `Transport = Callable[[str, str, bytes | None, dict[str, str]], tuple[int, bytes]]` (method, url, body, headers) → (http status, body). 기본 구현은 `urllib.request`이고 timeout은 10초다.
  - `class MudfishClient(base_url: str, transport: Transport = urllib_transport)`, 메서드: `status() -> dict`, `ensure_signed_in() -> dict`(스펙 4절 자동 로그인 절차. 이미 `isSignedIn`이면 그냥 status 반환. signin 응답이 200이 아니면 `SigninError`), `start() -> None`(응답 status 200/201이 아니면 `MudfishError`), `stop() -> None`, `rtts() -> dict[int, float]`, `static_nodes(jwt, api) -> list[dict]`, `prog_conf(jwt, api) -> dict`, `save_prog_conf(jwt, api, conf: dict) -> dict`(응답 그대로; status가 200이 아니면 `MudfishError`), `fullvpn_refresh(sid: int, exceptions: str) -> None`
- Produces (`system.py`):
  - `find_mudfish(root="/opt/mudfish") -> tuple[str, str] | None` — (bin 경로, var 디렉터리), 버전은 `.` 기준 정수 튜플로 비교
  - `api_base(var_dir: str) -> str` — `.ipport` 내용으로 `http://<ipport>`를 만들고, 없으면 `http://127.0.0.1:8282`
  - `ensure_daemon(bin_path: str, is_up: Callable[[], bool], run=subprocess.run) -> None` — `is_up()`이면 아무것도 안 하고, 아니면 `systemd-run --unit=mudfish-decky --collect <bin> -B`를 실행한 뒤 최대 10초 동안 `is_up()`을 기다린다
  - `tap_up() -> bool` — `/sys/class/net/tap0` 존재 여부
  - `route_text(run=subprocess.run) -> str` — `ip -4 route` 출력
  - `public_ip() -> dict | None` — `https://ipinfo.io/json`에서 `{"ip", "country"}`, 실패하면 None
- Produces (`store.py`): `class Store(path)`, `load() -> dict`, `save(d: dict)`. 키는 `node_mode`("auto"|"manual", 기본 "auto"), `manual_sid`(int|None), `connected_since`(float|None, epoch), `routes_before`(list[str]|None)이다.
- Produces (`controller.py`):
  - `class Controller(client, system, store, clock=time.time, sleep=time.sleep)` — `system`은 `system.py` 모듈과 같은 이름의 함수를 가진 객체다(테스트에서 가짜 주입). `ensure_daemon`의 `is_up`은 `client.status()`가 예외 없이 끝나는지로 판단한다.
  - 문구 상수(정확히 이 값, Task 6 UI도 사용):
    - `MSG_RELOGIN = "데스크탑 모드에서 미꾸라지(127.0.0.1:8282)에 '로그인 기억하기'로 다시 로그인하세요"`
    - `MSG_RTT = "노드 핑을 측정하는 중이에요. 잠시 후 다시 켜 주세요"`
    - `MSG_TIMEOUT = "30초 안에 연결되지 않아 연결을 취소했어요"`
    - `MSG_MISSING = "데스크탑 모드에서 미꾸라지를 설치하세요 (docs.mudfish.net Steam Deck 가이드)"`
    - 그 밖의 예외(`MudfishError`, 네트워크 오류)는 phase `error`, message `"연결 실패: <예외 메시지 한 줄>"`로 처리한다.
  - `state() -> dict` (프론트 계약, 아래)
  - `connect() -> dict`, `disconnect() -> dict`, `set_node(choice: str) -> dict`(choice는 `"auto"` 또는 sid 문자열), `nodes() -> list[dict]`(`{"sid","label","rtt"}`)
  - 모든 공개 메서드는 `threading.Lock` 하나로 직렬화한다. 이미 연결 중일 때 들어온 `connect`는 대기 후 현재 state를 돌려준다.

**state() 계약** (Task 5, 6이 그대로 사용):
```json
{"phase": "off|connecting|on|error|missing",
 "message": "문구 또는 null",
 "node_mode": "auto|manual", "node": {"sid": 11, "label": "Osaka - SakuraNet 4", "rtt": 31.0} ,
 "ip": "1.2.3.4" , "country": "JP",
 "connected_since": 1792840000.0}
```
- `missing`: `find_mudfish()`가 None. `on`: `core_running and client_ready and tap_up()`. `connecting`: `core_running`이지만 on이 아님. 그 외는 `off`. `error`는 마지막 connect 실패 후 다음 상태 변화 전까지만 쓴다.
- `node`: manual이면 저장된 sid의 노드, auto면 지금 시점 `pick_auto` 결과(없으면 null).
- `ip`/`country`: phase가 `on`일 때만 채운다(`public_ip()`를 30초 캐시).
- `connected_since`: on이면 store 값이고, store에 없으면 지금 시각을 저장해서 쓴다. off가 되면 store에서 지운다.

**connect() 절차:** `ensure_daemon` → `ensure_signed_in`(SigninError면 relogin 문구, error) → 노드 결정(auto면 `pick_auto`; None이면 rtt 문구, error, **start 호출 안 함**) → `prog_conf`를 읽고 `mudfishFullvpnSid`가 다르면 `mudfishFullvpnSid=sid`, `mudfishFullvpnVid=0`으로 `save_prog_conf` → `store.routes_before = sorted(host_routes(route_text()))` → `start()` → 1초 간격으로 최대 30초까지 on을 기다린다. 시간이 넘으면 `stop()` 후 timeout 문구, error. 성공하면 `connected_since=clock()`.

**set_node(choice):** store에 저장한다. phase가 on이면 `apply_node`(Task 1 결과에 따라: `save_prog_conf` 응답의 `need_restart`가 참이면 `stop()` 후 connect 절차의 start부터, 아니면 `fullvpn_refresh(sid, conf["mudfishFullvpnExceptions"])`)를 실행한다. off면 계정 sid를 건드리지 않는다(다음 connect 때 적용).

**disconnect():** `stop()` → 최대 10초 동안 `tap_up()`이 False가 되길 기다림 → `delete_routes(leftover_routes(store.routes_before, route_text()))` → store의 `routes_before`, `connected_since`를 비움.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_client.py` — 가짜 transport가 (method, url)별로 응답을 돌려주고 호출 기록을 남긴다:
- `test_ensure_signed_in_noop_when_signed` — status가 `isSignedIn: true`면 signin URL을 호출하지 않는다.
- `test_ensure_signed_in_replays_autologin` — status `{"isSignedIn": false, "username": "u", "token_v3": "123", "item_conf_mode": "simple", "version": "6.6.0", "api_server": "api.mudfish.net"}`일 때 `POST https://api.mudfish.net/signin_ng_v3` 본문(multipart)에 `autologin`=`ON`, `password`=`123`이 들어가고, 이어 `POST <base>/do/auth` JSON에 `password: "123"`, `remember_me: true`, `jwt`(signin 응답값)가 들어간다.
- `test_ensure_signed_in_raises_on_401` — signin 응답 `{"status": 401}` → `SigninError`.
- `test_start_accepts_201` / `test_start_raises_on_500`.
- `test_save_prog_conf_sends_authorization_header` — 헤더 `Authorization`이 jwt 그대로다.

`tests/test_controller.py` — `FakeClient`, `FakeSystem`, 임시 디렉터리 `Store`, 고정 `clock`, no-op `sleep`을 쓴다. 노드 데이터는 `test_nodes.py`의 `STATIC`/`RESP`와 같은 값이다:
- `test_state_missing_when_not_installed` → `phase == "missing"`
- `test_state_off_never_starts_core` → `state()` 호출 후 `client.start_calls == 0`
- `test_connect_auto_picks_lowest_and_saves_sid` → 저장된 conf의 `mudfishFullvpnSid == 11`, `mudfishFullvpnVid == 0`, phase `on`, `connected_since == clock()`
- `test_connect_skips_save_when_sid_unchanged` → `save_calls == 0`
- `test_connect_auto_without_rtts_does_not_start` → phase `error`, message가 표의 rtt 문구, `start_calls == 0`
- `test_connect_signin_failure_shows_relogin` → phase `error`, relogin 문구, `start_calls == 0`
- `test_connect_timeout_stops_core` → on이 끝내 안 되면 `stop_calls == 1`, phase `error`, timeout 문구
- `test_disconnect_deletes_only_new_routes_and_keeps_sid` → 삭제 명령이 새로 생긴 2줄뿐이고 `save_calls`가 늘지 않으며 store의 `connected_since`가 None
- `test_state_on_survives_restart_uses_saved_since` → 새 Controller(같은 store, store에 `connected_since=100.0`, 가짜 상태는 on)의 `state()["connected_since"] == 100.0`, `start_calls == 0`
- `test_set_node_while_off_only_saves_choice` → `save_calls == 0`, store `manual_sid == 9`
- `test_set_node_while_on_refreshes` → `need_restart` false 응답이면 `fullvpn_refresh(9, ...)`가 1회 호출된다

- [ ] **Step 2: 실패 확인**

Run: `bash scripts/test.sh`
Expected: 새 테스트 FAIL(ImportError)

- [ ] **Step 3: `client.py`, `system.py`, `store.py`, `controller.py`를 위 Interfaces와 절차대로 구현**

multipart 본문은 `uuid4().hex` 경계로 직접 만든다(스펙 4절과 같은 필드). `/do/fullvpn/refresh`는 `application/x-www-form-urlencoded`로 보낸다. 로그는 `logging.getLogger("mudfish_decky")`를 쓰고 jwt와 token은 로그에 남기지 않는다.

- [ ] **Step 4: 통과 확인**

Run: `bash scripts/test.sh`
Expected: 전부 OK

- [ ] **Step 5: Commit**

```bash
git add py_modules tests
git commit -m "feat: mudfish client and connect/disconnect controller"
```

---

### Task 5: 데키 백엔드 연결

**Files:**
- Modify: `main.py`
- Create: `src/backend.ts`

**Interfaces:**
- Consumes: Task 4의 `Controller`, `MudfishClient`, `system`, `Store`
- Produces (`main.py` `Plugin` 메서드, 모두 `async`이고 내부에서 `await asyncio.to_thread(...)`): `get_state() -> dict`, `connect() -> dict`, `disconnect() -> dict`, `set_node(choice: str) -> dict`, `list_nodes() -> list[dict]`
- Produces (`src/backend.ts`): `type Phase = "off"|"connecting"|"on"|"error"|"missing"`, `interface VpnState`(Task 4 계약과 같은 필드), `interface NodeInfo {sid:number; label:string; rtt:number|null}`, 그리고 `callable`로 만든 `getState`, `connect`, `disconnect`, `setNode(choice: string)`, `listNodes`

- [ ] **Step 1: `main.py` 구현**

`_main`: `Store(os.path.join(decky.DECKY_PLUGIN_SETTINGS_DIR, "settings.json"))`로 Controller를 만들고, `find_mudfish()`가 있으면 `ensure_daemon`만 백그라운드 스레드로 실행한다(**connect 호출 금지**). `logging.getLogger("mudfish_decky")`에 `decky.logger`의 핸들러를 붙인다. `_unload`는 아무것도 하지 않는다(데몬과 연결 상태 유지).

- [ ] **Step 2: 배포 후 백엔드 호출 확인**

Run: `bash scripts/deploy.sh`, 그리고 `ssh deck@192.168.1.50 'systemctl is-active mudfish-decky; journalctl -u plugin_loader --since "-1min" | grep -iE "mudfish|error"'`
Expected: `mudfish-decky`가 `active`(Task 1의 `mudfish-dev`가 떠 있으면 먼저 `sudo systemctl stop mudfish-dev`). 로그에 traceback이 없다. `curl -s 127.0.0.1:8282/do/mudrun/status`의 `core_running`이 false다.

- [ ] **Step 3: Commit**

```bash
git add main.py src/backend.ts
git commit -m "feat: expose controller through decky backend"
```

---

### Task 6: 패널 UI

**Files:**
- Create: `src/Panel.tsx`
- Modify: `src/index.tsx`

**Interfaces:**
- Consumes: Task 5의 `src/backend.ts`

**구성** (스펙 6절 순서): `PanelSection` 안에 차례로 둔다.
1. 상태 `Field`: 라벨 "상태", 값은 phase 문구.
   - on이면 `🇯🇵 JP · <ip> · <경과>`를 표시한다. country가 `JP`가 아니면 국가 코드를 그대로 쓰고 빨간 글씨로 표시한다.
   - 경과 시간은 `connected_since` 기준으로 1분 미만 "방금", 60분 미만 "N분째", 그 이상 "N시간 M분째"로 표시한다.
2. `ToggleField` "미꾸라지 Full VPN": 값은 phase가 on 또는 connecting이면 켜짐이다. connecting 동안과 missing일 때는 비활성화한다.
3. 노드 `Field`: auto면 `자동 · <label> (<rtt>ms)`, manual이면 `<label> (<rtt>ms)`, 노드가 없으면 "핑 측정 중…".
4. `ButtonItem` "고급 ▸/▾"로 접고 편다. 펼치면 `DropdownItem`의 첫 항목이 "자동 (핑 최저)"이고, 그 뒤로 `listNodes()` 순서대로 `<label> · <rtt>ms`(rtt 없으면 `측정 안 됨`)가 나온다. 선택하면 `setNode`를 호출한다.
5. message가 있으면 한 줄 `Field`로 표시한다.

폴링: 패널이 마운트되어 있는 동안 2초마다 `getState()`를 호출한다. 노드 목록은 고급을 펼칠 때 한 번, 그리고 이후 10초마다 갱신한다.

**문구 표** (백엔드 message와 UI에 그대로 사용):
| 키 | 문구 |
|---|---|
| phase off | 꺼짐 |
| phase connecting | 연결 중… |
| phase on | 연결됨 |
| phase error | 오류 |
| phase missing | 미꾸라지 미설치 |
| relogin | 데스크탑 모드에서 미꾸라지(127.0.0.1:8282)에 '로그인 기억하기'로 다시 로그인하세요 |
| rtt | 노드 핑을 측정하는 중이에요. 잠시 후 다시 켜 주세요 |
| timeout | 30초 안에 연결되지 않아 연결을 취소했어요 |
| missing | 데스크탑 모드에서 미꾸라지를 설치하세요 (docs.mudfish.net Steam Deck 가이드) |

relogin, rtt, timeout, missing 문구는 백엔드가 `message`로 보내 준다(Task 4의 `MSG_*` 상수). UI는 받은 message를 그대로 표시하고, phase 문구만 UI에서 정한다.

- [ ] **Step 1: `Panel.tsx` 구현, `index.tsx`에서 사용**

- [ ] **Step 2: 타입 검사와 빌드**

Run: `pnpm build`
Expected: 오류 없이 `dist/index.js`가 생성된다.

- [ ] **Step 3: 배포 후 사용자와 함께 게임모드에서 확인**

Run: `bash scripts/deploy.sh`
사용자에게 게임모드에서 다음 순서로 확인을 요청한다.
1. 패널이 "꺼짐"이고 노드 줄에 "자동 · …"가 보인다.
2. 토글을 켜면 "연결 중…"을 거쳐 "연결됨 · 🇯🇵 JP"가 된다.
3. 고급에서 다른 노드를 고르면 IP가 바뀐다.
4. 토글을 끄면 "꺼짐"이 된다.

그 사이 덱에서 `ip -br link | grep tap; curl -s -m 8 https://ipinfo.io/json`로 실제 상태를 대조한다.
Expected: 패널 표시와 실제 상태가 일치한다.

- [ ] **Step 4: Commit**

```bash
git add src
git commit -m "feat: quick access panel for Mudfish Full VPN"
```

---

### Task 7: 실사용 검증과 정리

**Files:**
- Modify: `docs/superpowers/specs/2026-10-24-mudfish-decky-design.md` (실측 결과에 이어서 기록)
- Create: `README.md` (설치 전제: 미꾸라지 설치, 데스크탑 모드에서 '로그인 기억하기'로 1회 로그인. 사용법 4줄. 문제가 생기면 볼 로그 위치)

- [ ] **Step 1: 지포스나우 실사용**

사용자에게 다음 순서로 진행해 달라고 요청한다: 게임모드 → 패널 켜기 → 일본 IP 확인 → 지포스나우 실행·로그인·게임 시작 → 패널 끄기 → 스트리밍이 유지되는지 확인.
Expected: 사용자가 정상 동작을 확인한다.

- [ ] **Step 2: 재부팅과 절전**

- 재부팅 후 패널이 "꺼짐"이고 `core_running`이 false다.
- 켠 상태로 절전했다가 깨운 뒤 패널이 실제 상태(`tap0`, ipinfo)와 일치한다.

결과를 스펙에 기록한다. 절전 후 터널이 죽었는데 core_running이 남는 등 불일치가 있으면 사용자에게 보고한다.

- [ ] **Step 3: 개발용 설정 정리**

Run: `ssh deck@192.168.1.50 'sudo systemctl stop mudfish-dev 2>/dev/null; rm -rf ~/mudfish-dl /tmp/htd /tmp/mfd-test /tmp/mf.js'`
사용자에게 Konsole에서 `sudo rm /etc/sudoers.d/zz-dev-nopasswd`를 직접 실행해 달라고 안내한다. 이후 `ssh deck@192.168.1.50 'sudo -n true'`가 실패하는 것으로 확인한다. 이 시점부터는 `deploy.sh`를 쓸 수 없다는 점을 README에 적는다.

- [ ] **Step 4: Commit**

```bash
git add README.md docs
git commit -m "docs: usage notes and on-device verification results"
```
