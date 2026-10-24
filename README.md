# Mudfish VPN (Decky plugin)

스팀덱 게임모드의 데키 패널에서 **미꾸라지(Mudfish) Full VPN**을 켜고 끄는 플러그인입니다. 일본 지포스나우 계정으로 로그인할 때 쓰려고 만들었어요.

## 처음 한 번만

1. 플러그인을 설치합니다. [릴리스](https://git.sejong.dev/ysj7705/mudfish-decky/releases)에서 `mudfish-decky-<버전>.zip`의 주소를 복사한 뒤, 데키 설정 → 개발자 모드 → **Install Plugin from URL**에 붙여 넣습니다. zip 파일을 직접 받아서 **Install Plugin from ZIP**으로 설치해도 됩니다.
2. 게임모드 패널에서 **미꾸라지 설치** 버튼을 누릅니다. `mudfish.net`에서 최신 리눅스 패키지를 받아 MD5를 확인한 뒤, 설치 스크립트를 실행하지 않고 직접 풀어서 `/opt/mudfish/<버전>`에 설치합니다.
3. **휴대폰으로 로그인 (QR)** 버튼으로 로그인합니다('로그인 기억하기' 체크).

그다음부터는 플러그인이 알아서 미꾸라지를 대기 상태로 띄우고 자동 로그인합니다. **연결은 직접 켤 때만** 합니다.

## 업데이트 / 제거

- **업데이트**: 하루에 한 번 최신 버전을 확인합니다. 새 버전이 있으면 **고급 ▸**에 업데이트 버튼이 나타납니다. VPN을 끈 상태에서만 할 수 있습니다. 로그인 설정은 새 버전으로 옮겨지고, 바로 전 버전 하나는 남깁니다.
- **제거**: **고급 ▸ → 미꾸라지 제거**를 누릅니다. 또는 데키에서 플러그인을 삭제해도 같이 정리됩니다. 정리 대상은 VPN 연결, 데몬, `/opt/mudfish` 전체, `mudfish-tap` 연결, 플러그인 설정입니다. 미꾸라지 계정에 저장된 Full VPN 노드 설정은 남습니다.
  - 데키 3.3은 플러그인을 5초 만에 강제 종료하는 경우가 잦습니다. 그래서 별도의 systemd 감시(`mudfish-decky-cleanup.path`)가 플러그인 폴더를 지켜보다가, 폴더가 20초 동안 사라져 있으면 정리를 실행합니다.
- 공식 설치 방법은 [Steam Deck 가이드](https://docs.mudfish.net/v3/en/docs/mudfish-product/mudfish-cloud-vpn/platform/steamos/steamos-install)를 참고하세요.

## 사용법 (게임모드)

1. `...` → 데키 → **Mudfish VPN**에서 토글을 켭니다.
2. 상태가 `연결됨 · 🇯🇵 JP`로 바뀌면 지포스나우를 실행해서 로그인하고 게임을 시작합니다.
3. 게임이 시작되면 토글을 끕니다. 미꾸라지는 1GB당 135원이고 경유 트래픽은 두 번 집계되므로, 켜 둔 채 스트리밍하지 마세요.
4. 노드는 기본이 **자동**이라 켤 때마다 핑이 가장 낮은 일본 노드를 고릅니다. 직접 고르려면 **고급 ▸**을 누르세요.

## 문제가 생기면

- "다시 로그인하세요": 패널의 **휴대폰으로 로그인 (QR)** 버튼을 누르고, 덱과 같은 와이파이에 있는 휴대폰으로 QR을 찍어 '로그인 기억하기'를 체크하고 로그인하세요. 로그인이 확인되면 팝업이 자동으로 닫힙니다.
  - 이때 플러그인이 덱의 LAN 주소에 최대 5분 동안 임시 포트를 엽니다. QR에 일회용 값이 들어 있어, 처음 QR을 찍은 기기만 접속할 수 있습니다.
  - 또는 데스크탑 모드에서 2번 로그인을 다시 해도 됩니다.
- "노드 핑을 측정하는 중": 부팅 직후 1~2분 정도는 핑 측정이 끝나지 않았을 수 있습니다.
- 로그: `~/homebrew/logs/mudfish-decky/`, `journalctl -u plugin_loader`
- 미꾸라지 데몬: `systemctl status mudfish-decky`

## 개발

- 스크립트는 SSH 대상을 `DECK` 환경변수로 받습니다(예: `export DECK=deck@steamdeck.local`). 덱에 SSH 키 인증이 설정되어 있어야 합니다.
- 파이썬 테스트는 스팀덱에서 실행합니다: `bash scripts/test.sh`
- 빌드와 배포: `bash scripts/deploy.sh`. 덱의 `deck` 계정에 **sudo 비밀번호 없음 설정이 있어야** 동작합니다. 개발용 설정을 지운 뒤에는 쓸 수 없고, 다시 배포하려면 그 설정을 잠시 되살려야 합니다.
- 설계: `docs/superpowers/specs/2026-10-24-mudfish-decky-design.md`

## 릴리스 (Jenkins)

`main`에 푸시하면 Jenkins(`Jenkinsfile`)가 다음 단계를 차례로 실행합니다.

1. **Test**: `python:3.14-slim`에서 단위 테스트
2. **Build**: `node:22`에서 pnpm 빌드
3. **Package**: `scripts/package.py`로 `out/mudfish-decky-<버전>.zip`을 만들고 아티팩트로 보관
4. **Release**: `scripts/gitea_release.py`로 Gitea 릴리스 `v<버전>`을 만들고 zip을 올림

이미 같은 버전의 릴리스가 있으면 Release 단계는 아무것도 하지 않습니다. **새 버전을 내려면 `package.json`의 `version`을 올려서 푸시**하면 됩니다. 업로드에는 Jenkins 자격증명 `gitea-ysj7705`(저장소 쓰기 권한이 있는 Gitea 토큰)를 씁니다.
