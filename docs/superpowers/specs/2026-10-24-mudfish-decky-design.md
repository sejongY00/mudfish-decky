# 미꾸라지 Full VPN 데키 플러그인 설계

작성일: 2026-10-24

## 1. 왜 만드는가

사용자의 **지포스나우(GeForce NOW) 계정은 일본 계정**이다. 스팀덱에서 지포스나우를 쓰려면 앱이 켜질 때와 로그인할 때, 게임을 실행할 때 **일본 IP**로 보여야 한다. 게임이 실행된 뒤에는 VPN을 꺼도 스트리밍이 문제없이 이어진다는 것을 사용자가 직접 확인했다.

미꾸라지(Mudfish) VPN은 스팀덱(SteamOS)을 공식 지원한다. 하지만 Konsole에서 띄운 미꾸라지는 데스크탑 모드에서 게임모드로 넘어가면 종료된다. 그래서 게임모드에서 켜고 끄려면 매번 데스크탑 모드를 오가야 한다.

이 플러그인은 **게임모드의 데키 패널에서 미꾸라지 Full VPN을 켜고 끄는 스위치**다.

### 사용 흐름

1. 게임모드에서 `...` 버튼을 누르고 데키 패널의 미꾸라지 플러그인에서 **켜기**를 누른다.
2. 패널에 일본 IP가 표시되는 것을 확인한다.
3. 지포스나우 앱을 실행해 로그인하고 게임을 시작한다.
4. 패널에서 **끄기**를 누른다. 이후 스트리밍은 직접 연결로 이어진다.

## 2. 목표 / 비목표 / 반목표

**목표**
- 게임모드 데키 패널에서 미꾸라지 Full VPN을 켜고 끈다.
- 연결 상태와 **현재 공인 IP·국가**를 보여 준다.
- 일본 노드는 기본이 **자동(그 시점에 핑이 가장 낮은 일본 노드)**이다. 수동 선택은 "고급" 접기 메뉴 안에 둔다.
- 연결된 뒤 지난 시간을 보여 줘서, 켜 둔 채로 잊는 일을 줄인다.
- 미리 데스크탑 모드에서 한 번 로그인해 두면(로그인 기억하기) 게임모드에서는 다시 로그인할 필요가 없다.

**비목표**
- 게임모드에서 아이디와 비밀번호를 입력해 로그인하는 기능. 토큰이 만료되면 안내 문구만 보여 준다.
- 미꾸라지 설치와 업데이트. 사용자가 공식 가이드대로 직접 한다.
- 자동 끄기, 시간 경과 알림 같은 자동화. 사용자가 수동으로 켜고 끄기로 했다.
- 아이템 모드 지원. 일본 이외 국가의 노드 선택.
- 데키 스토어 배포. 사용자 본인의 스팀덱 전용이다.

**반목표** (기술적으로는 돌아가도 실패로 보는 것)
- 사용자가 모르는 사이에 VPN이 켜진 상태로 남아 스트리밍 트래픽이 미꾸라지로 흘러가는 것. 종량제는 1GB당 135원이고 노드 경유 트래픽은 두 번 집계된다. 스트리밍 중에 켜져 있으면 시간당 수천 원이 나간다.
  - 플러그인이 자동으로 **연결을 시작**하는 동작은 없어야 한다. 부팅할 때, 플러그인을 다시 불러올 때, 절전에서 깨어날 때 모두 마찬가지다.
- 끄기를 눌렀는데 실제로는 터널이나 경로 설정이 남아 있는 것.
- 사용자의 미꾸라지 계정 설정을 묻지 않고 바꾸는 것. 예외는 Full VPN 노드 번호 하나로, 사용자가 노드를 선택하거나 자동 선택이 될 때만 바꾼다.

## 3. 환경 (2026-10-24 SSH로 확인)

- 스팀덱: SteamOS (holo), 커널 7.2.7, Python 3.14.6. SSH(`deck@<스팀덱 IP>`)는 키 인증으로 접속한다.
- 데키로더 **v3.3.0**과 플러그인 13개가 설치되어 있다. 참고할 만한 기존 플러그인으로 `tailscale-control`(VPN 스위치)이 있다.
- 지포스나우: Flatpak `com.nvidia.geforcenow` (user).
- 미꾸라지 **6.6.0**이 `/opt/mudfish/6.6.0/`에 설치되어 있다. `/opt`는 `/home` 쪽 파티션(`/.steamos/offload/opt`)이라 SteamOS 업데이트 후에도 남는다.
- 미꾸라지 계정은 종량제(PPT)이고 `isOkayToUseNodes: true`이다. "로그인 기억하기"로 로그인해 둔 상태다(`autologin on`, `token_v3` 저장).
- 개발 중에는 `deck` 계정에 sudo 비밀번호 없음 설정(`/etc/sudoers.d/zz-dev-nopasswd`)이 켜져 있다. **개발이 끝나면 지워야 한다.** 플러그인 자체는 이 설정에 의존하면 안 된다. 데키 백엔드는 root로 실행된다.

## 4. 확인된 미꾸라지 동작 (실측)

### 실행 바이너리
- `/opt/mudfish/<버전>/bin/mudrun-headless -B`: 로컬 웹 UI와 API를 `127.0.0.1:8282`에서 연다. `-B`는 브라우저를 띄우지 않는 옵션이다. 8282가 사용 중이면 임의의 포트로 열리고, 실제 포트는 `/opt/mudfish/<버전>/var/.ipport`에 기록된다.
- root가 필요하다. 라우팅 테이블을 바꾸고 `tap0` 인터페이스를 만들기 때문이다.
- Konsole이나 SSH 세션에서 띄우면 세션이 끝날 때 같이 죽는다. `sudo systemd-run --unit=<이름> --collect <바이너리> -B`로 띄우면 세션과 상관없이 유지되는 것을 확인했다.
- 설정과 상태 파일은 `/opt/mudfish/<버전>/var/.conf`(텍스트), `.conf.db`, `mudrun.pid` 등이다.

### 로컬 API (`http://127.0.0.1:8282`)
| 요청 | 용도 | 응답/비고 |
|---|---|---|
| `GET /do/mudrun/status` | 전체 상태 | JSON. `isSignedIn`, `autologin`, `username`, `token_v3`, `jwt`, `api_server`(`api.mudfish.net`), `item_conf_mode`, `version`, `core_running`, `core_ready`, `client_ready`, `fullvpn_enabled`, `mudfish_fullvpn_sid` |
| `POST /do/auth` (JSON) | 로컬 데몬에 로그인 결과 전달 | `{username, password, remember_me, token_v3, jwt, expert_mode, lang, alias_enable}` → `{"status":200}` |
| `POST /do/mudfish/start` | 코어(터널) 시작 | `{"status":200}`. 이미 실행 중이면 201 |
| `POST /do/mudfish/stop` | 코어 종료 | `{"status":200}` |
| `POST /do/fullvpn/refresh` (form) | 실행 중에 Full VPN 노드 반영 | `sid`, `exceptions` |
| `GET /do/rtt/staticnodes` | 노드별 핑 측정값 | `{"rtts":[{sid, rttavg, success, failure, ...}]}` |

### 자동 로그인 (데몬을 다시 띄우면 `isSignedIn: false`가 됨)
미꾸라지 웹 UI(`signin.html`)가 하는 절차를 그대로 따르며, 명령어로 성공을 확인했다.
1. `GET /do/mudrun/status`로 `username`, `token_v3`, `item_conf_mode`, `version`, `api_server`를 읽는다.
2. `POST https://api.mudfish.net/signin_ng_v3`를 **multipart form**으로 보낸다. 필드는 `autologin=ON`, `username`, `password=<token_v3>`, `item_conf_mode`, `version`이다. 응답은 `{status, token_v3, jwt, expert_mode, lang, alias_enable}`이다. `status`가 401이면 캡차가 필요하다는 뜻이다(웹 UI 기준).
3. `POST /do/auth`에 JSON을 보낸다. 필드는 `username`, `password=<저장된 token_v3>`, `remember_me=true`, `token_v3=<응답값>`, `jwt=<응답값>`, `expert_mode`, `lang`, `alias_enable`이다.
4. 이후 `status.isSignedIn == true`가 된다.

### Full VPN 노드 설정 (계정에 저장되는 값)
- 읽기: `POST https://api.mudfish.net/graphql`, 헤더 `Authorization: <jwt>`
  - `{ user { dataPlan isOkayToUseNodes progConf { mudfishFullvpnSid mudfishFullvpnVid mudfishFullvpnExceptions ... } staticNodes { sid location } } }`
  - 웹 UI(`prog.html`의 `prog_graphql`)는 progConf의 다음 필드를 모두 읽는다: `mudfishCreditSavingMode`, `mudfishFullvpnSid`, `mudfishFullvpnVid`, `mudfishFullvpnXp`, `mudfishFullvpnExceptions`, `mudfishMtu`, `mudfishPreferWfp`, `mudfishProtomethod`, `mudfishReBrokerMaxconns`, `mudflowCompatv1`, `mudflowRttmethod`.
- 쓰기: `POST https://api.mudfish.net/prog`에 **progConf 객체 전체**(위 필드)를 JSON으로 보내고, 헤더는 `Authorization: <jwt>`이다. 응답은 `{status, msg, need_restart}`이다. 웹 UI는 이어서 로컬 기록용으로 `POST /do/db/prog_conf`에 같은 객체를 보낸다.
  - 다른 필드는 읽은 값을 그대로 보내고, `mudfishFullvpnSid`만 바꾼다. `mudfishFullvpnVid`는 0이어야 한다. 웹 UI에는 sid와 vid가 둘 다 0보다 크면 막는 로직이 있다.
- 코어가 실행 중일 때 sid를 바꾸면 웹 UI는 `need_restart`이면 재시작하고, 아니면 `/do/fullvpn/refresh`를 호출한다.
- 현재 계정 값은 `mudfishFullvpnSid: 0`(Full VPN 꺼짐)이다. **sid > 0이면 Full VPN이 켜진 것으로 동작한다**(`status.fullvpn_enabled`). 아직 sid를 넣고 실제로 연결해 보지는 않았다. 아래 "검증이 필요한 부분"을 참고한다.

### 일본 노드
- `staticNodes` 228개 중 `location`이 `JP Asia (...)`로 시작하는 노드가 135개다. 예: `JP Asia (Tokyo - Linode3 IDC)`(sid 9), `JP Asia (Osaka - Vultr 1)`. 지역은 도쿄, 오사카, 홋카이도다.
- 핑은 `GET /do/rtt/staticnodes`의 `rttavg`(ms)를 sid로 맞춰 쓴다. 데몬이 켜져 있으면 미꾸라지가 주기적으로 측정한다. 측정 실패 노드는 `failure > 0`이거나 목록에 없다.

### 연결/해제 실측 (아이템 모드로 시험)
- start 후 약 6초 만에 `core_running → core_ready → client_ready`가 모두 true가 됐다. `tap0`가 생기고 아이템 IP 대역이 `tap0`로 잡혔다.
- stop 후 몇 초 안에 코어 프로세스가 종료되고 `tap0`도 사라졌다. 다만 **노드 IP로 가는 /32 경로 349개가 기존 게이트웨이(`via 192.168.1.1 dev wlan0`)로 남았다.** 같은 네트워크에서는 무해하지만, 다른 와이파이로 옮기면 그 노드들로 가는 경로가 틀어질 수 있다.
- 리눅스판에는 Windows의 프로세스 단위 캡처(WFP)가 없다. 아이템 모드에서는 지포스나우 로그인과 API 호스트(`login.nvidia.com`, `play/pcs/uas/als/mes.geforcenow.com`)가 미꾸라지를 거치지 않는다. 그래서 **Full VPN이 필요하다**(이 문서의 전제).

### 지포스나우 쪽 관찰
- 스팀덱 지포스나우 로그(2026-07-27)에 지역이 `KR GFN 1`(`prod.gkr.geforcenow.nvidiagrid.net`)로 잡혀 있었다. 앱이 켜질 때 IP로 지역을 정하므로, **앱을 켜기 전에 VPN이 연결되어 있어야 한다.** 그래서 패널에 "연결됨 + 일본 IP"를 분명하게 보여 주는 것이 중요하다.

## 5. 정해진 설계 (사용자 결정)

- **Full VPN 방식**만 지원한다.
- 켜기와 끄기는 **사용자가 수동**으로 한다. 자동 끄기나 알림은 넣지 않는다.
- 로그인은 데스크탑 모드에서 미리 한다(완료). 게임모드 로그인은 범위 밖이다.
- **끄기를 눌러도 계정의 Full VPN 노드 설정(sid)은 지우지 않는다.**
- 노드 선택은 **기본이 "자동"**이고, 켤 때마다 그 시점에 핑이 가장 낮은 일본 노드를 고른다. **수동 선택은 "고급" 접기 메뉴 안에 숨긴다.**
- 개발 중에는 Claude가 SSH로 스팀덱에 직접 배포하고 테스트한다.

## 6. 패널 구성

위에서 아래 순서다.
1. **상태 줄**: `꺼짐` / `연결 중…` / `연결됨` / `오류`.
   - 연결됨이면 현재 공인 IP와 국가(예: `🇯🇵 JP · 1.2.3.4`)와 **연결 후 지난 시간**(예: `12분째`)을 보여 준다.
   - 국가가 JP가 아니면 경고색으로 표시한다.
2. **켜기/끄기 토글**.
3. **노드 줄**: `자동 · Tokyo - Linode3 IDC (38ms)`처럼 실제로 쓰는(또는 쓸) 노드를 보여 준다.
4. **고급 (접힘)**: 펼치면 "자동" 항목과 일본 노드 목록이 나온다. 목록은 핑 오름차순이고 측정 실패 노드는 맨 아래에 둔다. 하나를 고르면 그 노드로 고정되고, "자동"을 고르면 자동으로 돌아간다. 이 선택은 플러그인 설정에 저장한다.
5. **오류/안내 문구**(필요할 때만):
   - 로그인 토큰 만료: "데스크탑 모드에서 미꾸라지(127.0.0.1:8282)에 '로그인 기억하기'로 다시 로그인하세요".
   - 미꾸라지가 설치되지 않음: 설치 가이드 안내.
   - 연결 실패: 원인 한 줄.

## 7. 동작 규칙

- **데몬 상주**: 플러그인이 로드되면(부팅 시 포함) 미꾸라지 데몬이 떠 있지 않을 때만 transient systemd unit으로 띄운다. 이 상태는 **코어 미실행 대기 상태**라 핑 측정만 한다. **코어는 절대 자동으로 시작하지 않는다.**
- **켜기**:
  1. 데몬을 확인한다.
  2. 필요하면 자동 로그인한다.
  3. 노드를 정한다. 자동이면 핑 최저 일본 노드, 수동이면 저장된 sid다.
  4. 계정 sid가 다르면 `/prog`로 갱신한다.
  5. `/do/mudfish/start`를 호출한다.
  6. `client_ready`가 될 때까지 기다린다.
  7. 공인 IP와 국가를 확인한다.
- **연결 중 노드 변경**(고급 메뉴): sid를 갱신한 뒤 `/do/fullvpn/refresh`를 호출하거나, `need_restart`이면 stop 후 start한다.
- **끄기**: `/do/mudfish/stop`을 호출하고, 코어 종료와 `tap0` 소멸을 확인한다. 미꾸라지가 남긴 노드 /32 경로를 정리한다. 데몬은 계속 떠 있다.
- **상태 판단의 기준은 미꾸라지 실제 상태**(`/do/mudrun/status`와 `tap0` 존재)다. 플러그인 내부 플래그에 의존하지 않는다. 패널을 열 때마다 새로 조회하고, 열려 있는 동안 주기적으로 갱신한다.
- 미꾸라지 경로는 `/opt/mudfish/*/bin/mudrun-headless` 중 **가장 높은 버전**을 쓴다.
- 미꾸라지 실행 파일은 root로 실행된다. 플러그인은 경로를 고정된 위치에서만 찾고, 사용자 입력을 명령어에 넣지 않는다.

## 8. 구현 기본값 (빌더가 바꿔도 되는 것)

- 데키 플러그인 표준 구성(공식 decky-plugin-template 계열)을 쓴다. 프론트엔드는 React/TypeScript(`@decky/ui`, `@decky/api`), 백엔드는 `main.py`(Python, `plugin.json`의 `flags: ["root"]`)다.
- HTTP 호출은 백엔드에서 Python 표준 라이브러리로 한다. 스팀덱에 별도 패키지를 설치하지 않는다.
- 공인 IP와 국가 확인 서비스는 빌더가 정한다. 예: `https://ipinfo.io/json`, `https://myip.mudfish.net`.
- systemd unit 이름, 폴링 주기, 타임아웃, 남은 경로 정리 방법(어떤 경로를 미꾸라지가 추가한 것으로 볼지)은 빌더가 정한다.
- 빌드는 Windows PC에서 하고, SSH로 `~/homebrew/plugins/<플러그인>/`에 배포한 뒤 `plugin_loader`를 재시작한다. 구체적인 도구는 빌더가 정한다.

## 9. 검증이 필요한 부분 (구현 초기에 실측)

1. `/prog`로 `mudfishFullvpnSid`를 바꾼 뒤 start했을 때 **실제로 모든 트래픽이 tap0로 가고 공인 IP가 일본으로 바뀌는지**. 기본 경로가 어떻게 바뀌는지, DNS는 어떻게 되는지도 확인한다.
2. 연결 중 sid를 바꿀 때 `need_restart` 값과 `/do/fullvpn/refresh`의 실제 효과.
3. Full VPN을 끈 뒤 기본 경로와 DNS가 원래대로 돌아오는지, 남는 것이 무엇인지.
4. 절전 후 깨어났을 때 데몬과 터널 상태.
5. 데스크탑 모드와 게임모드를 오갈 때 systemd로 띄운 데몬이 유지되는지.
6. 스팀덱 기본 Tailscale(`tailscale0`)과 Full VPN이 충돌하지 않는지.

### 실측 결과 (2026-10-24, 구현 Task 1)

1. **Full VPN이 동작한다.** `/prog`로 `mudfishFullvpnSid=165`(Osaka - Azure 01)를 저장하고 start하자 약 8초 뒤 `client_ready`가 됐다.
   - 경로: `0.0.0.0/1`과 `128.0.0.0/1`을 `tap0`로 보내는 분할 방식이다. 기존 `default via 192.168.1.1`은 그대로 남는다.
   - 공인 IP: `13.73.234.162`, `JP`(Microsoft).
   - `login.nvidia.com`과 `play.geforcenow.com`이 모두 `dev tap0`으로 나간다.
   - DNS는 그대로 `1.1.1.1`이지만, 1.1.1.1로 가는 질의도 터널을 타서 일본에서 질의한 것으로 보인다.
2. **꺼진 상태에서 sid를 저장하면** `/prog` 응답이 `need_restart: True`다. 로컬 `status.mudfish_fullvpn_sid`는 다음 start 때 반영된다.
3. **연결된 상태에서 sid를 165 → 504로 바꾸면** `need_restart: False`다. 이어서 `/do/fullvpn/refresh`를 부르면 재연결 없이 새 노드(Amazon 오사카, `13.208.184.0`)로 바뀐다. 이때 응답 본문은 비어 있다.
   - 단, **로컬 `status.mudfish_fullvpn_sid`는 165로 남는다.** 그래서 현재 노드는 status가 아니라 플러그인 저장값이나 클라우드 progConf로 판단해야 한다.
4. **해제하면** `tap0`가 없어지고, 분할 경로가 사라지고, 국가가 `KR`로 돌아온다. DNS 설정은 변화 없다. 노드 /32 경로는 이번 연결에서 5개가 새로 남았다(이전 시험분 포함 총 353줄).
5. **`/do/rtt/staticnodes`는 측정 라운드가 도는 동안 `{"status": 300}`만 준다.** `rtts`는 라운드가 끝난 순간에만 `status: 200`으로 잠깐 나오고, 라운드 간격은 1분 이상이다. 그래서 플러그인은 마지막으로 성공한 측정값을 저장해 둬야 한다.
6. **Tailscale은 로그아웃 상태**(`/opt/tailscale/tailscale status` → Logged out)라 충돌 우려가 없다.
7. **게임모드 전환 시 데몬 유지**: 확인했다. 데스크탑 모드에서 게임모드로 넘어간 뒤에도 `mudfish-decky` unit이 `active`였다.

### 실사용 검증 (2026-10-24, 구현 Task 7)

- **게임모드 패널**(사용자 확인): 꺼짐 상태와 자동 노드 표시, 켜기 → `🇯🇵 JP`, 고급에서 노드 변경, 끄기가 모두 정상이었다. 끌 때마다 미꾸라지가 남긴 노드 경로 400여 줄이 정리되어 라우팅 테이블에는 기본 2줄만 남았다.
- **지포스나우**(사용자 확인): 플러그인으로 켠 상태에서 로그인하고 게임을 시작했다. GFN 로그에 `Lowest latency zone is ap-japan.cloudmatchbeta.nvidiagrid.net with 40ms`가 남았다(이전에는 `KR GFN 1`).
- **절전 버그와 결정**: 켠 채로 절전했다 깨우면 NetworkManager가 wlan0 경로를 다시 만들면서 미꾸라지의 중계 서버 /32 경로를 지운다. 반면 `tap0`의 `0/1`, `128/1` 경로는 남는다. 그래서 중계 서버로 가는 패킷까지 터널로 들어가 **인터넷 전체가 끊긴다.** 이때도 미꾸라지는 `client_ready: true`를 보고한다. 중계 서버 /32 경로를 다시 넣으면 복구되는 것으로 원인을 확인했다.
  - **사용자 결정: 절전에서 깨어날 때와 덱 종료(플러그인 unload) 때 VPN을 자동으로 끈다.**
  - 구현: `CLOCK_BOOTTIME − CLOCK_MONOTONIC` 증가로 깨어남을 감지하고 2초마다 확인한다. 깨어난 것이 감지되면 teardown하고 안내 문구를 표시한다.
  - 재검증(사용자 확인 + 로그 `resume detected; turning VPN off`): 깨어난 직후 인터넷이 정상이고 패널은 꺼짐이다.
- **재부팅**(사용자 확인): 재부팅 후 패널은 꺼짐이고 코어는 미실행이다. 부팅 시 `prepare()`가 와이파이 연결 전에 실행되어 자동 로그인이 한 번 실패하지만, 노드 목록은 저장된 값을 쓰고 켜기를 누르면 그때 로그인한다.

## 추가 기능: 휴대폰 QR 로그인 (2026-10-24, 사용자 요청)

- **목적**: 저장된 로그인이 거부되면 데스크탑 모드로 가지 않고 게임모드에서 휴대폰으로 다시 로그인한다.
- **사용자가 승인한 설계**:
  - 패널에 "휴대폰으로 로그인 (QR)" 버튼을 띄운다. 플러그인 시작 시나 켜기를 누를 때 `SigninError`가 나면 `need_login`이 된다.
  - 버튼을 누르면 QR 팝업이 뜨고, 그동안 덱의 LAN IP의 무작위 포트로 런처 UI를 중계한다.
  - 중계는 일회용 토큰 `/_mfd/<token>`으로 보호한다. 이 경로를 처음 연 IP만 통과하고 나머지는 403이다.
  - 최대 5분 동안 열고, 새 세션(jwt 변경)이 감지되거나 팝업을 닫거나 만료되거나 unload되면 닫는다.
- **확인된 사실**:
  - `api.mudfish.net`은 CORS로 요청 Origin을 그대로 허용한다.
  - 런처 UI는 LAN 주소로 열어도 로그인 흐름이 동작한다.
  - `/logout.html`을 열면 런처가 `autologin=False`, `token_v3="0"`이 된다. 이 상태를 "저장된 로그인 없음"으로 처리한다.
- **실사용 검증**(사용자 확인 + 로그):
  - 로그아웃 → 패널에 QR 버튼이 표시됐다.
  - 휴대폰(192.168.1.60)이 인증됐고 10초 뒤 로그인이 감지되어 중계가 닫혔다.
  - 이후 자동 로그인이 다시 켜졌고 켜기가 정상 동작했다. 닫힌 뒤 LAN에 남은 포트는 없다.

## 추가 기능: 미꾸라지 설치·업데이트·제거 (2026-10-24, 사용자 요청)

이 기능으로 2절의 비목표 "미꾸라지 설치와 업데이트"를 철회한다.

- **설치**:
  - `mudfish.net/download`에서 최신 `mudfish-<ver>-linux-x86_64.sh`를 찾는다.
  - 이 파일은 Makeself 형식(셸 헤더 `skip`줄 + bzip2 tar, 헤더에 MD5)이다. MD5를 검증한 뒤 tar를 직접 푼다. 이때 경로 조작과 링크를 거부하고 `filter="data"`를 쓴다.
  - 결과는 `/opt/mudfish/<ver>/{bin,sbin,etc,share,var}`이다. **다운로드한 스크립트는 실행하지 않는다.**
  - 실제 6.6.0을 이 방식으로 설치하면 데몬 바이너리가 공식 설치본과 동일하다. 공식 스크립트가 복사하지 않는 `mudstat`, `.desktop`, polkit 파일도 함께 들어간다.
- **업데이트**:
  - 최신 버전 확인은 하루 1회 백그라운드에서 한다. 실제 업데이트는 버튼으로만 하고, 터널이 있으면 거부한다.
  - 새 버전을 설치한 뒤 `var/.conf`와 `var/.conf.db`를 복사하고, 데몬을 새 버전으로 재시작한다. 직전 버전 1개만 남긴다.
  - **실측**: 6.5.5에서 QR 로그인 후 6.6.0으로 업데이트했다. 재로그인 없이 `isSignedIn=True`, `autologin=True`였다.
- **제거**(사용자 결정: 버튼과 플러그인 삭제 시 모두):
  - 순서: 터널 teardown → 데몬 중지(`--no-block`) → `mudfish-tap` 삭제 → `/opt/mudfish` 삭제 → 플러그인 설정 비우기.
  - **데키 3.3.0 제약**: SIGTERM과 동시에 소켓이 닫히면 sandboxed plugin의 listener가 EOF에서 돌며 이벤트 루프를 굶긴다. 그러면 `_unload`/`_uninstall`이 실행되지 못하고 5초 뒤 SIGKILL된다. 이 덱에서 여러 플러그인이 이 상태로 수십 % 비율로 종료됐다.
  - 대책 1: `_unload`/`_uninstall`은 동기로 실행한다.
  - 대책 2: 일시적인 systemd path 유닛 `mudfish-decky-cleanup`이 plugins 폴더를 감시한다. 이 플러그인 폴더가 20초 동안 없으면 정리하고 스스로 멈춘다. 재설치나 업데이트처럼 폴더를 바로 다시 만드는 경우는 건드리지 않는다.
  - **실측**: 데키에서 플러그인을 삭제하자 `_uninstall`과 감시가 모두 동작했다. `/opt/mudfish`, 설정, 데몬, 프로세스가 모두 없어졌다.

## 10. 끝나면 할 일

- 스팀덱의 `/etc/sudoers.d/zz-dev-nopasswd`를 지운다(사용자가 직접 실행: `sudo rm /etc/sudoers.d/zz-dev-nopasswd`).
- 개발 중에 띄운 `mudfish-dev` transient unit을 정리한다.
