"""
Gate.io 고빈도 거래 봇 설정 파일

이 파일은 모든 거래 봇의 설정을 중앙에서 관리합니다.
.env 파일과 함께 사용되며, 환경별(테스트/운영) 설정을 분리합니다.
"""

import os
from typing import Dict, Any
from dataclasses import dataclass
from dotenv import load_dotenv

# .env 파일 로드
load_dotenv()


@dataclass
class APISettings:
    """Gate.io API 연결 설정"""
    
    api_key: str = os.getenv("GATE_API_KEY", "")
    secret_key: str = os.getenv("GATE_SECRET_KEY", "")
    testnet: bool = os.getenv("GATE_TESTNET", "False").lower() == "true"
    
    # API 엔드포인트
    base_url_testnet: str = "https://fx-api-testnet.gateio.ws"
    base_url_mainnet: str = "https://api.gateio.ws"
    
    @property
    def base_url(self) -> str:
        return self.base_url_testnet if self.testnet else self.base_url_mainnet


@dataclass 
class TradingSettings:
    """거래 전략 및 리스크 관리 설정"""
    
    # =================== 포지션 관리 ===================
    position_size_pct: float = 0.20        # 총 시드의 10% 사용
    leverage: int = 20                      # 20배 레버리지
    max_open_positions: int = 10             # 최대 동시 포지션 수
    
    # =================== 심볼 관리 ===================  
    symbols_count: int = 15                 # 거래량 상위 15개 심볼 선택
    symbol_update_interval: int = 3600      # 1시간마다 심볼 리스트 업데이트
    
    # =================== 시간 관리 ===================
    htf_timeframe: str = "15m"              # Higher Time Frame (트렌드 확인)
    ltf_timeframe: str = "1m"               # Lower Time Frame (진입/청산)
    candle_limit: int = 1000                # 패턴 분석용 캔들 데이터 수
    
    # =================== 기술적 지표 ===================
    # EMA 설정
    ema_fast: int = 9                       # 빠른 EMA
    ema_slow: int = 21                      # 느린 EMA
    
    # RSI 설정  
    rsi_period: int = 14                    # RSI 계산 기간
    rsi_oversold: int = 30                  # 과매도 구간
    rsi_overbought: int = 70                # 과매수 구간
    
    # Bollinger Bands 설정
    bb_period: int = 20                     # BB 계산 기간
    bb_std: float = 2.0                     # 표준편차 배수
    
    # ATR 설정
    atr_period: int = 14                    # ATR 계산 기간
    stop_loss_atr_mult: float = 2.0         # 손절 ATR 배수
    take_profit_atr_mult: float = 4.0       # 익절 ATR 배수
    
    # =================== 신호 필터링 ===================
    confidence_threshold: float = 0.40      # 최소 진입 신뢰도
    strong_signal_threshold: float = 0.70   # 강한 신호 (역추세 진입 허용)
    neutral_signal_threshold: float = 0.50  # 중립 트렌드 진입 허용
    
    # =================== 횡보 전략 설정 ===================
    enable_sideways_strategy: bool = False  # 횡보 전략 비활성화
    sideways_detection_method: str = "oscillation"  # oscillation, range, consecutive_holds
    sideways_lookback_period: int = 10      # 횡보 감지 기간 (캔들 수)
    bollinger_period: int = 20              # 볼린저 밴드 기간
    bollinger_std_dev: float = 2.0          # 볼린저 밴드 표준편차
    sideways_min_oscillations: int = 2      # 최소 진동 횟수
    sideways_max_oscillations: int = 4      # 최대 진동 횟수
    sideways_max_range_pct: float = 0.02    # 최대 가격 레인지 (2%)
    
    # =================== 리스크 관리 ===================
    max_daily_loss_pct: float = 0.5       # 일일 최대 손실 50%
    max_consecutive_losses: int = 0         # 연속 손실 후 중단 (0=비활성화)
    position_timeout_minutes: int = 0       # 포지션 타임아웃 (0=무제한)
    
    # =================== 운영 시간 ===================
    trading_hours_start: int = 0            # 24시간 운영
    trading_hours_end: int = 24
    
    def to_dict(self) -> Dict[str, Any]:
        """전략 객체 생성용 딕셔너리 변환"""
        return {
            'ema_fast': self.ema_fast,
            'ema_slow': self.ema_slow,
            'rsi_period': self.rsi_period,
            'rsi_oversold': self.rsi_oversold,
            'rsi_overbought': self.rsi_overbought,
            'bb_period': self.bb_period,
            'bb_std': self.bb_std,
            'atr_period': self.atr_period,
            'stop_loss_atr_mult': self.stop_loss_atr_mult,
            'take_profit_atr_mult': self.take_profit_atr_mult,
        }


@dataclass
class BacktestSettings:
    """백테스트 전용 설정"""
    
    initial_balance: float = float(os.getenv("INITIAL_BALANCE", "10000"))
    commission_rate: float = 0.0004         # Gate.io Taker 수수료 0.04%
    days: int = int(os.getenv("BACKTEST_DAYS", "30"))
    
    # 시뮬레이션 모드
    simulation_mode: bool = os.getenv("SIMULATION_MODE", "False").lower() == "true"
    
    # 결과 저장 경로
    results_dir: str = "backtest_results"
    charts_dir: str = "charts"


@dataclass
class NotificationSettings:
    """Discord/이메일 알림 설정"""
    
    # Discord 설정
    enable_discord: bool = os.getenv("ENABLE_DISCORD_ALERTS", "True").lower() == "true"
    discord_webhook_url: str = os.getenv("DISCORD_WEBHOOK_URL", "")
    
    # 이메일 설정
    enable_email: bool = os.getenv("ENABLE_EMAIL_ALERTS", "False").lower() == "true"
    email_from: str = os.getenv("EMAIL_FROM", "")
    email_password: str = os.getenv("EMAIL_PASSWORD", "")
    email_to: str = os.getenv("EMAIL_TO", "")
    
    # 알림 조건
    notify_on_trade: bool = True            # 거래 신호/진입/청산
    notify_on_profit: bool = True           # 수익 실현
    notify_on_loss: bool = True             # 손실 실현
    notify_on_daily_summary: bool = True    # 일일 요약
    notify_on_error: bool = True            # 시스템 오류
    
    # Discord 임베드 색상 코드
    color_profit: int = 0x00FF00            # 초록색 (수익)
    color_loss: int = 0xFF0000              # 빨간색 (손실)
    color_info: int = 0x0099FF              # 파란색 (정보)
    color_warning: int = 0xFFAA00           # 주황색 (경고)
    color_error: int = 0xFF0000             # 빨간색 (오류)


@dataclass
class LoggingSettings:
    """로깅 및 디버그 설정"""
    
    level: str = os.getenv("LOG_LEVEL", "INFO")
    file_path: str = "logs/trading_bot.log"
    max_file_size: int = 10 * 1024 * 1024   # 10MB
    backup_count: int = 5
    
    # 로그 포맷
    format: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    date_format: str = "%Y-%m-%d %H:%M:%S"
    
    # 상세 로깅 옵션
    log_api_calls: bool = False             # API 호출 로깅
    log_market_data: bool = False           # 시장 데이터 로깅
    log_signals: bool = True                # 거래 신호 로깅


@dataclass
class DatabaseSettings:
    """데이터베이스 연결 설정 (선택사항)"""
    
    url: str = os.getenv("DATABASE_URL", "sqlite:///trading_bot.db")
    create_tables: bool = True
    data_retention_days: int = 90           # 90일 후 데이터 정리


class Settings:
    """중앙 설정 관리 클래스
    
    모든 설정을 통합 관리하며, 유효성 검사 및 요약 출력 기능을 제공합니다.
    """
    
    def __init__(self):
        self.api = APISettings()
        self.trading = TradingSettings()
        self.backtest = BacktestSettings()
        self.notifications = NotificationSettings()
        self.logging = LoggingSettings()
        self.database = DatabaseSettings()
    
    def validate(self, mode: str = "trading") -> bool:
        """설정 유효성 검사
        
        Args:
            mode: "trading", "backtest", "analysis" 중 하나
        """
        errors = []
        warnings = []
        
        # API 키 검사 (거래 모드일 때만 필수)
        if mode == "trading":
            if not self.api.api_key:
                errors.append("⚠️ GATE_API_KEY가 설정되지 않았습니다.")
            if not self.api.secret_key:
                errors.append("⚠️ GATE_SECRET_KEY가 설정되지 않았습니다.")
        elif mode in ["backtest", "analysis"]:
            if not self.api.api_key:
                warnings.append("📊 백테스트/분석 모드: API 키 없음 (샘플 데이터 사용)")
        
        # Discord 알림 검사
        if self.notifications.enable_discord and not self.notifications.discord_webhook_url:
            if mode == "backtest":
                warnings.append("📢 Discord 알림 비활성화 (웹훅 URL 없음)")
                self.notifications.enable_discord = False
            else:
                errors.append("⚠️ Discord 알림이 활성화되었지만 웹훅 URL이 없습니다.")
        
        # 거래 설정 유효성 검사
        if self.trading.position_size_pct <= 0 or self.trading.position_size_pct > 0.5:
            errors.append("⚠️ 포지션 크기는 0%~50% 사이여야 합니다.")
        
        if self.trading.leverage < 1 or self.trading.leverage > 100:
            errors.append("⚠️ 레버리지는 1~100배 사이여야 합니다.")
        
        if self.trading.confidence_threshold <= 0 or self.trading.confidence_threshold > 1:
            errors.append("⚠️ 신뢰도 임계값은 0~1 사이여야 합니다.")
        
        # 결과 출력
        if warnings:
            print("🔶 설정 경고:")
            for warning in warnings:
                print(f"   {warning}")
            print()
        
        if errors:
            print("🔴 설정 오류:")
            for error in errors:
                print(f"   {error}")
            print()
            return False
        
        print("✅ 모든 설정이 유효합니다.")
        return True
    
    def print_summary(self):
        """설정 요약 출력 (SMC 스타일)"""
        print("=" * 60)
        print("🚀 Gate.io 고빈도 거래 봇 설정")
        print("=" * 60)
        print(f"🌐 API 모드: {'🧪 테스트넷' if self.api.testnet else '🔴 메인넷'}")
        print(f"💰 포지션 크기: {self.trading.position_size_pct:.1%} (총 시드의 비율)")
        print(f"📈 레버리지: {self.trading.leverage}배")
        print(f"📊 거래 심볼: 거래량 상위 {self.trading.symbols_count}개")
        print(f"⏰ 타임프레임: HTF {self.trading.htf_timeframe} / LTF {self.trading.ltf_timeframe}")
        print(f"🎯 신뢰도 임계값: {self.trading.confidence_threshold:.2f} (강신호: {self.trading.strong_signal_threshold:.2f})")
        print(f"🛡️ 일일 최대 손실: {self.trading.max_daily_loss_pct:.1%}")
        print(f"📱 Discord 알림: {'✅ 활성화' if self.notifications.enable_discord else '❌ 비활성화'}")
        print(f"🔄 포지션 타임아웃: {'♾️ 무제한' if self.trading.position_timeout_minutes == 0 else f'{self.trading.position_timeout_minutes}분'}")
        print("=" * 60)


# 전역 설정 인스턴스 생성
settings = Settings()


def get_version_info() -> Dict[str, str]:
    """버전 및 호환성 정보 반환"""
    return {
        "settings_version": "2.0",
        "compatible_bots": ["multi_symbol_bot", "live_trading_bot", "backtest"],
        "last_updated": "2025-08-30",
        "breaking_changes": [
            "레버리지 20배 → 50배 변경",
            "포지션 크기 계산 방식 변경 (총 시드의 10%)",
            "포지션 타임아웃 기본값 무제한으로 변경"
        ]
    }


if __name__ == "__main__":
    """설정 파일 직접 실행시 유효성 검사 및 요약 출력"""
    import sys
    import codecs
    
    # UTF-8 출력 설정 (Windows 호환)
    try:
        sys.stdout = codecs.getwriter('utf-8')(sys.stdout.detach())
    except:
        pass  # 이미 UTF-8이거나 설정 실패시 무시
    
    print("🔧 설정 파일 유효성 검사 시작...")
    print()
    
    if settings.validate():
        settings.print_summary()
        
        print("\n📋 버전 정보:")
        version_info = get_version_info()
        print(f"   버전: {version_info['settings_version']}")
        print(f"   업데이트: {version_info['last_updated']}")
        print(f"   호환 봇: {', '.join(version_info['compatible_bots'])}")
        
        if version_info['breaking_changes']:
            print("\n🚨 주요 변경사항:")
            for change in version_info['breaking_changes']:
                print(f"   • {change}")
    else:
        print("❌ 설정을 확인하고 수정해주세요.")
        exit(1)