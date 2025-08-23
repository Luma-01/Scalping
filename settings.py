import os
from typing import Dict, Any
from dataclasses import dataclass
from dotenv import load_dotenv

# .env 파일 로드
load_dotenv()

@dataclass
class APISettings:
    """Gate.io API 설정"""
    api_key: str = os.getenv("GATE_API_KEY", "")
    secret_key: str = os.getenv("GATE_SECRET_KEY", "")
    testnet: bool = os.getenv("GATE_TESTNET", "True").lower() == "true"
    base_url_testnet: str = "https://fx-api-testnet.gateio.ws"
    base_url_mainnet: str = "https://api.gateio.ws"
    
    @property
    def base_url(self) -> str:
        return self.base_url_testnet if self.testnet else self.base_url_mainnet


@dataclass 
class TradingSettings:
    """거래 전략 설정"""
    # 최적화된 파라미터 (백테스트 결과 기반)
    ema_fast: int = 9
    ema_slow: int = 21
    rsi_period: int = 14
    rsi_oversold: int = 30
    rsi_overbought: int = 70
    bb_period: int = 20
    bb_std: float = 2.0
    atr_period: int = 14
    
    # 리스크 관리
    stop_loss_atr_mult: float = 2.5
    take_profit_atr_mult: float = 3.5
    max_position_size: float = 0.1  # BTC
    risk_per_trade: float = 0.02  # 2%
    confidence_threshold: float = 0.9  # 높은 신뢰도 진입
    
    # 거래 심볼 (동적으로 상위 15개 선택)
    symbol: str = "BTC_USDT"  # 기본값
    symbols_count: int = 15   # 거래량 상위 15개
    
    # 스켈핑 최적화 타임프레임 구조
    htf_timeframe: str = "15m"   # Higher Time Frame (트렌드 확인)
    ltf_timeframe: str = "1m"    # Lower Time Frame (진입/청산)
    timeframe: str = "1m"        # 기본 거래 타임프레임
    
    # 캔들 데이터 수집
    candle_limit: int = 1000     # 패턴 인식을 위한 충분한 데이터
    
    leverage: int = 20  # 레버리지 20배 (안전한 최대값)
    
    # 운영 시간 (UTC 기준)
    trading_hours_start: int = 0  # 24시간 운영
    trading_hours_end: int = 24
    
    # 손절매 설정
    max_daily_loss: float = 0.05  # 일일 최대 손실 5%
    max_consecutive_losses: int = 3  # 연속 손실 후 중단
    
    def to_dict(self) -> Dict[str, Any]:
        """딕셔너리로 변환 (전략 객체 생성용)"""
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
            'max_position_size': self.max_position_size,
            'risk_per_trade': self.risk_per_trade
        }


@dataclass
class BacktestSettings:
    """백테스트 설정"""
    initial_balance: float = float(os.getenv("INITIAL_BALANCE", "10000"))
    commission_rate: float = 0.0004  # Gate.io Taker 수수료 0.04%
    days: int = int(os.getenv("BACKTEST_DAYS", "30"))
    
    # 결과 저장 경로
    results_dir: str = "backtest_results"
    charts_dir: str = "charts"
    logs_dir: str = "logs"


@dataclass
class NotificationSettings:
    """알림 설정"""
    enable_discord: bool = os.getenv("ENABLE_DISCORD_ALERTS", "True").lower() == "true"
    discord_webhook_url: str = os.getenv("DISCORD_WEBHOOK_URL", "")
    
    enable_email: bool = os.getenv("ENABLE_EMAIL_ALERTS", "False").lower() == "true"
    email_from: str = os.getenv("EMAIL_FROM", "")
    email_password: str = os.getenv("EMAIL_PASSWORD", "")
    email_to: str = os.getenv("EMAIL_TO", "")
    
    # 알림 조건
    notify_on_trade: bool = True
    notify_on_profit: bool = True
    notify_on_loss: bool = True
    notify_on_daily_summary: bool = True
    notify_on_error: bool = True
    
    # Discord 임베드 색상
    color_profit: int = 0x00FF00  # 초록색
    color_loss: int = 0xFF0000    # 빨간색
    color_info: int = 0x0099FF    # 파란색
    color_warning: int = 0xFFAA00 # 주황색
    color_error: int = 0xFF0000   # 빨간색


@dataclass
class LoggingSettings:
    """로깅 설정"""
    level: str = os.getenv("LOG_LEVEL", "INFO")
    file_path: str = os.getenv("LOG_FILE", "logs/trading_bot.log")
    max_file_size: int = 10 * 1024 * 1024  # 10MB
    backup_count: int = 5
    
    # 로그 포맷
    format: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    date_format: str = "%Y-%m-%d %H:%M:%S"


@dataclass
class DatabaseSettings:
    """데이터베이스 설정"""
    url: str = os.getenv("DATABASE_URL", "sqlite:///trading_bot.db")
    
    # 테이블 생성 여부
    create_tables: bool = True
    
    # 데이터 보관 기간 (일)
    data_retention_days: int = 90


class Settings:
    """전체 설정 클래스"""
    
    def __init__(self):
        self.api = APISettings()
        self.trading = TradingSettings()
        self.backtest = BacktestSettings()
        self.notifications = NotificationSettings()
        self.logging = LoggingSettings()
        self.database = DatabaseSettings()
    
    def validate(self, backtest_only: bool = False) -> bool:
        """설정 유효성 검사"""
        errors = []
        warnings = []
        
        # API 키 검사 (백테스트 전용일 때는 경고만)
        if not self.api.api_key:
            if backtest_only:
                warnings.append("GATE_API_KEY가 설정되지 않았습니다. (샘플 데이터 사용)")
            else:
                errors.append("GATE_API_KEY가 설정되지 않았습니다.")
        if not self.api.secret_key:
            if backtest_only:
                warnings.append("GATE_SECRET_KEY가 설정되지 않았습니다. (샘플 데이터 사용)")
            else:
                errors.append("GATE_SECRET_KEY가 설정되지 않았습니다.")
        
        # Discord 웹훅 검사 (알림이 활성화된 경우)
        if self.notifications.enable_discord and not self.notifications.discord_webhook_url:
            if backtest_only:
                warnings.append("Discord 알림이 활성화되었지만 DISCORD_WEBHOOK_URL이 설정되지 않았습니다. (알림 비활성화)")
                self.notifications.enable_discord = False
            else:
                errors.append("Discord 알림이 활성화되었지만 DISCORD_WEBHOOK_URL이 설정되지 않았습니다.")
        
        # 이메일 설정 검사
        if self.notifications.enable_email:
            email_errors = []
            if not self.notifications.email_from:
                email_errors.append("EMAIL_FROM이 설정되지 않았습니다.")
            if not self.notifications.email_password:
                email_errors.append("EMAIL_PASSWORD가 설정되지 않았습니다.")
            if not self.notifications.email_to:
                email_errors.append("EMAIL_TO가 설정되지 않았습니다.")
            
            if email_errors:
                if backtest_only:
                    warnings.extend([f"이메일 알림 설정 오류: {err}" for err in email_errors])
                    warnings.append("이메일 알림을 비활성화합니다.")
                    self.notifications.enable_email = False
                else:
                    errors.extend([f"이메일 알림이 활성화되었지만 {err}" for err in email_errors])
        
        # 거래 설정 검사
        if self.trading.risk_per_trade <= 0 or self.trading.risk_per_trade > 0.1:
            errors.append("거래당 위험도는 0과 0.1 사이여야 합니다.")
        
        if self.trading.confidence_threshold <= 0 or self.trading.confidence_threshold > 1:
            errors.append("신뢰도 임계값은 0과 1 사이여야 합니다.")
        
        # 경고 출력
        if warnings:
            print("설정 경고:")
            for warning in warnings:
                print(f"  - {warning}")
        
        # 오류 출력
        if errors:
            print("설정 오류:")
            for error in errors:
                print(f"  - {error}")
            return False
        
        return True
    
    def print_summary(self):
        """설정 요약 출력"""
        print("=" * 60)
        print("거래 봇 설정 요약")
        print("=" * 60)
        print(f"API 모드: {'테스트넷' if self.api.testnet else '메인넷'}")
        print(f"거래 심볼: {self.trading.symbol}")
        print(f"초기 자본: {self.backtest.initial_balance:,} USDT")
        print(f"거래당 위험도: {self.trading.risk_per_trade:.1%}")
        print(f"신뢰도 임계값: {self.trading.confidence_threshold}")
        print(f"Discord 알림: {'활성화' if self.notifications.enable_discord else '비활성화'}")
        print(f"백테스트 기간: {self.backtest.days}일")
        print("=" * 60)


# 전역 설정 인스턴스
settings = Settings()

# 설정 유효성 검사 (모듈 임포트 시 자동 실행)
if __name__ == "__main__":
    if settings.validate():
        print("모든 설정이 유효합니다.")
        settings.print_summary()
    else:
        print("설정을 확인하고 수정해주세요.")