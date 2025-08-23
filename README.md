# Gate.io 고빈도 스켈핑 자동매매 시스템

Gate.io 선물거래를 이용한 고빈도 스켈핑 자동매매 봇입니다.

## 📊 핵심 성과

### 최종 전략 백테스트 결과 (7일)
- **거래량**: 2,100+ 회 (일평균 300회)
- **승률**: 55.6%
- **최대 낙폭**: 0.41%
- **평균 보유시간**: 2분

## 🏗️ 핵심 파일 구조

```
├── settings.py                  # 전략 설정 및 파라미터
├── gateio_connector.py          # Gate.io API 연동
├── discord_notifier.py          # Discord 알림 시스템
├── final_high_frequency_strategy.py  # 최종 고빈도 전략
├── live_trading_bot.py          # 실시간 거래 봇
├── .env                         # 환경변수 설정
└── requirements.txt             # 필요 라이브러리
```

## 🚀 설치 및 설정

### 1. 라이브러리 설치

```bash
pip install pandas numpy matplotlib requests python-dotenv
```

### 2. 환경변수 설정 (.env)

```bash
# Gate.io API 설정
GATE_API_KEY=your_api_key_here
GATE_SECRET_KEY=your_secret_key_here
GATE_TESTNET=True

# Discord 웹훅 설정
DISCORD_WEBHOOK_URL=your_discord_webhook_url

# 백테스트 설정
BACKTEST_DAYS=30
INITIAL_BALANCE=10000

# 알림 설정
ENABLE_DISCORD_ALERTS=True
LOG_LEVEL=INFO
```

## 🎯 고빈도 전략 특징

### Price Action 스켈핑
- **연속 캔들 패턴** 감지 (3-6개 연속)
- **바디 비율 필터링** (80% 이상)
- **ATR 기반 동적 손익 설정**
- **시장 구조 분석** (추세/횡보 구분)

### 리스크 관리
- 거래당 0.3% 익절/손절
- 최대 보유시간 10분
- 시장 활동성 필터링
- 연속 손실 제한

## 📈 사용법

### 백테스트 실행

```bash
# 최종 전략 백테스트
python final_high_frequency_strategy.py
```

### 실시간 거래

```bash
# ⚠️ 반드시 테스트넷에서 먼저 테스트
python live_trading_bot.py
```

## ⚙️ 전략 설정

`settings.py`에서 핵심 파라미터 조정:

```python
@dataclass
class TradingSettings:
    # Price Action 파라미터
    min_consecutive: int = 3        # 최소 연속 캔들
    max_consecutive: int = 6        # 최대 연속 캔들
    body_ratio_threshold: float = 0.8  # 바디 비율
    min_confidence: float = 0.3     # 최소 신뢰도
    
    # 리스크 관리
    profit_target_pct: float = 0.003   # 익절 0.3%
    stop_loss_pct: float = 0.003       # 손절 0.3%
    max_hold_minutes: int = 10         # 최대 보유 10분
    
    # 거래 제한
    max_daily_trades: int = 500        # 일일 최대 거래
    min_signal_gap_minutes: int = 1    # 신호 간격
```

## 📱 Discord 알림

설정된 Discord 채널로 실시간 알림:
- 거래 신호 발생
- 포지션 진입/청산
- 일일 성과 요약
- 시스템 오류 알림

## ⚠️ 중요 사항

### 실거래 전 필수 체크
1. **테스트넷에서 충분한 검증** 완료
2. **소액으로 실전 테스트** 진행
3. **시장 상황에 따른 파라미터 조정**
4. **지속적인 성과 모니터링**

### 리스크
- 암호화폐 거래의 원금 손실 위험
- 높은 변동성으로 인한 예상치 못한 손실
- API 연결 불안정성
- 전략 오작동 가능성

## 🔧 문제 해결

### 자주 발생하는 문제
1. **API 연결 오류**: Gate.io API 키 및 권한 확인
2. **거래량 부족**: `min_confidence` 값 조정 (0.3 → 0.2)
3. **Discord 알림 실패**: 웹훅 URL 확인

### 성과 개선
- 시장 상황에 맞는 파라미터 튜닝
- 거래 시간대 제한 설정
- 변동성 필터 조정

## 📄 라이센스

개인 사용 목적으로만 제공됩니다. 상업적 사용 금지.

---

**⚠️ 면책조항**: 이 소프트웨어는 교육 및 연구 목적으로 제공됩니다. 실제 거래에서 발생하는 손실에 대해서는 사용자가 전적으로 책임집니다.