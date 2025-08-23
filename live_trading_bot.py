import os
import sys
import time
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, Optional
import logging
import signal
import threading
from queue import Queue

# 현재 디렉토리를 Python path에 추가
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from settings import settings
from gateio_connector import GateIOConnector
from final_high_frequency_strategy import FinalHighFrequencyStrategy, Signal, Position, MarketDataCollector, TechnicalIndicators
from discord_notifier import discord_notifier

# 로깅 설정
os.makedirs("logs", exist_ok=True)
logging.basicConfig(
    level=getattr(logging, settings.logging.level),
    format=settings.logging.format,
    datefmt=settings.logging.date_format,
    handlers=[
        logging.FileHandler(settings.logging.file_path, encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class LiveTradingBot:
    """실시간 거래 봇"""
    
    def __init__(self):
        self.running = False
        self.connector = None
        self.collector = None
        self.strategy = None
        
        # 거래 상태
        self.balance = 0.0
        self.current_positions = {}  # 심볼별 포지션 관리
        self.daily_pnl = 0.0
        self.daily_trades = 0
        self.consecutive_losses = 0
        self.last_trade_time = None
        self.trading_symbols = []  # 거래 대상 심볼들
        
        # 데이터 저장
        self.price_data = pd.DataFrame()
        self.max_data_length = 1000  # 메모리 관리를 위해 제한
        
        # 스레드 통신
        self.data_queue = Queue()
        self.stop_event = threading.Event()
        
        # 성과 추적
        self.trades_today = []
        self.daily_start_balance = 0.0
        
    def initialize(self) -> bool:
        """봇 초기화"""
        try:
            # 설정 검증
            if not settings.validate():
                logger.error("설정 검증 실패")
                return False
            
            logger.info("실시간 거래 봇 초기화 시작")
            
            # Gate.io 연결
            self.connector = GateIOConnector(
                api_key=settings.api.api_key,
                secret_key=settings.api.secret_key,
                testnet=settings.api.testnet
            )
            
            self.collector = MarketDataCollector(self.connector)
            
            # 시뮬레이션 모드 확인
            simulation_mode = os.getenv('SIMULATION_MODE', 'False').lower() == 'true'
            
            if simulation_mode:
                # 시뮬레이션 모드: 가상 잔고 사용
                self.balance = float(os.getenv('INITIAL_BALANCE', 10000))
                self.daily_start_balance = self.balance
                logger.info(f"[시뮬레이션] 초기 잔고: {self.balance:.2f} USDT")
                print(f"[SIMULATION] 시뮬레이션 모드로 실행됩니다 (가상 잔고: {self.balance:.2f} USDT)")
            else:
                # 실제 API 모드: Gate.io 잔고 조회
                account_info = self.connector.get_futures_balance()
                if account_info:
                    self.balance = float(account_info.get('available_balance', 0))
                    self.daily_start_balance = self.balance
                    logger.info(f"현재 잔고: {self.balance:.2f} USDT")
                else:
                    logger.error("계정 정보를 가져올 수 없습니다")
                    return False
            
            # 레버리지 설정 (실제 거래 모드만)
            if not simulation_mode:
                leverage_set = self.connector.set_leverage(
                    settings.trading.symbol, 
                    settings.trading.leverage
                )
                if not leverage_set:
                    logger.warning(f"레버리지 설정 실패 - 기본값 사용")
            
            # 거래 대상 심볼 조회 (거래량 상위 15개)
            if not simulation_mode:
                self.trading_symbols = self.connector.get_top_volume_symbols(
                    settings.trading.symbols_count
                )
                logger.info(f"거래 대상: {len(self.trading_symbols)}개 심볼")
            else:
                # 시뮬레이션 모드에서는 기본 심볼 사용
                self.trading_symbols = ['BTC_USDT', 'ETH_USDT', 'BNB_USDT']
                logger.info(f"[시뮬레이션] 거래 대상: {self.trading_symbols}")
            
            # 전략 초기화
            self.strategy = FinalHighFrequencyStrategy()
            
            # Discord 알림
            discord_notifier.send_bot_status(
                "started", 
                f"실시간 거래 봇 시작 (잔고: {self.balance:.2f} USDT)"
            )
            
            logger.info("봇 초기화 완료")
            return True
            
        except Exception as e:
            logger.error(f"봇 초기화 실패: {e}")
            discord_notifier.send_error_alert("초기화 오류", str(e))
            return False
    
    def fetch_latest_data(self, symbol: str) -> Optional[pd.DataFrame]:
        """특정 심볼의 최신 시장 데이터 수집"""
        try:
            # 최근 100개 캔들 데이터 수집
            df = self.connector.get_futures_klines(
                symbol=symbol,
                interval=settings.trading.timeframe,
                limit=100
            )
            
            if df.empty:
                logger.warning("데이터 수집 실패")
                return None
            
            # 기존 데이터와 병합
            if not self.price_data.empty:
                # 중복 제거 및 병합
                combined = pd.concat([self.price_data, df]).drop_duplicates('timestamp')
                combined = combined.sort_values('timestamp').tail(self.max_data_length)
                self.price_data = combined.reset_index(drop=True)
            else:
                self.price_data = df
            
            return self.price_data
            
        except Exception as e:
            logger.error(f"데이터 수집 오류: {e}")
            return None
    
    def check_trading_conditions(self) -> bool:
        """거래 조건 확인"""
        # 운영 시간 확인
        current_hour = datetime.now().hour
        if not (settings.trading.trading_hours_start <= current_hour <= settings.trading.trading_hours_end):
            return False
        
        # 일일 손실 한도 확인
        if self.daily_pnl < -self.daily_start_balance * settings.trading.max_daily_loss:
            logger.warning("일일 손실 한도 도달")
            return False
        
        # 연속 손실 확인
        if self.consecutive_losses >= settings.trading.max_consecutive_losses:
            logger.warning("연속 손실 한도 도달")
            return False
        
        return True
    
    def execute_trade(self, signal: Signal) -> bool:
        """거래 실행"""
        try:
            if signal.action not in ['BUY', 'SELL']:
                return False
            
            # 거래량 계산
            current_price = signal.price
            atr = self.strategy.indicators.calculate_atr(
                self.price_data['high'], 
                self.price_data['low'], 
                self.price_data['close']
            ).iloc[-1]
            
            size = self.strategy.calculate_position_size(current_price, atr, self.balance)
            
            if size <= 0:
                logger.warning("포지션 사이즈 계산 실패")
                return False
            
            # 주문 실행 (실제 거래 시 주의!)
            if not settings.api.testnet:
                logger.warning("실제 거래 모드입니다! 신중하게 진행하세요.")
                user_confirm = input("실제 거래를 진행하시겠습니까? (yes/no): ")
                if user_confirm.lower() != 'yes':
                    logger.info("사용자가 거래를 취소했습니다.")
                    return False
            
            # 주문 생성
            side = 'long' if signal.action == 'BUY' else 'short'
            order = self.connector.place_order(
                symbol=settings.trading.symbol,
                size=size,
                side=side,
                order_type='market'  # 시장가 주문
            )
            
            if order and 'id' in order:
                # 포지션 생성
                stop_loss = current_price - (atr * settings.trading.stop_loss_atr_mult)
                take_profit = current_price + (atr * settings.trading.take_profit_atr_mult)
                
                if side == 'short':
                    stop_loss, take_profit = take_profit, stop_loss
                
                self.current_position = Position(
                    entry_time=datetime.now(),
                    entry_price=current_price,
                    size=size,
                    side=side,
                    stop_loss=stop_loss,
                    take_profit=take_profit
                )
                
                self.last_trade_time = datetime.now()
                
                logger.info(f"포지션 진입: {side} {size} {settings.trading.symbol} @ {current_price}")
                
                # Discord 알림
                discord_notifier.send_position_opened(
                    side, settings.trading.symbol, current_price, size, stop_loss, take_profit
                )
                
                return True
            else:
                logger.error(f"주문 실행 실패: {order}")
                return False
                
        except Exception as e:
            logger.error(f"거래 실행 오류: {e}")
            discord_notifier.send_error_alert("거래 실행 오류", str(e))
            return False
    
    def check_exit_conditions(self, current_price: float) -> Optional[str]:
        """청산 조건 확인"""
        if not self.current_position:
            return None
        
        # 손절/익절 확인
        if self.current_position.side == 'long':
            if current_price <= self.current_position.stop_loss:
                return "손절"
            elif current_price >= self.current_position.take_profit:
                return "익절"
        else:  # short
            if current_price >= self.current_position.stop_loss:
                return "손절"
            elif current_price <= self.current_position.take_profit:
                return "익절"
        
        # 시간 기반 청산 (예: 30분 경과)
        if datetime.now() - self.current_position.entry_time > timedelta(minutes=30):
            return "시간만료"
        
        return None
    
    def close_position(self, exit_reason: str, current_price: float) -> bool:
        """포지션 청산"""
        try:
            if not self.current_position:
                return False
            
            # 청산 주문 실행
            side = 'short' if self.current_position.side == 'long' else 'long'
            order = self.connector.place_order(
                symbol=settings.trading.symbol,
                size=self.current_position.size,
                side=side,
                order_type='market'
            )
            
            if order and 'id' in order:
                # 손익 계산
                pnl = self.strategy.calculate_pnl(self.current_position, current_price)
                pnl_pct = (pnl / (self.current_position.entry_price * self.current_position.size)) * 100
                
                # 통계 업데이트
                self.daily_pnl += pnl
                self.balance += pnl
                self.daily_trades += 1
                
                if pnl > 0:
                    self.consecutive_losses = 0
                else:
                    self.consecutive_losses += 1
                
                # 거래 기록
                trade_record = {
                    'timestamp': datetime.now(),
                    'side': self.current_position.side,
                    'entry_price': self.current_position.entry_price,
                    'exit_price': current_price,
                    'size': self.current_position.size,
                    'pnl': pnl,
                    'pnl_pct': pnl_pct,
                    'exit_reason': exit_reason
                }
                self.trades_today.append(trade_record)
                
                logger.info(f"포지션 청산: {exit_reason} | 손익: {pnl:+.2f} USDT ({pnl_pct:+.2f}%)")
                
                # Discord 알림
                discord_notifier.send_position_closed(
                    self.current_position.side,
                    settings.trading.symbol,
                    self.current_position.entry_price,
                    current_price,
                    self.current_position.size,
                    pnl,
                    pnl_pct,
                    exit_reason
                )
                
                self.current_position = None
                return True
            else:
                logger.error(f"청산 주문 실패: {order}")
                return False
                
        except Exception as e:
            logger.error(f"포지션 청산 오류: {e}")
            discord_notifier.send_error_alert("청산 오류", str(e))
            return False
    
    def trading_loop(self):
        """메인 거래 루프 - 다중 심볼 거래"""
        logger.info(f"거래 루프 시작 ({len(self.trading_symbols)}개 심볼)")
        last_signal_time = {}  # 심볼별 마지막 신호 시간
        
        # 각 심볼별 초기화
        for symbol in self.trading_symbols:
            last_signal_time[symbol] = datetime.now()
        
        while self.running and not self.stop_event.is_set():
            try:
                # 거래 조건 확인
                if not self.check_trading_conditions():
                    time.sleep(60)  # 1분 대기
                    continue
                
                # 각 심볼별로 순차 처리
                for symbol in self.trading_symbols:
                    try:
                        # 최신 데이터 수집
                        df = self.fetch_latest_data(symbol)
                        if df is None or len(df) < 50:
                            logger.debug(f"{symbol}: 데이터 부족, 건너뛰기")
                            continue
                        
                        # 기술적 지표 업데이트
                        df = self.strategy.update_indicators(df)
                        current_price = df['close'].iloc[-1]
                        
                        # 현재 포지션 확인
                        if self.current_position:
                            # 청산 조건 확인
                            exit_reason = self.check_exit_conditions(current_price)
                            if exit_reason:
                                self.close_position(exit_reason, current_price)
                        else:
                            # 신호 생성 (1분에 한번)
                            if datetime.now() - last_signal_time > timedelta(minutes=1):
                                # 오더북과 거래내역 수집 (실시간 데이터)
                                orderbook = self.connector.get_orderbook(settings.trading.symbol)
                                trades = self.connector.get_trades(settings.trading.symbol)
                                
                                # 신호 생성
                                signal = self.strategy.check_entry_signal(
                                    df, len(df)-1, orderbook, trades
                                )
                                
                                # 거래 실행
                                if signal.action in ['BUY', 'SELL'] and signal.confidence >= settings.trading.confidence_threshold:
                                    logger.info(f"거래 신호 발생: {signal.action} (신뢰도: {signal.confidence:.2f})")
                                    
                                    # Discord 알림
                                    discord_notifier.send_trade_signal(
                                        signal.action, settings.trading.symbol, signal.price, signal.reason, signal.confidence
                                    )
                                    
                                    # 거래 실행
                                    self.execute_trade(signal)
                                
                                last_signal_time = datetime.now()
                    
                    except Exception as e:
                        logger.error(f"{symbol} 처리 오류: {e}")
                        continue
                
                # 일일 요약 (자정에)
                current_time = datetime.now()
                if current_time.hour == 0 and current_time.minute == 0 and self.trades_today:
                    self.send_daily_summary()
                
                # 주기적 상태 업데이트 (10분마다)
                if current_time.minute % 10 == 0 and current_time.second < 30:
                    self.log_status()
                
                time.sleep(10)  # 10초마다 확인
                
            except KeyboardInterrupt:
                logger.info("사용자가 봇을 중단했습니다")
                break
            except Exception as e:
                logger.error(f"거래 루프 오류: {e}")
                discord_notifier.send_error_alert("거래 루프 오류", str(e))
                time.sleep(30)  # 오류 발생 시 30초 대기
    
    def log_status(self):
        """상태 로그 출력"""
        logger.info(f"현재 상태 - 잔고: {self.balance:.2f} USDT | 일일손익: {self.daily_pnl:+.2f} USDT | 거래수: {self.daily_trades}")
        
        if self.current_position:
            unrealized_pnl = self.strategy.calculate_pnl(self.current_position, self.price_data['close'].iloc[-1])
            logger.info(f"현재 포지션: {self.current_position.side} | 미실현손익: {unrealized_pnl:+.2f} USDT")
    
    def send_daily_summary(self):
        """일일 요약 전송"""
        if not self.trades_today:
            return
        
        winning_trades = len([t for t in self.trades_today if t['pnl'] > 0])
        win_rate = winning_trades / len(self.trades_today) if self.trades_today else 0
        
        discord_notifier.send_daily_summary(
            date=datetime.now().strftime("%Y-%m-%d"),
            total_trades=len(self.trades_today),
            winning_trades=winning_trades,
            total_pnl=self.daily_pnl,
            win_rate=win_rate,
            balance=self.balance
        )
        
        # 일일 데이터 리셋
        self.trades_today = []
        self.daily_pnl = 0.0
        self.daily_trades = 0
        self.daily_start_balance = self.balance
    
    def start(self):
        """봇 시작"""
        logger.info("실시간 거래 봇 시작 요청")
        
        if not self.initialize():
            return False
        
        self.running = True
        
        # 신호 처리기 등록
        def signal_handler(signum, frame):
            logger.info("종료 신호 수신")
            self.stop()
        
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
        
        try:
            self.trading_loop()
        except Exception as e:
            logger.error(f"봇 실행 오류: {e}")
            discord_notifier.send_error_alert("봇 실행 오류", str(e))
        finally:
            self.stop()
        
        return True
    
    def stop(self):
        """봇 중지"""
        logger.info("실시간 거래 봇 중지")
        self.running = False
        self.stop_event.set()
        
        # 현재 포지션이 있으면 청산 여부 확인
        if self.current_position:
            logger.warning("현재 진행 중인 포지션이 있습니다.")
            if not settings.api.testnet:
                choice = input("포지션을 청산하시겠습니까? (y/n): ")
                if choice.lower() == 'y':
                    current_price = self.price_data['close'].iloc[-1] if not self.price_data.empty else self.current_position.entry_price
                    self.close_position("수동청산", current_price)
        
        discord_notifier.send_bot_status("stopped", "실시간 거래 봇 정지")
        logger.info("봇이 안전하게 종료되었습니다.")


def main():
    """메인 함수"""
    print("=" * 60)
    print("Gate.io 실시간 스켈핑 봇")
    print("=" * 60)
    
    # 설정 확인
    if not settings.validate():
        print("설정을 먼저 확인하고 .env 파일을 수정해주세요.")
        return
    
    settings.print_summary()
    
    # 테스트넷 경고
    if settings.api.testnet:
        print("\n[WARNING] 테스트넷 모드로 실행됩니다.")
    else:
        print("\n[LIVE] 실제 거래 모드입니다! 신중하게 진행하세요.")
        confirm = input("실제 거래를 시작하시겠습니까? (yes/no): ")
        if confirm.lower() != 'yes':
            print("거래를 취소했습니다.")
            return
    
    # 봇 시작
    bot = LiveTradingBot()
    
    try:
        bot.start()
    except KeyboardInterrupt:
        print("\n사용자가 봇을 중단했습니다.")
    except Exception as e:
        logger.error(f"봇 실행 중 오류: {e}")
    finally:
        print("봇이 종료되었습니다.")


if __name__ == "__main__":
    main()