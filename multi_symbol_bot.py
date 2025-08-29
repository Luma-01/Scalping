import os
import sys
import time
import pandas as pd
import logging
import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import threading
from dataclasses import dataclass

# 현재 디렉토리를 Python path에 추가
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from settings import settings
from gateio_connector import GateIOConnector, get_kst_time
from final_high_frequency_strategy import FinalHighFrequencyStrategy, Signal, Position
from discord_notifier import discord_notifier

# 로깅 설정 - SMC 스타일
logging.basicConfig(
    level=logging.INFO,
    format='%(message)s',  # SMC 스타일로 시간 제거
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# SMC 스타일 로거 함수
def log_info(category: str, message: str, emoji: str = "🔍"):
    """SMC 스타일 정보 로깅"""
    print(f"{get_kst_time()} {emoji} [{category}] {message}")

def log_success(message: str):
    """SMC 스타일 성공 로깅"""
    print(f"{get_kst_time()} ✅ [SUCCESS] {message}")

def log_error(message: str):
    """SMC 스타일 오류 로깅"""
    print(f"{get_kst_time()} ❌ [ERROR] {message}")

def log_trade(action: str, symbol: str, price: float, size: float):
    """SMC 스타일 거래 로깅"""
    emoji = "💰" if action.upper() == "BUY" else "📉"
    print(f"{get_kst_time()} {emoji} [{action.upper()}] {symbol} | Price: {price} | Size: {size}")

def log_position(action: str, symbol: str, pnl: float):
    """SMC 스타일 포지션 로깅"""
    emoji = "✅" if pnl > 0 else "❌"
    pnl_text = f"{pnl:+.2f} USDT"
    print(f"{get_kst_time()} {emoji} [{action}] {symbol} | P&L: {pnl_text}")


class MultiSymbolTradingBot:
    """다중 심볼 고빈도 거래 봇"""
    
    def __init__(self):
        self.running = False
        self.connector = None
        self.strategy = None
        
        # 거래 상태
        self.balance = 0.0
        self.positions = {}  # {symbol: Position}
        self.daily_pnl = 0.0
        self.daily_trades = 0
        self.trading_symbols = []
        
        # 다중 타임프레임 데이터 저장
        self.market_data = {}  # {symbol: {timeframe: DataFrame}}
        self.last_data_update = {}  # {symbol: datetime} - 마지막 데이터 업데이트 시간
        
        # 로깅 최적화를 위한 카운터
        self.data_success_count = 0
        self.data_error_count = 0
        self.last_log_time = datetime.now()
        self.analysis_count = 0
        self.signal_count = 0
        self.last_summary_time = datetime.now()
        
        # 성과 추적
        self.trades_today = []
        self.daily_start_balance = 0.0
        
        # Contract Size 캐시 (동적으로 학습)
        self.contract_sizes = self.load_contract_sizes()  # {symbol: contract_size}
        
    def initialize(self) -> bool:
        """봇 초기화"""
        try:
            log_info("INIT", "다중 심볼 고빈도 거래 봇 초기화 시작", "🚀")
            
            # Gate.io 연결
            self.connector = GateIOConnector(
                api_key=settings.api.api_key,
                secret_key=settings.api.secret_key,
                testnet=settings.api.testnet
            )
            
            # 연결 테스트
            if not self.connector.test_connection():
                log_error("Gate.io 연결 실패")
                return False
            
            # 시뮬레이션 모드 확인
            simulation_mode = os.getenv('SIMULATION_MODE', 'False').lower() == 'true'
            
            if simulation_mode:
                self.balance = float(os.getenv('INITIAL_BALANCE', 10000))
                self.daily_start_balance = self.balance
                log_info("SIM", f"초기 잔고: {self.balance:.2f} USDT (시뮬레이션 모드)", "🎮")
                self.trading_symbols = ['BTC_USDT', 'ETH_USDT', 'BNB_USDT']
            else:
                # 실제 거래 모드
                account_info = self.connector.get_futures_balance()
                if account_info:
                    self.balance = float(account_info.get('available_balance', 0))
                    self.daily_start_balance = self.balance
                    log_info("BALANCE", f"현재 잔고: {self.balance:.2f} USDT", "💰")
                else:
                    log_error("계정 정보 조회 실패")
                    return False
                
                # 거래량 상위 심볼 조회
                self.trading_symbols = self.connector.get_top_volume_symbols(
                    settings.trading.symbols_count
                )
                
                # 각 심볼별 레버리지 설정
                log_info("LEVERAGE", f"레버리지 {settings.trading.leverage}배 설정 중...", "⚙️")
                for symbol in self.trading_symbols:
                    result = self.connector.set_leverage(symbol, settings.trading.leverage)
                    if not result:
                        log_info("WARNING", f"{symbol} 레버리지 설정 실패 (기존값 유지)", "⚠️")
            
            log_success(f"거래 대상 설정 완료: {len(self.trading_symbols)}개 심볼")
            
            # 전략 초기화
            self.strategy = FinalHighFrequencyStrategy()
            
            # Discord 알림
            total_allocation = self.balance * 0.10
            discord_notifier.send_bot_status(
                "started", 
                f"다중심볼 거래봇 시작\\n거래대상: {len(self.trading_symbols)}개\\n총잔고: {self.balance:.2f} USDT\\n사용자금: {total_allocation:.2f} USDT (10%)"
            )
            
            return True
            
        except Exception as e:
            log_error(f"초기화 실패: {e}")
            return False
    
    def collect_multi_timeframe_data(self, symbol: str) -> Dict:
        """다중 타임프레임 데이터 수집 (최적화됨)"""
        try:
            current_time = datetime.now()
            
            # 첫 번째 호출이거나 30초 이상 경과한 경우에만 새 데이터 수집 (엄격하게)
            need_update = (
                symbol not in self.last_data_update or
                current_time - self.last_data_update[symbol] > timedelta(seconds=30)
            )
            
            if not need_update and symbol in self.market_data:
                # 기존 데이터에 현재 가격만 업데이트
                try:
                    ticker = self.connector.get_futures_ticker(symbol)
                    if ticker and 'last_price' in ticker:
                        self.market_data[symbol]['current_price'] = ticker['last_price']
                        # 캐시된 데이터 사용도 성공으로 카운트
                        self.data_success_count += 1
                        return self.market_data[symbol]
                except Exception:
                    pass  # 티커 조회 실패시 새 데이터 수집
            
            # 초기 로드인 경우 1000개, 업데이트인 경우 20개만 (더 적게)
            candle_limit = settings.trading.candle_limit if symbol not in self.market_data else 20
            
            # LTF (1분) 데이터 수집
            ltf_data = self.connector.get_futures_klines(
                symbol, 
                settings.trading.ltf_timeframe, 
                candle_limit
            )
            
            if ltf_data.empty:
                return self.market_data.get(symbol, {})
            
            # 기존 데이터가 있으면 새 데이터와 합치기 (중복 제거)
            if symbol in self.market_data and not self.market_data[symbol]['ltf'].empty:
                existing_ltf = self.market_data[symbol]['ltf']
                # 최신 시점부터 합치기
                latest_time = existing_ltf['timestamp'].iloc[-1]
                new_data = ltf_data[ltf_data['timestamp'] > latest_time]
                
                if not new_data.empty:
                    ltf_data = pd.concat([existing_ltf.iloc[-500:], new_data]).drop_duplicates('timestamp').reset_index(drop=True)
                else:
                    ltf_data = existing_ltf
            
            # LTF 데이터에서 HTF (15분) 리샘플링
            ltf_data_indexed = ltf_data.set_index('timestamp')
            htf_data = ltf_data_indexed.resample('15T').agg({
                'open': 'first',
                'high': 'max',
                'low': 'min', 
                'close': 'last',
                'volume': 'sum'
            }).dropna().reset_index()
            
            result = {
                'htf': htf_data,
                'ltf': ltf_data,
                'current_price': ltf_data['close'].iloc[-1] if not ltf_data.empty else 0
            }
            
            # 데이터 캐시 및 업데이트 시간 기록
            self.market_data[symbol] = result
            self.last_data_update[symbol] = current_time
            
            self.data_success_count += 1
            return result
            
        except Exception as e:
            self.data_error_count += 1
            # 에러만 간단히 출력 (상세 내용은 에러 발생시에만)
            print(f"{get_kst_time()} ❌ [ERROR] {symbol} 데이터 수집 실패: {str(e)}")
            return self.market_data.get(symbol, {})

    def process_symbol(self, symbol: str) -> None:
        """개별 심볼 처리"""
        try:
            # 다중 타임프레임 데이터 수집
            data = self.collect_multi_timeframe_data(symbol)
            if not data or data['htf'].empty or data['ltf'].empty:
                return
            
            # 분석 카운트 증가
            self.analysis_count += 1
            
            # 데이터 저장
            if symbol not in self.market_data:
                self.market_data[symbol] = {}
            self.market_data[symbol] = data
            
            current_price = data['current_price']
            
            # 현재 포지션 확인
            if symbol in self.positions:
                position = self.positions[symbol]
                # 청산 조건 체크
                exit_reason = self.check_exit_conditions(position, current_price)
                if exit_reason:
                    self.close_position(symbol, exit_reason, current_price)
            else:
                # HTF 트렌드 확인 후 신호 생성
                htf_trend = self.get_htf_trend(data['htf'])
                if htf_trend == 'neutral':
                    return  # 명확한 트렌드가 없으면 거래 안함
                
                # LTF에서 진입 신호 생성 (HTF 트렌드와 일치하는 방향만)
                signal = self.strategy.get_signal(data['ltf'], len(data['ltf'])-1)
                
                # 전략 분석 상태 로그 (디버깅용)
                if signal.signal_type != 'HOLD':
                    self.signal_count += 1
                    log_info("ANALYSIS", f"{symbol}: {signal.signal_type} 신호 (신뢰도: {signal.confidence:.2f}, 트렌드: {htf_trend})", "🔍")
                
                if (signal.signal_type in ['BUY', 'SELL'] and 
                    signal.confidence >= 0.3 and
                    self.is_signal_aligned_with_trend(signal.signal_type, htf_trend)):
                    
                    self.open_position(symbol, signal, current_price)
                    
        except Exception as e:
            log_error(f"{symbol} 처리 오류: {e}")
    
    def get_htf_trend(self, htf_data: pd.DataFrame) -> str:
        """HTF 트렌드 분석 (15분봉)"""
        if len(htf_data) < 20:
            return 'neutral'
        
        # 간단한 EMA 기반 트렌드 확인
        try:
            closes = htf_data['close']
            ema_20 = closes.ewm(span=20).mean().iloc[-1]
            ema_50 = closes.ewm(span=50).mean().iloc[-1]
            current_price = closes.iloc[-1]
            
            # 트렌드 강도 확인
            if current_price > ema_20 > ema_50:
                return 'bullish'
            elif current_price < ema_20 < ema_50:
                return 'bearish'
            else:
                return 'neutral'
                
        except Exception:
            return 'neutral'
    
    def is_signal_aligned_with_trend(self, signal_type: str, htf_trend: str) -> bool:
        """신호가 HTF 트렌드와 일치하는지 확인"""
        if htf_trend == 'bullish' and signal_type == 'BUY':
            return True
        elif htf_trend == 'bearish' and signal_type == 'SELL':
            return True
        return False

    def get_contract_size(self, symbol: str) -> float:
        """Gate.io Contract Size 반환 (API 조회 → 캐시 → 기본값 순)"""
        # 캐시된 값이 있으면 사용
        if symbol in self.contract_sizes:
            return self.contract_sizes[symbol]
        
        # API에서 Contract 정보 조회
        try:
            contract_info = self.connector.get_contract_info(symbol)
            if contract_info and 'contract_size' in contract_info:
                contract_size = contract_info['contract_size']
                # 캐시에 저장
                self.contract_sizes[symbol] = contract_size
                self.save_contract_sizes()
                print(f"{get_kst_time()} 🔍 [API] {symbol} Contract Size 조회: {contract_size}")
                return contract_size
        except Exception as e:
            print(f"{get_kst_time()} ⚠️ [WARNING] {symbol} Contract Size API 조회 실패: {e}")
        
        # API 조회 실패시 알려진 값 사용
        known_sizes = {
            'XRP_USDT': 10,
            'BTC_USDT': 0.0001,
            'ETH_USDT': 0.01,
            'DOGE_USDT': 10,
            'SOL_USDT': 1,
            'PEPE_USDT': 10000000,  # PEPE는 천만개 단위
            'FARTCOIN_USDT': 1,
        }
        
        if symbol in known_sizes:
            fallback_size = known_sizes[symbol]
            print(f"{get_kst_time()} 📋 [KNOWN] {symbol} Contract Size (기본값): {fallback_size}")
            self.contract_sizes[symbol] = fallback_size
            return fallback_size
        
        # 완전히 모르는 심볼은 1로 설정
        print(f"{get_kst_time()} ⚠️ [UNKNOWN] {symbol} Contract Size 미확인 (기본값 1 사용)")
        return 1
    
    def load_contract_sizes(self) -> Dict[str, float]:
        """저장된 Contract Size 로드"""
        try:
            contract_file = "contract_sizes.json"
            if os.path.exists(contract_file):
                with open(contract_file, 'r') as f:
                    return json.load(f)
        except Exception as e:
            log_info("LOAD", f"Contract Size 파일 로드 실패: {e}", "⚠️")
        return {}
    
    def save_contract_sizes(self):
        """Contract Size 파일에 저장"""
        try:
            contract_file = "contract_sizes.json"
            with open(contract_file, 'w') as f:
                json.dump(self.contract_sizes, f, indent=2)
        except Exception as e:
            log_info("SAVE", f"Contract Size 파일 저장 실패: {e}", "⚠️")
    
    def learn_contract_size(self, symbol: str, sdk_size: float, actual_size: float):
        """주문 결과를 통해 Contract Size 학습"""
        if sdk_size > 0:
            detected_size = actual_size / sdk_size
            # 기존 값과 다르면 업데이트
            if symbol not in self.contract_sizes or abs(self.contract_sizes[symbol] - detected_size) > 0.0001:
                self.contract_sizes[symbol] = detected_size
                log_info("LEARN", f"{symbol} Contract Size 학습: 1 계약 = {detected_size} {symbol.split('_')[0]}", "🧠")
                self.save_contract_sizes()  # 즉시 저장
    
    def get_actual_size(self, symbol: str, sdk_size: float) -> float:
        """SDK 크기를 실제 크기로 변환"""
        contract_size = self.get_contract_size(symbol)
        return sdk_size * contract_size

    def open_position(self, symbol: str, signal: Signal, price: float):
        """포지션 진입"""
        try:
            # 포지션 크기 계산 (총 시드의 10%를 15개 심볼에 분산)
            total_allocation = self.balance * 0.10  # 총 시드의 10%
            per_symbol_allocation = total_allocation / len(self.trading_symbols)  # 심볼당 할당
            
            # Contract Size를 고려한 크기 계산
            contract_size = self.get_contract_size(symbol)
            max_contracts = int((per_symbol_allocation * settings.trading.leverage) / (contract_size * price))
            size = max(1, max_contracts)
            
            actual_amount = size * contract_size
            coin_name = symbol.split('_')[0]
            
            # Contract Size 정보 표시 (1이어도 정상)
            log_info("CONTRACT", f"{symbol}: {size} 계약 = {actual_amount} {coin_name} (Contract Size: {contract_size})", "📋")
            
            if size <= 0:
                return
            
            # 주문 실행
            side = 'long' if signal.signal_type == 'BUY' else 'short'
            order = self.connector.create_futures_order(
                symbol=symbol,
                side=side,
                size=size,
                order_type='market'
            )
            
            if order and order.get('order_id'):
                # Contract Size 학습 (주문 결과에서 실제 크기 확인)
                order_actual_size = order.get('size', size)
                if order_actual_size != size:
                    self.learn_contract_size(symbol, size, order_actual_size)
                
                # ATR 기반 동적 익절/손절 계산
                market_data = self.collect_market_data(symbol)
                if market_data and 'ltf' in market_data and not market_data['ltf'].empty:
                    df = market_data['ltf']
                    if len(df) >= settings.trading.atr_period:
                        # ATR 계산
                        from final_high_frequency_strategy import TechnicalIndicators
                        atr = TechnicalIndicators.atr(
                            df['high'], df['low'], df['close'], 
                            settings.trading.atr_period
                        ).iloc[-1]
                        
                        # ATR 기반 손절/익절 설정
                        if side == 'long':
                            stop_loss = price - (atr * settings.trading.stop_loss_atr_mult)
                            take_profit = price + (atr * settings.trading.take_profit_atr_mult)
                        else:
                            stop_loss = price + (atr * settings.trading.stop_loss_atr_mult)
                            take_profit = price - (atr * settings.trading.take_profit_atr_mult)
                        
                        log_info("ATR", f"{symbol} ATR: {atr:.6f}, 손절: {stop_loss:.6f}, 익절: {take_profit:.6f}", "📊")
                    else:
                        # 데이터 부족시 기본값 사용
                        stop_loss = price * (0.997 if side == 'long' else 1.003)
                        take_profit = price * (1.003 if side == 'long' else 0.997)
                        log_info("ATR", f"{symbol} ATR 데이터 부족 - 고정 0.3% 사용", "⚠️")
                else:
                    # 시장 데이터 없을 시 기본값
                    stop_loss = price * (0.997 if side == 'long' else 1.003)
                    take_profit = price * (1.003 if side == 'long' else 0.997)
                    log_info("ATR", f"{symbol} 시장 데이터 없음 - 고정 0.3% 사용", "⚠️")

                # 포지션 기록
                position = Position(
                    symbol=symbol,
                    side=side,
                    size=size,  # SDK 크기 저장
                    entry_price=price,
                    entry_time=datetime.now(),
                    stop_loss=stop_loss,
                    take_profit=take_profit
                )
                
                self.positions[symbol] = position
                self.daily_trades += 1
                
                log_trade(side, symbol, price, size)
                
                # Discord 알림
                discord_notifier.send_position_opened(
                    side, symbol, price, size, 
                    position.stop_loss, position.take_profit
                )
                
        except Exception as e:
            log_error(f"{symbol} 포지션 진입 실패: {e}")
    
    def close_position(self, symbol: str, reason: str, price: float):
        """포지션 청산"""
        try:
            if symbol not in self.positions:
                return
                
            position = self.positions[symbol]
            
            # 청산 주문
            close_side = 'short' if position.side == 'long' else 'long'
            order = self.connector.create_futures_order(
                symbol=symbol,
                side=close_side,
                size=position.size,
                order_type='market'
            )
            
            if order and order.get('order_id'):
                # Contract Size를 고려한 손익 계산
                actual_size = self.get_actual_size(symbol, position.size)
                
                if position.side == 'long':
                    pnl = (price - position.entry_price) * actual_size
                else:
                    pnl = (position.entry_price - price) * actual_size
                
                pnl_pct = (pnl / (position.entry_price * actual_size)) * 100 * settings.trading.leverage
                
                self.daily_pnl += pnl
                self.balance += pnl
                
                # 거래 기록
                trade = {
                    'timestamp': datetime.now(),
                    'symbol': symbol,
                    'side': position.side,
                    'entry_price': position.entry_price,
                    'exit_price': price,
                    'size': position.size,
                    'pnl': pnl,
                    'pnl_pct': pnl_pct,
                    'reason': reason
                }
                self.trades_today.append(trade)
                
                log_position(f"{reason.upper()}", symbol, pnl)
                
                # Discord 알림
                discord_notifier.send_position_closed(
                    position.side, symbol, position.entry_price, 
                    price, position.size, pnl, pnl_pct, reason
                )
                
                # 포지션 제거
                del self.positions[symbol]
                
        except Exception as e:
            log_error(f"{symbol} 포지션 청산 실패: {e}")
    
    def check_exit_conditions(self, position: Position, current_price: float) -> Optional[str]:
        """청산 조건 확인"""
        # 시간 기반 청산 (10분)
        if datetime.now() - position.entry_time > timedelta(minutes=10):
            return "시간만료"
        
        # 손절/익절
        if position.side == 'long':
            if current_price >= position.take_profit:
                return "익절"
            elif current_price <= position.stop_loss:
                return "손절"
        else:
            if current_price <= position.take_profit:
                return "익절"
            elif current_price >= position.stop_loss:
                return "손절"
        
        return None
    
    def trading_loop(self):
        """메인 거래 루프"""
        log_info("START", "다중 심볼 고빈도 거래 시작", "🚀")
        
        while self.running:
            try:
                # 데이터 수집 상태 리셋
                self.data_success_count = 0
                self.data_error_count = 0
                self.analysis_count = 0
                self.signal_count = 0
                
                # 각 심볼 순차 처리 (조용히)
                for symbol in self.trading_symbols:
                    if not self.running:
                        break
                    self.process_symbol(symbol)
                    time.sleep(0.1)  # API 호출 간격
                
                # 데이터 수집 및 분석 결과 요약 로그 (신호가 있거나 30초마다)
                current_time = datetime.now()
                if current_time - self.last_summary_time > timedelta(seconds=30):
                    # 30초마다 한 번 상태 요약 출력
                    if self.signal_count > 0:
                        log_info("STATUS", f"분석 완료: {self.analysis_count}개 심볼, {self.signal_count}개 신호 감지, 데이터 {self.data_success_count}/{len(self.trading_symbols)} 성공", "⚡")
                    else:
                        log_info("STATUS", f"분석 완료: {self.analysis_count}개 심볼, 신호 없음, 데이터 {self.data_success_count}/{len(self.trading_symbols)} 성공", "📈")
                    self.last_summary_time = current_time
                elif self.signal_count > 0:
                    # 신호가 감지되면 즉시 로그 출력
                    log_info("DATA", f"데이터 수집 완료: {self.data_success_count}/{len(self.trading_symbols)}, 신호 {self.signal_count}개 감지", "⚡")
                elif self.data_error_count > 0:
                    # 오류가 있으면 로그 출력
                    log_info("DATA", f"데이터 수집: {self.data_success_count}개 성공, {self.data_error_count}개 실패", "⚠️")
                    
                    # 실패한 심볼들 확인
                    failed_symbols = []
                    for symbol in self.trading_symbols:
                        if symbol not in self.market_data or not self.market_data[symbol]:
                            failed_symbols.append(symbol)
                    
                    if failed_symbols:
                        print(f"{get_kst_time()} 🚨 [FAILED_SYMBOLS] 데이터 수집 실패: {', '.join(failed_symbols)}")
                        
                # 신호 없고 오류 없으면 로그 생략 (스팸 방지)
                
                # 5초 대기 (고빈도 거래)
                time.sleep(5)
                
            except Exception as e:
                log_error(f"거래 루프 오류: {e}")
                time.sleep(30)
    
    def start(self):
        """봇 시작"""
        if not self.initialize():
            return False
        
        self.running = True
        
        # 거래 스레드 시작
        trading_thread = threading.Thread(target=self.trading_loop)
        trading_thread.daemon = True
        trading_thread.start()
        
        log_success("다중 심볼 거래 봇 가동 시작")
        return True
    
    def stop(self):
        """봇 중지"""
        self.running = False
        
        # 모든 포지션 청산
        for symbol in list(self.positions.keys()):
            try:
                current_price = self.connector.get_futures_ticker(symbol)['last_price']
                self.close_position(symbol, "봇종료", current_price)
            except:
                pass
        
        log_info("STOP", "봇이 안전하게 중지되었습니다", "⭕")


def main():
    """메인 함수 - SMC 스타일"""
    print("=" * 60)
    print("Gate.io 다중 심볼 고빈도 거래 봇")
    print("=" * 60)
    
    # 설정 출력 - SMC 스타일
    log_info("CONFIG", f"거래 대상: 거래량 상위 {settings.trading.symbols_count}개", "🎯")
    log_info("CONFIG", f"레버리지: {settings.trading.leverage}배 | 자금: 총 시드 10%", "⚙️")
    log_info("CONFIG", f"체크 주기: 5초 (고빈도) | HTF: 15m / LTF: 1m", "🕰️")
    log_info("CONFIG", f"테스트넷: {'예' if settings.api.testnet else '아니오'}", "🎮" if settings.api.testnet else "🔴")
    print("=" * 60)
    
    # 봇 시작
    bot = MultiSymbolTradingBot()
    
    try:
        if bot.start():
            log_success("봇이 실행 중입니다. 중지하려면 Ctrl+C를 누르세요...")
            
            while True:
                time.sleep(1)
                
    except KeyboardInterrupt:
        log_info("STOP", "봇 중지 요청 수신", "⚠️")
        bot.stop()
        log_success("봇이 안전하게 종료되었습니다")


if __name__ == "__main__":
    main()