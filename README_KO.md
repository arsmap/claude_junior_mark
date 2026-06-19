 [[한글]](./README_KO.md) · [[English]](./README.md)
 
<h1 align="center">Claude Junior Mark</h1>

<p align="center">
  <b>Claude Code CLI를 위한 세션 연속성 시스템</b><br>
  컨텍스트 경고, 세션 간 핸드오프, 그리고 지속성 백그라운드 모니터를 통한 컨텍스트 포화 및 유실 완화.
</p><br>

<p align="center">
  <img src="https://img.shields.io/badge/version-1.04.25-blue" alt="Version" />
  <img src="https://img.shields.io/badge/license-MIT-green" alt="License" />
  <img src="https://img.shields.io/badge/python-≥_3.8-3776AB?logo=python&logoColor=white" alt="Python" />
  <img src="https://img.shields.io/badge/platform-Windows-0078D4?logo=windows&logoColor=white" alt="Platform" />
  <img src="https://img.shields.io/badge/Claude_Code-plugin-D97706" alt="Claude Code" />
  <img src="https://img.shields.io/badge/PRs-welcome-purple" alt="PRs Welcome" />
</p>

## 개요
Claude Code CLI 와 대화하다보면 컨텍스트 창이 가득 차게 되어 세션이 갑자기 종료됩니다.  
사용자는 생각의 흐름을 놓치게 되고, 다음 세션은 직전의 내가 무엇을 하고 있었는지에 대한 기억 없이 차갑게 시작됩니다.  

Claude Junior Mark(이하 jm으로 지칭됨)는 백그라운드에서 당신의 CLI 세션들을 관리함으로써 이것을 해결합니다.  
'foreman'이라 불리는 백그라운드 데몬으로서 커스텀 훅들과 함께 작동하며, 이것은 지속적으로 세션 상태들을 모니터링하고 핸드오프를 통해 하나의 세션에서 다음 세션으로 맥락을 매끄럽게 연결합니다(다리를 놓습니다).  

| 문제 | 해결책 |
|---------|----------|
| 컨텍스트 오버플로우(넘침) 전 경고 없음 | 백그라운드 foreman이 토큰/턴 사용량을 모니터링하고 임계값에서 알림을 보냄 |
| 각 세션이 맨 처음부터(아무것도 없는 상태에서) 시작됨 | 핸드오프 파일이 작업 컨텍스트를 다음 세션으로 자동으로 실어 나름 |
| /compact가 턴 카운터를 리셋함 | PreCompact 훅이 추적 상태를 재초기화함 |  
<br>

## 요구사항
> | Requirement | Check |
> |-------------|-------|
> | Windows OS | `ver` |
> | Git Bash | `bash --version` |
> | Python 3.8+ | `python --version` |
> | Claude Code | `claude --version` | 
<br>

## 설치
윈도우 터미널 혹은 Git Bash에서 설치합니다:
```
cd installer
install.bat
```  

설치 후 Claude Code CLI를 재시작하면 자동으로 활성화됩니다.  

| 배포 위치 | 내용 |
|-----------|------|
| `~/.claude/plugins/junior_mark/scripts/` | 훅 스크립트 |
| `~/.claude/settings.json` | 훅 자동 등록 |
| `~/.claude/CLAUDE.md` | jm_rules.md 자동 등록 |  
<br>

## 기능들
백그라운드 데몬을 통한 실시간 토큰/턴 모니터링  
매 턴마다의 상태 표시줄: 토큰%, 턴 수, foreman PID 및 활성화 상태 (alive state)  
컨텍스트 임계값 경고 (82%에서 경고, 92%에서 긴급)  
자동 핸드오프 — 다음 세션이 당신이 떠났던 바로 그 지점부터 이어받음  
'/compact' 시 턴 카운터 리셋  
> **권장사항:** 최선의 결과를 위해 Claude Code의 내장 자동 압축 기능을 비활성화하십시오.
> JM은 세션 전환을 수동으로 관리하며, 자동 압축은 핸드오프 타이밍을 방해할 수 있습니다.
> 
> 이것을 당신의 ~/.claude/settings.json에 추가하십시오:
> ```json
> "autoCompact": false
> ```  
<br>

## 세션 시작 TUI 읽는 법
```
⎿ SessionStart says:
    [Junior Mark] foreman ✓ | HOME turns(42%) token(35%) | 마지막 메시지 미리보기...
```

| 심볼 | 의미 |
|------|------|
| `foreman ▶` | 이번 세션에서 foreman 새로 기동됨 |
| `foreman ✓` | 이전 세션에서 foreman이 살아있음 (연속) |
| `foreman ✗` | foreman 기동 실패 — 새 세션을 열거나 `start~` 입력 |
| `turns(X%) token(X%)` | 현재 세션 토큰 사용량. 82%+ 경고 발생 시 이동 권장 |  
<br>

## 대화 키워드
| 키워드 | 동작 | 다음 세션 |
|--------|------|-----------|
| `move~` | 맥락 보존 후 새 세션으로 이동 | 이전 세션 이어받음 |
| `end~` | 완전 종료 (foreman 종료 + 세션 종료) | 첫 세션으로 리셋 |
| `start~` | 종료 후 같은 창에서 재활성화 | — |
| `on~` | 포맨만 시작 (세션 상태 변경 없음) | — |
| `off~` | 포맨만 종료 (세션 상태 변경 없음) | — |
| `restart~` | 포맨 kill 후 재시작 | — |
| `guest-end~` | 게스트 세션 완전 종료 | — |  
<br>
> **두 가지 그룹으로 나뉨**
> - **세션 상태 명령** (`start~` / `move~` / `end~`): retire_flag, reset_flag, session_warn 등 세션 파일 변경
> - **프로세스 제어 명령** (`on~` / `off~` / `restart~`): 포맨 프로세스만 제어, 세션 상태 무관. ⚠️ `restart~`는 `start~`의 연장선이 아닙니다.

> `~` 접미사가 있어야 명령으로 인식하며, 일반 대화 중에 키워드가 언급되더라도 오작동하지 않습니다.
  
<br>

## 상태바
매 턴 화면하단 Footer 영역에 자동으로 표시:

```
🟢 [████████░░░░░░░░░░░░] 40.1% | 80/200K 26/30T | PID:3624
```

| 항목 | 설명 |
|------|------|
| 🟢 / 🟡 / 🔴 | 포맨 생존 + 컨텍스트 레벨 (정상/경고/임계) |
| ⚫ | 포맨 죽음 → `restart~` 입력 또는 새 세션 열기 |
| `X% \| N/200K` | 토큰 사용률 |
| `N/30T` | 현재 세션 턴 수 |
| `PID:N` | 포맨 프로세스 ID (`----`이면 죽은 상태) |  
<br>

## 경고 신호
| signal | 의미 | 대응 |
|--------|------|------|
| `none` | 정상 | — |
| `warn` | 토큰 82% 초과 | 마무리 준비, `move~` 고려 |
| `trsd` | 토큰 92% 초과 | 즉시 `move~` 권장 |  
<br>

### 경고 메시지 대응
| 메시지 | 대응 |
|--------|------|
| ⚠ Context N% reached | `move~` 입력 |
| ⚠ Context N% exceeded — run move~ now | 즉시 `move~` |
| ⚠ foreman dead detected | `restart~` 입력 또는 새 세션 열기 |
| ⚠ Session interrupted by terminal close | 새 CC 대화창 열기 또는 `start~` 입력 |
| ⚠ Session already ended | 새 CC 대화창 열기 또는 `start~` 입력 |
| ℹ Foreman stopped in previous session | 자동 재시작됨 — 무시해도 됨 |
| ℹ Session move requested in previous session | 이전 맥락 파악 후 대화 시작 |  
<br>

## 세션 흐름
```
[새 세션 시작]
    ↓
포맨 기동 → handoff_prev 인계 → 대화 진행
    ↓
warn(82%) → trsd(92%) → 사용자 판단
    ↓
move~              end~
    ↓                  ↓
retire 처리        off 처리
스냅샷 저장        foreman_reset.flag 생성
새 세션 인계       다음 세션 초기화
```  
<br>

## 동작 원리
| 구성요소 | 역할 |
|----------|------|
| `foreman.py` | 백그라운드 데몬. 5초마다 턴/토큰/문자 모니터링 |
| `session_start.py` | CC 시작 시 handoff 로드 + foreman 기동 |
| `signal_checker.py` | 프롬프트마다 경고 flag 감지 + 키워드 처리 |
| `relay_writer.py` | 응답 후 대화 기록 + handoff 갱신 |
| `precompact.py` | /compact 직전 경고 flag 및 relay.jsonl 초기화 |
| `handoff.json` | 세션 요약 — 다음 세션이 이어받는 핵심 파일 |

데이터 위치: `~/.claude/plugins/junior_mark/data/{프로젝트-slug}/`  
<br>

## 참고 및 출처
상태바의 출력 형식은 fomyio의 [claude-context-monitor](https://github.com/fomyio/claude-context-monitor) 를 참고하였습니다.  
그외 세션 관리, 포맨 데몬, handoff 시스템 등의 중요 기능은 자체 개발되었음을 밝힙니다.  
<br>

## 라이선스
이 프로젝트는 MIT 라이선스를 따릅니다 - 자세한 내용은 라이선스 파일을 참조 바랍니다 [LICENSE](LICENSE).  
<br>
