# Claude Junior Mark

Claude Code 세션 연속성 시스템 — 컨텍스트 한계 경고 · 세션 간 맥락 전달

---

## 개요
Claude Junior Mark(jm)는 Claude Code 세션을 관리하는 백그라운드 시스템.  
포맨(foreman)이 세션 상태를 감시하고, 세션 간 맥락을 handoff로 이어줌.

**주요 기능:**
- 토큰/턴 사용량 실시간 모니터링 (백그라운드 데몬)
- 매 턴 상태바 자동 표시 (토큰%, 턴 수, 포맨 PID 및 생사)
- 컨텍스트 임계값 도달 시 경고 알림
- 세션 간 작업 맥락 자동 전달 (handoff)
- `/compact` 실행 시 턴 카운터 자동 초기화

---

## 요구사항
- Windows + Git Bash
- Python 3.8+
- Claude Code (CC) 설치

---

## 설치
```bash
cd installer
install.bat
```

설치 후 Claude Code를 재시작하면 자동으로 활성됨.

설치 후 JM 시스템의 기능을 효과적으로 사용하기 위해선 Claude Code의 내장된 자동대화압축 옵션
즉 `"autoCompact": false` 로 설정하기를 권장.

| 배포 위치 | 내용 |
|-----------|------|
| `~/.claude/plugins/junior_mark/scripts/` | 훅 스크립트 |
| `~/.claude/settings.json` | 훅 자동 등록 |
| `~/.claude/CLAUDE.md` | jm_rules.md 자동 등록 |

---

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
| `turns(X%) token(X%)` | 현재 세션 토큰 사용량. 72%+ 경고 발생 시 이동 권장 |

---

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

> `~` 접미사가 있어야 명령으로 인식. 일반 대화 중 단어만 언급해도 동작하진 않음.

---

## 상태바

매 턴 화면하단 Footer 영역에 자동으로 표시:

```
🟢 [████████░░░░░░░░░░░░] 40.1% | 80K/200K T:26/30 | PID: 3624
```

| 항목 | 설명 |
|------|------|
| 🟢 / 🟡 / 🔴 | 포맨 생존 + 컨텍스트 레벨 (정상/경고/임계) |
| ⚫ | 포맨 죽음 → `restart~` 입력 또는 새 세션 열기 |
| `X% \| XK/200K` | 토큰 사용률 |
| `T:N/30` | 현재 세션 턴 수 |
| `PID: N` | 포맨 프로세스 ID (`----`이면 죽은 상태) |

---

## 경고 신호
| signal | 의미 | 대응 |
|--------|------|------|
| `none` | 정상 | — |
| `warn` | 토큰 72% 초과 | 마무리 준비, `move~` 고려 |
| `trsd` | 토큰 81% 초과 | 즉시 `move~` 권장 |

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

---

## 세션 흐름
```
[새 세션 시작]
    ↓
포맨 기동 → handoff_prev 인계 → 대화 진행
    ↓
warn(72%) → trsd(81%) → 사용자 판단
    ↓
move~              end~
    ↓                  ↓
retire 처리        off 처리
스냅샷 저장        foreman_reset.flag 생성
새 세션 인계       다음 세션 초기화
```

---

## 동작 원리

| 구성요소 | 역할 |
|----------|------|
| `foreman.py` | 백그라운드 데몬. 5초마다 토큰/턴/문자 모니터링 |
| `session_start.py` | CC 시작 시 handoff 로드 + foreman 기동 |
| `signal_checker.py` | 프롬프트마다 경고 flag 감지 + 키워드 처리 |
| `relay_writer.py` | 응답 후 대화 기록 + handoff 갱신 |
| `precompact.py` | /compact 직전 경고 flag 및 relay.jsonl 초기화 |
| `handoff.json` | 세션 요약 — 다음 세션이 이어받는 핵심 파일 |

데이터 위치: `~/.claude/plugins/junior_mark/data/{프로젝트-slug}/`

---

## 약칭
Claude Junior Mark / Junior Mark / jm / foreman — 모두 같은 시스템을 지칭.

---

## 참고 출처

Claude Code가 `statusLine` 훅의 stdin으로 `context_window` 데이터(토큰 수, 윈도우 크기, 사용률 등)를 전달한다는 사실은
fomyio의 [claude-context-monitor](https://github.com/fomyio/claude-context-monitor)를 통해 알게됨.
상태바 레이아웃, 세션 관리, 포맨 데몬, handoff 시스템은 독자적으로 개발됨.
