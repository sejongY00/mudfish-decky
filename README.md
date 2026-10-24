# Mudfish VPN (Decky plugin)

스팀덱 게임모드의 데키 패널에서 **미꾸라지(Mudfish) Full VPN**을 켜고 끄는 플러그인입니다. 일본 지포스나우 계정으로 로그인할 때 쓰려고 만들었어요.

## 처음 한 번만 (데스크탑 모드)

1. 미꾸라지를 설치합니다. 자세한 방법은 [공식 Steam Deck 가이드](https://docs.mudfish.net/v3/en/docs/mudfish-product/mudfish-cloud-vpn/platform/steamos/steamos-install)를 참고하세요. 설치 위치는 `/opt/mudfish/<버전>`입니다.
2. 미꾸라지를 실행하고 브라우저에서 `http://127.0.0.1:8282`에 접속해 **'로그인 기억하기'를 체크하고** 로그인합니다.
3. 플러그인을 `~/homebrew/plugins/mudfish-decky/`에 설치합니다. 개발 환경에서는 `scripts/deploy.sh`를 씁니다.

그다음부터는 플러그인이 알아서 미꾸라지를 대기 상태로 띄우고 자동 로그인합니다. **연결은 직접 켤 때만** 합니다.

## 사용법 (게임모드)

1. `...` → 데키 → **Mudfish VPN**에서 토글을 켭니다.
2. 상태가 `연결됨 · 🇯🇵 JP`로 바뀌면 지포스나우를 실행해서 로그인하고 게임을 시작합니다.
3. 게임이 시작되면 토글을 끕니다. 미꾸라지는 1GB당 135원이고 경유 트래픽은 두 번 집계되므로, 켜 둔 채 스트리밍하지 마세요.
4. 노드는 기본이 **자동**이라 켤 때마다 핑이 가장 낮은 일본 노드를 고릅니다. 직접 고르려면 **고급 ▸**을 누르세요.

## 문제가 생기면

- "다시 로그인하세요": 데스크탑 모드에서 2번 로그인을 다시 하세요.
- "노드 핑을 측정하는 중": 부팅 직후 1~2분 정도는 핑 측정이 끝나지 않았을 수 있습니다.
- 로그: `~/homebrew/logs/mudfish-decky/`, `journalctl -u plugin_loader`
- 미꾸라지 데몬: `systemctl status mudfish-decky`

## 개발

- 파이썬 테스트는 스팀덱에서 실행합니다: `bash scripts/test.sh` (SSH `deck@192.168.1.50`)
- 빌드와 배포: `bash scripts/deploy.sh`. 덱의 `deck` 계정에 **sudo 비밀번호 없음 설정이 있어야** 동작합니다. 개발용 설정을 지운 뒤에는 쓸 수 없고, 다시 배포하려면 그 설정을 잠시 되살려야 합니다.
- 설계: `docs/superpowers/specs/2026-10-24-mudfish-decky-design.md`
