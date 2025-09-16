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
        self.winning_trades_today = 0
        self.last_daily_summary = datetime.now().date()
        
        # 동적 심볼 리스트 관리 (매시 정각 업데이트)
        self.last_symbol_update_hour = -1  # 마지막 업데이트한 시간
        
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
                
                # 각 심볼별 레버리지 및 마진 모드 설정 (통합 로그)
                log_info("LEVERAGE", f"레버리지 {settings.trading.leverage}배 & Isolated 모드 설정 중...", "⚙️")
                
                failed_symbols = []
                max_leverage_symbols = []
                
                for symbol in self.trading_symbols:
                    # 레버리지 설정
                    leverage_result = self.connector.set_leverage(symbol, settings.trading.leverage)
                    
                    # Isolated 모드 설정 (항상 성공하므로 별도 체크 불필요)
                    self.connector.set_position_mode_isolated(symbol)
                    
                    # 결과 분류
                    if leverage_result == "failed":
                        failed_symbols.append(symbol)
                    elif leverage_result == "max_leverage":
                        max_leverage_symbols.append(symbol)
                
                # 통합 결과 출력
                success_count = len(self.trading_symbols) - len(failed_symbols)
                log_info("LEVERAGE", f"✅ {success_count}개 심볼 설정 완료: {settings.trading.leverage}배 레버리지 + Isolated 모드", "⚙️")
                
                # 특이사항 별도 알림
                if failed_symbols:
                    log_info("WARNING", f"⚠️ 레버리지 설정 실패 (기존값 유지): {', '.join(failed_symbols)}", "⚠️")
                
                if max_leverage_symbols:
                    log_info("WARNING", f"🔧 최대 레버리지로 자동 설정: {', '.join(max_leverage_symbols)}", "🔧")
            
            log_success(f"거래 대상 설정 완료: {len(self.trading_symbols)}개 심볼")
            
            # 전략 초기화
            self.strategy = FinalHighFrequencyStrategy()
            
            # Discord 알림
            total_allocation = self.balance * settings.trading.position_size_pct
            discord_notifier.send_multi_symbol_bot_started(
                symbols_count=len(self.trading_symbols),
                balance=self.balance,
                allocated_amount=total_allocation,
                allocation_pct=settings.trading.position_size_pct,
                leverage=settings.trading.leverage
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
                    if exit_reason == "반익절":
                        # 반익절 실행
                        if self.execute_partial_close(position, current_price):
                            # 반익절 성공하면 포지션 유지하고 계속 모니터링
                            pass
                        else:
                            # 반익절 실패하면 전량 청산
                            self.close_position(symbol, "반익절실패", current_price)
                    else:
                        # 일반 청산 (손절, 익절, 트레일링익절 등)
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

                    # Discord 거래 신호 알림
                    reason = f"HTF 트렌드: {htf_trend}, 분석: {signal.reason if hasattr(signal, 'reason') else '기술적 분석'}"
                    discord_notifier.send_trade_signal(
                        signal_type=signal.signal_type,
                        symbol=symbol,
                        price=current_price,
                        reason=reason,
                        confidence=signal.confidence
                    )
                
                if (signal.signal_type in ['BUY', 'SELL'] and 
                    signal.confidence >= settings.trading.confidence_threshold and
                    self.is_signal_aligned_with_trend(signal.signal_type, htf_trend, signal.confidence)):
                    
                    # 진입 조건에 대한 상세 로그 추가
                    trend_reason = ""
                    if signal.confidence >= 0.7:
                        trend_reason = "강한 신호로 역추세 진입"
                    elif signal.confidence >= 0.5 and htf_trend == 'neutral':
                        trend_reason = "중간 신호로 중립 트렌드 진입"
                    elif (htf_trend == 'bullish' and signal.signal_type == 'BUY') or (htf_trend == 'bearish' and signal.signal_type == 'SELL'):
                        trend_reason = "트렌드 일치 진입"
                    
                    log_info("ENTRY", f"{symbol} {signal.signal_type} 진입 승인: {trend_reason} (신뢰도: {signal.confidence:.2f})", "🚀")
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
    
    def is_signal_aligned_with_trend(self, signal_type: str, htf_trend: str, confidence: float = 0.0) -> bool:
        """신호가 HTF 트렌드와 일치하는지 확인 (강한 신호는 역추세도 허용)"""
        # 1. 강한 신호(0.7+ 신뢰도)는 트렌드 무관하게 진입 허용
        if confidence >= 0.7:
            return True
            
        # 2. 중간 강도 신호(0.5+ 신뢰도)는 neutral 트렌드에서도 허용
        if confidence >= 0.5 and htf_trend == 'neutral':
            return True
            
        # 3. 일반적인 트렌드 일치 확인
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
            'PYTH_USDT': 10,  # 거래소 확인된 정확한 값
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

    def check_existing_positions(self, symbol: str) -> bool:
        """실제 포지션이 있는지 확인"""
        try:
            positions = self.connector.get_futures_positions()
            for pos in positions:
                # Gate.io API 응답 구조에 맞게 수정
                pos_symbol = pos.get('contract') or pos.get('symbol') or pos.get('instrument_name')
                pos_size = float(pos.get('size', 0))
            
                if pos_symbol == symbol and pos_size > 0:
                    log_info("EXISTS", f"{symbol} 거래소에 포지션 존재 감지", "⚠️")
                    return True
            return False
        except Exception as e:
            log_error(f"{symbol} 포지션 확인 실패: {e}")
            return False

    def sync_positions_with_exchange(self):
        """거래소와 포지션 상태 동기화"""
        try:
            exchange_positions = self.connector.get_futures_positions()
            synced_count = 0
        
            # 거래소에는 없는데 프로그램에 있는 포지션 제거
            for symbol in list(self.positions.keys()):
                found = False
                for pos in exchange_positions:
                    # Gate.io API 응답 구조에 맞게 수정
                    pos_symbol = pos.get('contract') or pos.get('symbol') or pos.get('instrument_name')
                    pos_size = float(pos.get('size', 0))
                
                    if pos_symbol == symbol and pos_size > 0:
                        found = True
                        break
            
                if not found:
                    log_info("SYNC", f"{symbol} 포지션이 거래소에서 청산됨 - 프로그램 기록 제거", "🔄")
                    del self.positions[symbol]
                    synced_count += 1
        
            if synced_count > 0:
                log_info("SYNC", f"{synced_count}개 포지션 동기화 완료", "✅")
            
        except Exception as e:
            log_error(f"포지션 동기화 실패: {e}")
            # 디버깅을 위해 실제 응답 구조 출력
            try:
                positions = self.connector.get_futures_positions()
                if positions:
                    log_info("DEBUG", f"포지션 응답 구조: {positions[0].keys() if positions else 'Empty'}", "🔍")
            except:
                pass
    
    def save_contract_sizes(self):
        """Contract Size 파일에 저장"""
        try:
            contract_file = "contract_sizes.json"
            with open(contract_file, 'w') as f:
                json.dump(self.contract_sizes, f, indent=2)
        except Exception as e:
            log_info("SAVE", f"Contract Size 파일 저장 실패: {e}", "⚠️")
    
    def learn_contract_size(self, symbol: str, sdk_size: float, actual_size: float):
        """주문 결과를 통해 Contract Size 학습 (부분 체결시 학습 안 함)"""
        if sdk_size > 0:
            detected_size = actual_size / sdk_size
            
            # 부분 체결인 경우 학습하지 않음 (잘못된 Contract Size 학습 방지)
            expected_size = sdk_size * self.get_contract_size(symbol)
            if abs(actual_size - expected_size) > expected_size * 0.1:  # 10% 이상 차이나면 부분 체결로 판단
                log_info("SKIP", f"{symbol} 부분 체결 감지 - Contract Size 학습 안 함 (예상: {expected_size:.1f}, 실제: {actual_size:.1f})", "⚠️")
                return
            
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
            # 기존 포지션 확인 (프로그램 + 거래소)
            if symbol in self.positions:
                log_info("SKIP", f"{symbol} 이미 포지션 보유중 - 스킵", "⚠️")
                return
                
            if self.check_existing_positions(symbol):
                log_info("SKIP", f"{symbol} 거래소에 포지션 존재 - 스킵", "⚠️")
                return

            # settings에서 포지션 크기 비율 가져오기
            safe_allocation = self.balance * settings.trading.position_size_pct
            log_info("ALLOCATION", f"{symbol} 시드 배분: {safe_allocation:.2f} USDT (총 시드의 {settings.trading.position_size_pct:.1%})", "💰")

            # Contract Size를 고려한 크기 계산 (API에서 정확한 값 조회)
            contract_info = self.connector.get_contract_info(symbol)
            if contract_info and 'contract_size' in contract_info:
                contract_size = contract_info['contract_size']
                # 정확한 값으로 캐시 업데이트
                self.contract_sizes[symbol] = contract_size
            else:
                contract_size = self.get_contract_size(symbol)

            # 필요한 마진 = (Contract Size × 가격) / 레버리지 (settings에서 가져옴)
            required_margin_per_contract = (contract_size * price) / settings.trading.leverage
            max_contracts = int(safe_allocation / required_margin_per_contract)
            size = max(1, max_contracts)

            log_info("CALC", f"{symbol} 마진계산: {safe_allocation:.2f} USDT ÷ {required_margin_per_contract:.6f} = {max_contracts} 계약 ({settings.trading.leverage}배)", "🧮")

            actual_amount = size * contract_size
            coin_name = symbol.split('_')[0]

            # Contract Size 정보 표시
            log_info("CONTRACT", f"{symbol}: {size} 계약 = {actual_amount} {coin_name} (Contract Size: {contract_size})", "📋")
            log_info("ORDER", f"{symbol} 원하는 수량: {actual_amount} {coin_name}", "📊")
            log_info("ORDER", f"Contract Size: {contract_size}, SDK 주문: {size}계약", "📊")
            log_info("ORDER", f"실제 거래: {size}계약 = {actual_amount} {coin_name}", "✅")

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
                market_data = self.market_data.get(symbol)
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

                # 포지션 기록 (트레일링 익절 필드 초기화)
                position = Position(
                    symbol=symbol,
                    side=side,
                    size=size,
                    entry_price=price,
                    entry_time=datetime.now(),
                    stop_loss=stop_loss,
                    take_profit=take_profit,
                    status='open',
                    original_size=size,
                    partial_closed=False,
                    partial_pnl=0.0,
                    trailing_price=None,
                    trailing_stop=None,
                    breakeven_set=False,
                    original_stop_loss=stop_loss,
                    _atr_stop_switched=False
                )  # 괄호 하나만

                self.positions[symbol] = position
                self.daily_trades += 1

                log_trade(side, symbol, price, size)

                # Discord 알림
                discord_notifier.send_position_opened(
                    side, symbol, price, size, 
                    position.stop_loss, position.take_profit,
                    contract_size=contract_size
                )

        except Exception as e:
            log_error(f"{symbol} 포지션 진입 실패: {e}")

    def close_position(self, symbol: str, reason: str, price: float):
        """포지션 청산 (오류 방지 강화)"""
        try:
            if symbol not in self.positions:
                return

            position = self.positions[symbol]
        
            # 청산 주문 시도
            close_side = 'short' if position.side == 'long' else 'long'
        
            try:
                order = self.connector.create_futures_order(
                    symbol=symbol,
                    side=close_side,
                    size=position.size,
                    order_type='market'
                )
                order_success = order and order.get('order_id')
            except Exception as e:
                log_error(f"{symbol} 청산 주문 실패: {e}")
                order_success = False

            # 주문 성공 여부와 관계없이 손익 계산 및 포지션 제거
            actual_size = self.get_actual_size(symbol, position.size)
        
            if position.side == 'long':
                pnl = (price - position.entry_price) * actual_size
            else:
                pnl = (position.entry_price - price) * actual_size
        
            pnl_pct = (pnl / (position.entry_price * actual_size)) * 100 * settings.trading.leverage
        
            # 반익절 수익 안전하게 가져오기
            partial_pnl = getattr(position, 'partial_pnl', 0.0)
            total_pnl = partial_pnl + pnl
        
            if order_success:
                # 정상 청산
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
            
                # 승리 거래 카운트
                if total_pnl > 0:
                    self.winning_trades_today += 1
            
                # Discord 알림
                try:
                    discord_notifier.send_position_closed(
                        position.side, symbol, position.entry_price,
                        price, position.size, pnl, pnl_pct, reason,
                        contract_size=self.get_contract_size(symbol),
                        partial_pnl=partial_pnl
                    )
                except:
                    pass  # Discord 오류는 무시
            else:
                # 청산 실패시 로그만
                log_error(f"{symbol} 청산 주문 실패 - 포지션 기록은 제거")
        
            # 포지션 제거 (무조건)
            del self.positions[symbol]
            log_info("CLEANUP", f"{symbol} 포지션 기록 제거 완료", "🧹")
        
        except Exception as e:
            log_error(f"{symbol} 포지션 청산 처리 오류: {e}")
            # 최종 안전장치: 오류시에도 포지션 제거
            if symbol in self.positions:
                del self.positions[symbol]
                log_info("FORCE", f"{symbol} 강제 포지션 제거", "⚠️")
    
    def check_exit_conditions(self, position: Position, current_price: float) -> Optional[str]:
        """개선된 청산 조건 확인 (트레일링 익절 + 동적 손절)"""
        
        # 1. 손절 체크 (동적 전환)
        effective_stop_loss = self.get_effective_stop_loss(position, current_price)
        
        if position.side == 'long':
            if current_price <= effective_stop_loss:
                if position.breakeven_set and abs(effective_stop_loss - position.entry_price) < 0.01:
                    return "본전손절"
                return "손절"
        else:
            if current_price >= effective_stop_loss:
                if position.breakeven_set and abs(effective_stop_loss - position.entry_price) < 0.01:
                    return "본전손절"
                return "손절"
        
        # 2. 반익절 체크 (아직 안 했을 때만)
        if not position.partial_closed:
            if position.side == 'long':
                if current_price >= position.take_profit:
                    return "반익절"
            else:
                if current_price <= position.take_profit:
                    return "반익절"
        
        # 3. 트레일링 체크 (반익절 후)
        if position.partial_closed:
            trailing_result = self.check_trailing_conditions(position, current_price)
            if trailing_result:
                return trailing_result
        
        return None
    
    def get_effective_stop_loss(self, position: Position, current_price: float) -> float:
        """현재 상황에 맞는 손절가 반환"""
        
        if not position.partial_closed:
            # 반익절 전: 기존 ATR 손절
            return position.stop_loss
        
        if not position.breakeven_set:
            # 예외 상황: 반익절했는데 본전설정 안됨
            return position.stop_loss
        
        # 반익절 후: 본전 vs ATR 손절 비교
        breakeven_stop = position.entry_price
        atr_stop = self.calculate_atr_stop_loss(position, current_price)
        
        if position.side == 'long':
            # 롱: ATR 손절이 본전보다 위에 있으면 ATR 사용
            if atr_stop > breakeven_stop:
                if not hasattr(position, '_atr_stop_switched') or not position._atr_stop_switched:
                    log_info("SWITCH", f"{position.symbol} 손절 전환: 본전({breakeven_stop:.6f}) → ATR({atr_stop:.6f})", "🔄")
                    position._atr_stop_switched = True
                return atr_stop
            return breakeven_stop
        else:
            # 숏: ATR 손절이 본전보다 아래 있으면 ATR 사용
            if atr_stop < breakeven_stop:
                if not hasattr(position, '_atr_stop_switched') or not position._atr_stop_switched:
                    log_info("SWITCH", f"{position.symbol} 손절 전환: 본전({breakeven_stop:.6f}) → ATR({atr_stop:.6f})", "🔄")
                    position._atr_stop_switched = True
                return atr_stop
            return breakeven_stop
    
    def calculate_atr_stop_loss(self, position: Position, current_price: float) -> float:
        """현재가 기준으로 ATR 손절가 계산"""
        try:
            market_data = self.market_data.get(position.symbol)
            if market_data and 'ltf' in market_data and not market_data['ltf'].empty:
                df = market_data['ltf']
                if len(df) >= settings.trading.atr_period:
                    from final_high_frequency_strategy import TechnicalIndicators
                    atr = TechnicalIndicators.atr(
                        df['high'], df['low'], df['close'], 
                        settings.trading.atr_period
                    ).iloc[-1]
                    
                    if position.side == 'long':
                        return current_price - (atr * settings.trading.stop_loss_atr_mult)
                    else:
                        return current_price + (atr * settings.trading.stop_loss_atr_mult)
        except Exception:
            pass
        
        # ATR 계산 실패시 기본값
        if position.side == 'long':
            return current_price * 0.997
        else:
            return current_price * 1.003
    
    def execute_partial_close(self, position: Position, current_price: float):
        """반익절 실행 + 본전 손절 설정"""
        try:
            # 50% 청산 주문
            close_size = position.original_size // 2
            if close_size <= 0:
                close_size = 1  # 최소 1계약은 청산
            
            close_side = 'short' if position.side == 'long' else 'long'
            order = self.connector.create_futures_order(
                symbol=position.symbol,
                side=close_side,
                size=close_size,
                order_type='market'
            )
            
            if order and order.get('order_id'):
                # 포지션 크기 업데이트
                position.size = position.original_size - close_size
                position.partial_closed = True
                
                # 손절을 본전(진입가)으로 변경
                position.stop_loss = position.entry_price
                position.breakeven_set = True
                
                # 트레일링 초기화
                position.trailing_price = current_price
                position._atr_stop_switched = False
                
                # 반익절 수익 계산
                actual_size = self.get_actual_size(position.symbol, close_size)
                if position.side == 'long':
                    partial_pnl = (current_price - position.entry_price) * actual_size
                else:
                    partial_pnl = (position.entry_price - current_price) * actual_size
                
                log_info("PARTIAL", f"{position.symbol} 반익절 완료: {close_size}계약 → +{partial_pnl:.2f} USDT", "💰")
                log_info("BREAKEVEN", f"{position.symbol} 손절을 본전({position.entry_price:.6f})으로 변경", "🛡️")
                
                # Discord 알림
                discord_notifier.send_partial_close_notification(
                    position.side, position.symbol, position.entry_price, 
                    current_price, close_size, partial_pnl,
                    contract_size=self.get_contract_size(position.symbol)
                )
                
                return True
        except Exception as e:
            log_error(f"{position.symbol} 반익절 실패: {e}")
            return False
    
    def check_trailing_conditions(self, position: Position, current_price: float) -> Optional[str]:
        """트레일링 익절 조건 체크"""
        try:
            # 트레일링 기준가 업데이트 (새 고점/저점)
            if position.side == 'long':
                if position.trailing_price is None or current_price > position.trailing_price:
                    position.trailing_price = current_price
                    # ATR 기반 트레일링 스톱 설정
                    atr = self.get_current_atr(position.symbol)
                    if atr:
                        position.trailing_stop = current_price - (atr * 2.0)  # ATR의 2배
                        log_info("TRAIL", f"{position.symbol} 트레일링 업데이트: 기준가 {current_price:.6f}, 스톱 {position.trailing_stop:.6f}", "🎯")
                
                # 트레일링 스톱 도달
                if position.trailing_stop and current_price <= position.trailing_stop:
                    return "트레일링익절"
            else:
                # 숏 포지션
                if position.trailing_price is None or current_price < position.trailing_price:
                    position.trailing_price = current_price
                    atr = self.get_current_atr(position.symbol)
                    if atr:
                        position.trailing_stop = current_price + (atr * 2.0)
                        log_info("TRAIL", f"{position.symbol} 트레일링 업데이트: 기준가 {current_price:.6f}, 스톱 {position.trailing_stop:.6f}", "🎯")
                
                if position.trailing_stop and current_price >= position.trailing_stop:
                    return "트레일링익절"
            
            # 반전 신호 감지
            if self.detect_reversal_signal(position.symbol):
                return "반전익절"
                
        except Exception as e:
            log_error(f"{position.symbol} 트레일링 체크 오류: {e}")
        
        return None
    
    def get_current_atr(self, symbol: str) -> Optional[float]:
        """현재 ATR 값 조회"""
        try:
            market_data = self.market_data.get(symbol)
            if market_data and 'ltf' in market_data and not market_data['ltf'].empty:
                df = market_data['ltf']
                if len(df) >= settings.trading.atr_period:
                    from final_high_frequency_strategy import TechnicalIndicators
                    atr = TechnicalIndicators.atr(
                        df['high'], df['low'], df['close'], 
                        settings.trading.atr_period
                    ).iloc[-1]
                    return atr
        except Exception:
            pass
        return None
    
    def detect_reversal_signal(self, symbol: str) -> bool:
        """반전 신호 감지"""
        try:
            market_data = self.market_data.get(symbol)
            if not market_data or 'ltf' not in market_data or market_data['ltf'].empty:
                return False
            
            df = market_data['ltf']
            if len(df) < 20:
                return False
            
            # RSI 다이버전스나 강한 반전 신호 체크
            from final_high_frequency_strategy import TechnicalIndicators
            rsi = TechnicalIndicators.rsi(df['close'], 14)
            
            # RSI 과매수/과매도 + 가격 반전 패턴
            current_rsi = rsi.iloc[-1]
            prev_rsi = rsi.iloc[-2]
            
            current_price = df['close'].iloc[-1]
            prev_price = df['close'].iloc[-2]
            
            # 과매수에서 RSI 하락 + 가격 하락 = 매도 신호
            if current_rsi > 70 and current_rsi < prev_rsi and current_price < prev_price:
                return True
            
            # 과매도에서 RSI 상승 + 가격 상승 = 매수 신호
            if current_rsi < 30 and current_rsi > prev_rsi and current_price > prev_price:
                return True
            
        except Exception:
            pass
        
        return False
    
    def update_trading_symbols(self):
        """거래량 상위 심볼 업데이트"""
        try:
            log_info("UPDATE", "거래량 상위 심볼 업데이트 시작...", "🔄")
            
            # 거래량 상위 심볼 재조회
            new_symbols = self.connector.get_top_volume_symbols(
                settings.trading.symbols_count
            )
            
            if new_symbols:
                # 기존 심볼과 비교
                added_symbols = set(new_symbols) - set(self.trading_symbols)
                removed_symbols = set(self.trading_symbols) - set(new_symbols)
                
                if added_symbols or removed_symbols:
                    log_info("SYMBOLS", f"심볼 변경: +{len(added_symbols)} -{len(removed_symbols)}", "📊")
                    if added_symbols:
                        log_info("ADDED", f"추가: {', '.join(added_symbols)}", "➕")
                    if removed_symbols:
                        log_info("REMOVED", f"제거: {', '.join(removed_symbols)}", "➖")
                        
                        # 제거된 심볼의 포지션이 있으면 청산
                        for symbol in removed_symbols:
                            if symbol in self.positions:
                                try:
                                    current_price = self.connector.get_futures_ticker(symbol)['last_price']
                                    self.close_position(symbol, "심볼제거", current_price)
                                    log_info("CLOSE", f"{symbol} 심볼 제거로 포지션 청산", "🔄")
                                except:
                                    pass
                
                self.trading_symbols = new_symbols
                log_success(f"심볼 업데이트 완료: {len(self.trading_symbols)}개")
            
        except Exception as e:
            log_error(f"심볼 업데이트 실패: {e}")
    
    def trading_loop(self):
        """메인 거래 루프"""
        log_info("START", "다중 심볼 고빈도 거래 시작", "🚀")
        
        while self.running:
            try:
                # 일일 요약 체크 (새로운 날이 시작되었는지 확인)
                self.check_daily_summary()

                # 매시 정각에 거래량 상위 심볼 업데이트
                current_time = datetime.now()
                current_hour = current_time.hour
                
                if (current_hour != self.last_symbol_update_hour and 
                    current_time.minute == 0 and current_time.second < 10):  # 정각 10초 이내
                    self.update_trading_symbols()
                    self.last_symbol_update_hour = current_hour

                # 5분마다 포지션 동기화 (추가된 부분)
                if current_time.minute % 5 == 0 and current_time.second < 10:
                    self.sync_positions_with_exchange()

                
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
    
    def send_daily_summary(self):
        """일일 거래 요약 전송"""
        try:
            today = datetime.now().strftime("%Y-%m-%d")
            current_balance = self.balance
            total_pnl = current_balance - self.daily_start_balance
            win_rate = (self.winning_trades_today / self.daily_trades) if self.daily_trades > 0 else 0.0

            discord_notifier.send_daily_summary(
                date=today,
                total_trades=self.daily_trades,
                winning_trades=self.winning_trades_today,
                total_pnl=total_pnl,
                win_rate=win_rate,
                balance=current_balance
            )

            log_info("SUMMARY", f"일일 요약 전송 완료: {self.daily_trades}거래, {self.winning_trades_today}승, {total_pnl:+.2f}USDT", "📊")

        except Exception as e:
            log_error(f"일일 요약 전송 실패: {e}")

    def check_daily_summary(self):
        """매일 자정에 일일 요약 전송"""
        today = datetime.now().date()
        if today != self.last_daily_summary:
            # 새로운 날이 시작됨
            if self.daily_trades > 0:  # 어제 거래가 있었다면 요약 전송
                self.send_daily_summary()

            # 일일 통계 초기화
            self.daily_trades = 0
            self.winning_trades_today = 0
            self.daily_start_balance = self.balance
            self.last_daily_summary = today

            log_info("RESET", "새로운 거래일 시작 - 일일 통계 초기화", "🌅")

    def stop(self):
        """봇 중지"""
        self.running = False

        # 봇 종료 시 일일 요약 전송
        if self.daily_trades > 0:
            self.send_daily_summary()

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
    log_info("CONFIG", f"레버리지: {settings.trading.leverage}배 | 자금: 총 시드 {settings.trading.position_size_pct:.0%}", "⚙️")
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
