# final_high_frequency_strategy.py

import os
import sys
import pandas as pd
import numpy as np
from typing import Dict, List, Optional
from dataclasses import dataclass
from datetime import datetime, timedelta
import warnings
warnings.filterwarnings('ignore')

# 현재 디렉토리를 Python path에 추가
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# 필요한 클래스들을 직접 정의
from settings import settings
from discord_notifier import discord_notifier


@dataclass
class Signal:
    """거래 신호"""
    signal_type: str  # 'BUY' 또는 'SELL'
    timestamp: datetime
    price: float
    confidence: float
    reason: str = ""


@dataclass 
class Position:
    """포지션 정보"""
    symbol: str
    side: str  # 'long' 또는 'short'
    size: float
    entry_price: float
    entry_time: datetime
    stop_loss: float = None
    take_profit: float = None
    status: str = 'open'  # 'open', 'closed'
    
    # 트레일링 익절용 새 필드들
    original_size: float = None      # 원래 포지션 크기
    partial_closed: bool = False     # 반익절 완료 여부
    partial_pnl: float = 0.0        # 반익절 수익 (추가!)
    trailing_price: float = None     # 트레일링 기준가 (최고점/최저점)
    trailing_stop: float = None      # 트레일링 스톱 가격
    breakeven_set: bool = False      # 본전 손절 설정 여부
    original_stop_loss: float = None # 원래 ATR 손절가 저장
    _atr_stop_switched: bool = False # ATR 손절 전환 여부 (추가!)


class TechnicalIndicators:
    """기술적 지표 계산"""
    
    @staticmethod
    def ema(data: pd.Series, period: int) -> pd.Series:
        """지수이동평균"""
        return data.ewm(span=period, adjust=False).mean()
    
    @staticmethod 
    def rsi(data: pd.Series, period: int = 14) -> pd.Series:
        """RSI 계산"""
        delta = data.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        rs = gain / loss
        return 100 - (100 / (1 + rs))
    
    @staticmethod
    def atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
        """Average True Range 계산"""
        high_low = high - low
        high_close = np.abs(high - close.shift())
        low_close = np.abs(low - close.shift())
        
        ranges = pd.concat([high_low, high_close, low_close], axis=1)
        true_range = ranges.max(axis=1)
        return true_range.rolling(window=period).mean()


class MarketDataCollector:
    """시장 데이터 수집기"""
    
    def __init__(self, connector):
        self.connector = connector
        self.data_queue = []
    
    def get_latest_data(self, symbol: str, limit: int = 100) -> pd.DataFrame:
        """최신 시장 데이터 조회"""
        return self.connector.get_futures_klines(symbol, '1m', limit)


class OptimizedPriceActionStrategy:
    """최적화된 Price Action 전략"""
    
    def __init__(self, config: Dict):
        self.config = config
        
    def detect_consecutive_pattern(self, df: pd.DataFrame, idx: int) -> tuple:
        """연속 캔들 패턴 감지"""
        if idx < 10:
            return False, 0, 'none'
        
        current = df.iloc[idx]
        candles = df.iloc[max(0, idx-6):idx+1]  # 최대 6개 캔들 확인
        
        # 연속 상승/하락 확인
        consecutive_up = 0
        consecutive_down = 0
        
        for i in range(len(candles)-1):
            if candles.iloc[i+1]['close'] > candles.iloc[i]['close']:
                consecutive_up += 1
                consecutive_down = 0
            elif candles.iloc[i+1]['close'] < candles.iloc[i]['close']:
                consecutive_down += 1
                consecutive_up = 0
            else:
                break
        
        # 바디 비율 확인
        body_ratios = []
        for i in range(len(candles)):
            candle = candles.iloc[i]
            body = abs(candle['close'] - candle['open'])
            total_range = candle['high'] - candle['low']
            if total_range > 0:
                body_ratios.append(body / total_range)
            else:
                body_ratios.append(0)
        
        avg_body_ratio = np.mean(body_ratios[-3:]) if len(body_ratios) >= 3 else 0
        
        # 패턴 조건 확인
        min_consecutive = self.config.get('min_consecutive', 3)
        max_consecutive = self.config.get('max_consecutive', 6)
        body_threshold = self.config.get('body_ratio_threshold', 0.8)
        
        if (consecutive_up >= min_consecutive and consecutive_up <= max_consecutive and 
            avg_body_ratio >= body_threshold):
            return True, consecutive_up, 'bullish'
        elif (consecutive_down >= min_consecutive and consecutive_down <= max_consecutive and 
              avg_body_ratio >= body_threshold):
            return True, consecutive_down, 'bearish'
        
        return False, 0, 'none'
    
    def enhanced_price_action_signal(self, df: pd.DataFrame, idx: int) -> Signal:
        """향상된 Price Action 신호 생성"""
        current = df.iloc[idx]
        current_time = current['timestamp'] if 'timestamp' in df.columns else datetime.now()
        
        # 연속 패턴 감지
        has_pattern, count, direction = self.detect_consecutive_pattern(df, idx)
        
        if not has_pattern:
            return Signal('HOLD', current_time, current['close'], 0.0, "패턴 없음")
        
        # 신뢰도 계산
        confidence = min(0.9, 0.3 + (count - 3) * 0.1)  # 3개부터 시작해서 개수에 따라 증가
        
        # 신호 결정
        if direction == 'bullish':
            action = 'BUY'
            reason = f"{count}연속 상승 패턴"
        elif direction == 'bearish':
            action = 'SELL' 
            reason = f"{count}연속 하락 패턴"
        else:
            action = 'HOLD'
            reason = "패턴 불명확"
            confidence = 0.0
        
        # Signal 객체 반환 (dataclass 정의에 맞게 사용)
        return Signal(action, current_time, current['close'], confidence, reason)


class SidewaysDetector:
    """횡보 전략 진입 감지"""

    def __init__(self):
        pass
    
    def detect_sideways_entry_opportunity(self, df: pd.DataFrame, idx: int) -> bool:
        """횡보 전략 진입 기회 감지 - 횡보 전략 전용"""
        lookback = settings.trading.sideways_entry_lookback
        
        if idx < max(lookback, settings.trading.atr_period):
            return False
        
        recent_data = df.iloc[idx-lookback+1:idx+1]
        
        # ATR 계산
        atr = TechnicalIndicators.atr(
            df['high'].iloc[idx-settings.trading.atr_period:idx+1],
            df['low'].iloc[idx-settings.trading.atr_period:idx+1],
            df['close'].iloc[idx-settings.trading.atr_period:idx+1],
            settings.trading.atr_period
        ).iloc[-1]
        
        current_price = df['close'].iloc[idx]
        
        # 횡보 전략용 범위 (더 타이트)
        max_range = atr * settings.trading.sideways_entry_atr_multiplier
        actual_range = recent_data['high'].max() - recent_data['low'].min()
        
        # 진동 패턴 확인
        high_peaks = 0
        low_valleys = 0
        highs = recent_data['high'].values
        lows = recent_data['low'].values
        
        for i in range(1, len(highs)-1):
            if highs[i] > highs[i-1] and highs[i] > highs[i+1]:
                high_peaks += 1
            if lows[i] < lows[i-1] and lows[i] < lows[i+1]:
                low_valleys += 1
        
        # 횡보 전략 진입 조건
        is_sideways_pattern = (
            actual_range <= max_range and  # 범위가 ATR * 1.5 이내
            high_peaks >= settings.trading.sideways_entry_min_oscillations and
            low_valleys >= settings.trading.sideways_entry_min_oscillations and
            high_peaks <= settings.trading.sideways_entry_max_oscillations and
            low_valleys <= settings.trading.sideways_entry_max_oscillations
        )
        
        return is_sideways_pattern


class BollingerBandStrategy:
    """볼린저 밴드 횡보 전략"""
    
    def __init__(self):
        self.period = settings.trading.bollinger_period
        self.std_dev = settings.trading.bollinger_std_dev
    
    def calculate_bands(self, df: pd.DataFrame, idx: int) -> tuple:
        """볼린저 밴드 계산"""
        if idx < self.period:
            current_close = df.iloc[idx]['close']
            return current_close, current_close, current_close
            
        recent_closes = df.iloc[max(0, idx-self.period+1):idx+1]['close']
        middle = recent_closes.mean()
        std = recent_closes.std()
        
        upper = middle + (self.std_dev * std)
        lower = middle - (self.std_dev * std)
        
        return upper, middle, lower
    
    def get_sideways_signal(self, df: pd.DataFrame, idx: int) -> Signal:
        """볼린저 밴드 횡보 신호 생성"""
        current = df.iloc[idx]
        current_price = current['close']
        current_time = current['timestamp'] if 'timestamp' in df.columns else datetime.now()
        
        upper, middle, lower = self.calculate_bands(df, idx)
        
        # 밴드 폭 확인
        band_width = (upper - lower) / middle
        if band_width < 0.01:  # 1% 미만
            return Signal('HOLD', current_time, current_price, 0.0, "밴드폭 부족")
        
        # 횡보 신호 생성
        if current_price >= upper * 0.995:  # 상단 밴드 근처
            confidence = min(0.8, (current_price - upper) / (upper - middle) + 0.5)
            return Signal('SELL', current_time, current_price, confidence, f"횡보-BB상단터치")
        elif current_price <= lower * 1.005:  # 하단 밴드 근처  
            confidence = min(0.8, (lower - current_price) / (middle - lower) + 0.5)
            return Signal('BUY', current_time, current_price, confidence, f"횡보-BB하단터치")
        else:
            return Signal('HOLD', current_time, current_price, 0.0, "횡보-BB중간영역")


class FinalHighFrequencyStrategy:
    """최종 고빈도 스켈핑 전략 - 검증된 최적 설정"""
    
    def __init__(self, config: Dict = None):
        # 검증된 최적 파라미터
        self.config = config or {
            'min_consecutive': 3,
            'max_consecutive': 6, 
            'body_ratio_threshold': 0.8,
            'volatility_threshold': 1.2,
            'min_confidence': 0.3,
            'use_volume_filter': True,
            'use_volatility_filter': True,
            
            # 리스크 관리
            'profit_target': 0.003,  # 0.3% 익절
            'stop_loss': 0.003,      # 0.3% 손절
            'max_hold_time': 600,    # 10분 최대 보유
            'position_size_pct': 0.01, # 1% 포지션 크기
            
            # 시장 필터
            'min_volatility': 0.001,  # 최소 변동성
            'max_volatility': 0.05,   # 최대 변동성
            'trading_hours': (9, 23), # 거래 시간 (한국시간)
        }
        
        self.price_action = OptimizedPriceActionStrategy(self.config)
        self.indicators = TechnicalIndicators()
        
        # 횡보 전략 추가
        self.sideways_detector = SidewaysDetector()
        self.sideways_strategy = BollingerBandStrategy()
        
        # 성과 추적
        self.signals_generated = 0
        self.trades_executed = 0
        self.last_signal_time = None
        
    def get_signal(self, df: pd.DataFrame, idx: int) -> Signal:
        """신호 생성 - 용도별 분리된 로직 사용"""

        # 기본 데이터 검증
        if idx < 20 or len(df) < 20:
            timestamp = df.iloc[idx]['timestamp'] if 'timestamp' in df.columns else datetime.now()
            return Signal('HOLD', timestamp, df.iloc[idx]['close'], 0.0, "데이터 부족")

        current = df.iloc[idx]
        current_time = current['timestamp'] if 'timestamp' in df.columns else datetime.now()

        # 변동성 필터
        volatility = self._calculate_current_volatility(df, idx)
        if volatility < self.config['min_volatility'] or volatility > self.config['max_volatility']:
            return Signal('HOLD', current_time, current['close'], 0.0, f"변동성 부적합({volatility:.3f})")

        # 신호 빈도 제한
        if self.last_signal_time and (current_time - self.last_signal_time).total_seconds() < 60:
            return Signal('HOLD', current_time, current['close'], 0.0, "신호 간격 부족")

        # 1. 시장 구조 분석 (한 번만!)
        market_structure = self._analyze_market_structure(df, idx)

        # 2. 횡보 전략 진입 기회 확인
        sideways_entry = False
        if settings.trading.enable_sideways_strategy:
            sideways_entry = self.sideways_detector.detect_sideways_entry_opportunity(df, idx)

        # 3. 전략 선택
        if sideways_entry:
            # 횡보 전략 사용
            signal = self.sideways_strategy.get_sideways_signal(df, idx)
            signal.reason = f"[횡보전략] " + signal.reason
        else:
            # 추세 전략 사용 (시장 구조에 따라 신뢰도 조정)
            signal = self.price_action.enhanced_price_action_signal(df, idx)

            if market_structure == 'choppy':
                signal.confidence *= 0.7
                signal.reason = f"[추세전략-불안정] " + signal.reason
            elif market_structure == 'tight_sideways':
                signal.confidence *= 0.8
                signal.reason = f"[추세전략-횡보중] " + signal.reason
            elif market_structure == 'trending':
                signal.confidence *= 1.1
                signal.reason = f"[추세전략-추세중] " + signal.reason
            else:
                signal.reason = f"[추세전략] " + signal.reason

        # 4. 추가 필터링
        if signal.signal_type in ['BUY', 'SELL']:
            if not sideways_entry:
                # 추세 전략에서만 볼륨 필터 적용
                if self.config['use_volume_filter']:
                    volume_ok = self._check_volume_confirmation(df, idx)
                    if not volume_ok:
                        signal.confidence *= 0.7
                        signal.reason += " (거래량부족)"

            # 최종 신뢰도 확인
            if signal.confidence >= self.config['min_confidence']:
                self.signals_generated += 1
                self.last_signal_time = current_time

                return Signal(
                    signal.signal_type,
                    current_time,
                    signal.price,
                    min(0.95, signal.confidence),
                    f"[HF{self.signals_generated}] {signal.reason}"
                )

        return Signal('HOLD', current_time, current['close'], 0.0, "조건 미달")
    
    def _is_trading_hours(self, timestamp: datetime) -> bool:
        """거래 시간 확인"""
        hour = timestamp.hour
        start_hour, end_hour = self.config['trading_hours']
        return start_hour <= hour <= end_hour
    
    def _calculate_current_volatility(self, df: pd.DataFrame, idx: int) -> float:
        """현재 변동성 계산"""
        lookback = min(20, idx)
        if lookback < 5:
            return 0.01
        
        recent_returns = df['close'].iloc[idx-lookback+1:idx+1].pct_change().dropna()
        return recent_returns.std()
    
    def _check_volume_confirmation(self, df: pd.DataFrame, idx: int) -> bool:
        """거래량 확인"""
        if idx < 10:
            return True
        
        current_volume = df['volume'].iloc[idx]
        avg_volume = df['volume'].iloc[idx-9:idx+1].mean()
        
        return current_volume > avg_volume * 0.8  # 평균의 80% 이상
    
    def _analyze_market_structure(self, df: pd.DataFrame, idx: int) -> str:  # ← self 포함, 들여쓰기 수정
        
        """시장 구조 분석 - 추세 전략에서 사용"""
        if idx < settings.trading.market_structure_lookback:
            return 'neutral'
        
        lookback = settings.trading.market_structure_lookback
        recent_data = df.iloc[idx-lookback+1:idx+1]
        
        # ATR 계산
        if idx >= settings.trading.atr_period:
            atr = TechnicalIndicators.atr(
                df['high'].iloc[idx-settings.trading.atr_period:idx+1],
                df['low'].iloc[idx-settings.trading.atr_period:idx+1],
                df['close'].iloc[idx-settings.trading.atr_period:idx+1],
                settings.trading.atr_period
            ).iloc[-1]
        else:
            atr = df['close'].iloc[idx] * 0.01
        
        current_price = df['close'].iloc[idx]
        price_range = recent_data['high'].max() - recent_data['low'].min()
        
        # 추세선 분석
        high_trend = np.polyfit(range(len(recent_data)), recent_data['high'].values, 1)[0]
        low_trend = np.polyfit(range(len(recent_data)), recent_data['low'].values, 1)[0]
        
        # 시장 상태 판단
        range_in_atr = price_range / atr
        
        if range_in_atr > settings.trading.market_structure_atr_multiplier:
            # 큰 변동성 = choppy (불안정)
            return 'choppy'
        elif range_in_atr < settings.trading.market_sideways_atr_threshold:
            # 작은 변동성 = 타이트한 횡보
            return 'tight_sideways'
        elif abs(high_trend / atr) > 0.5:
            # 명확한 추세
            return 'trending'
        else:
            return 'neutral'


class FinalStrategyBacktester:
    """최종 전략 백테스터"""
    
    def __init__(self, initial_balance: float = 10000):
        self.initial_balance = initial_balance
        
    def create_realistic_test_data(self, days: int = 10) -> pd.DataFrame:
        """현실적인 테스트 데이터 생성"""
        print(f"{days}일간의 현실적인 고빈도 거래용 데이터 생성...")
        
        end_time = datetime.now()
        start_time = end_time - timedelta(days=days)
        time_range = pd.date_range(start_time, end_time, freq='1T')
        
        np.random.seed(456)  # 새로운 패턴
        base_price = 52000
        
        prices = [base_price]
        market_regime = 'normal'  # normal, volatile, trending
        regime_change_time = 0
        
        for i in range(1, len(time_range)):
            # 마켓 체제 변화
            if i - regime_change_time > 300:  # 5시간마다 체제 변화 가능
                if np.random.random() < 0.3:
                    market_regime = np.random.choice(['normal', 'volatile', 'trending'])
                    regime_change_time = i
            
            # 체제별 가격 변동
            if market_regime == 'normal':
                base_change = np.random.normal(0, 40)
                trend = np.sin(i * 0.01) * 10
            elif market_regime == 'volatile':
                base_change = np.random.normal(0, 120)
                trend = np.random.normal(0, 50)
            else:  # trending
                base_change = np.random.normal(0, 60)
                trend = (i - regime_change_time) * 0.5 if np.random.random() > 0.5 else -(i - regime_change_time) * 0.5
            
            # 미세 패턴 (연속성 생성)
            if i % 3 == 0:
                micro_trend = np.random.choice([-1, -0.5, 0, 0.5, 1])
            else:
                micro_trend = getattr(self, 'last_micro_trend', 0) * 0.7
            
            self.last_micro_trend = micro_trend
            
            # 일중 패턴
            hour = time_range[i].hour
            if 14 <= hour <= 22:  # 활발한 시간
                activity = 1.3
            elif 2 <= hour <= 8:   # 조용한 시간
                activity = 0.6
            else:
                activity = 1.0
            
            total_change = (base_change + trend + micro_trend * 20) * activity
            new_price = max(prices[-1] + total_change, 30000)
            prices.append(new_price)
        
        # OHLCV 생성 (더 정교하게)
        data = []
        for i in range(len(time_range)):
            base = prices[i]
            
            # 현실적인 스프레드와 슬리피지
            spread = base * 0.0001  # 0.01% 스프레드
            
            if i == 0:
                open_price = base
            else:
                # 갭 고려
                gap = np.random.normal(0, base * 0.0005)
                open_price = data[-1]['close'] + gap
            
            # 캔들 내부 움직임 (체계적)
            volatility = abs(np.random.normal(base * 0.008, base * 0.002))
            
            # 실제 거래처럼 고가/저가 생성
            high_move = np.random.uniform(0.2, 1.0) * volatility
            low_move = np.random.uniform(0.2, 1.0) * volatility
            
            high = base + high_move + spread/2
            low = base - low_move - spread/2
            close = base + np.random.normal(0, base * 0.003)
            
            # 논리적 제약
            high = max(high, open_price, close)
            low = min(low, open_price, close)
            
            # 거래량 (가격 움직임과 연관)
            price_movement = abs(close - open_price) / open_price
            base_volume = 500000 + price_movement * 5000000
            volume = max(base_volume * np.random.lognormal(0, 0.8), 10000)
            
            data.append({
                'timestamp': time_range[i],
                'open': round(open_price, 2),
                'high': round(high, 2),
                'low': round(low, 2),
                'close': round(close, 2),
                'volume': round(volume, 2),
                'volume_usdt': round(volume * close, 2)
            })
        
        df = pd.DataFrame(data)
        
        # 통계
        returns = df['close'].pct_change().dropna()
        print(f"데이터 완성: {len(df)}개 캔들 ({df['timestamp'].min()} ~ {df['timestamp'].max()})")
        print(f"일평균 변동성: {returns.std() * np.sqrt(1440) * 100:.2f}%")
        print(f"최대 일중 변동폭: {((df['high'] - df['low']) / df['close']).max() * 100:.2f}%")
        
        return df
    
    def comprehensive_backtest(self, days: int = 10) -> Dict:
        """종합 백테스트"""
        print("=" * 70)
        print("최종 고빈도 스켈핑 전략 종합 검증")
        print("=" * 70)
        
        # 데이터 생성
        df = self.create_realistic_test_data(days)
        
        # 전략 초기화
        strategy = FinalHighFrequencyStrategy()
        
        # 백테스트 실행
        trades = []
        balance = self.initial_balance
        equity_curve = []
        current_position = None
        
        signals_count = {'BUY': 0, 'SELL': 0, 'HOLD': 0}
        
        print(f"\n백테스트 실행 중... (총 {len(df)}개 데이터포인트)")
        
        for idx in range(len(df)):
            if idx % 1000 == 0:
                print(f"  진행률: {idx/len(df)*100:.1f}%")
            
            current_row = df.iloc[idx]
            current_price = current_row['close']
            timestamp = current_row['timestamp']
            
            # 신호 생성
            signal = strategy.get_signal(df, idx)
            signals_count[signal.action] += 1
            
            # 포지션 관리
            if current_position is None and signal.action in ['BUY', 'SELL']:
                # 진입
                position_value = balance * strategy.config['position_size_pct']
                size = position_value / current_price
                
                if size > 0:
                    current_position = {
                        'entry_time': timestamp,
                        'entry_price': current_price,
                        'size': size,
                        'side': signal.action,
                        'signal_confidence': signal.confidence,
                        'signal_reason': signal.reason
                    }
                    strategy.trades_executed += 1
            
            elif current_position is not None:
                # 청산 조건 확인
                if current_position['side'] == 'BUY':
                    pnl_pct = (current_price - current_position['entry_price']) / current_position['entry_price']
                else:
                    pnl_pct = (current_position['entry_price'] - current_price) / current_position['entry_price']
                
                should_exit = False
                exit_reason = ""
                
                # 익절/손절
                if pnl_pct >= strategy.config['profit_target']:
                    should_exit = True
                    exit_reason = "익절"
                elif pnl_pct <= -strategy.config['stop_loss']:
                    should_exit = True
                    exit_reason = "손절"
                elif (timestamp - current_position['entry_time']).total_seconds() > strategy.config['max_hold_time']:
                    should_exit = True
                    exit_reason = "시간만료"
                
                if should_exit:
                    # 거래 기록
                    pnl = pnl_pct * current_position['entry_price'] * current_position['size']
                    
                    # 수수료 (진입 + 청산)
                    entry_fee = current_position['entry_price'] * current_position['size'] * 0.0004
                    exit_fee = current_price * current_position['size'] * 0.0004
                    total_fees = entry_fee + exit_fee
                    
                    net_pnl = pnl - total_fees
                    balance += net_pnl
                    
                    trade_record = {
                        'entry_time': current_position['entry_time'],
                        'exit_time': timestamp,
                        'entry_price': current_position['entry_price'],
                        'exit_price': current_price,
                        'side': current_position['side'],
                        'size': current_position['size'],
                        'pnl': net_pnl,
                        'pnl_pct': pnl_pct * 100,
                        'fees': total_fees,
                        'duration_minutes': (timestamp - current_position['entry_time']).total_seconds() / 60,
                        'exit_reason': exit_reason,
                        'signal_confidence': current_position['signal_confidence'],
                        'signal_reason': current_position['signal_reason']
                    }
                    trades.append(trade_record)
                    current_position = None
            
            # 자기자본 곡선
            unrealized_pnl = 0
            if current_position:
                if current_position['side'] == 'BUY':
                    unrealized_pnl = (current_price - current_position['entry_price']) * current_position['size']
                else:
                    unrealized_pnl = (current_position['entry_price'] - current_price) * current_position['size']
                # 수수료 차감
                unrealized_pnl -= current_price * current_position['size'] * 0.0008
            
            equity_curve.append({
                'timestamp': timestamp,
                'balance': balance,
                'equity': balance + unrealized_pnl,
                'unrealized_pnl': unrealized_pnl
            })
        
        # 결과 분석
        result = self._analyze_results(trades, equity_curve, signals_count, strategy)
        
        return result
    
    def _analyze_results(self, trades: List, equity_curve: List, signals_count: Dict, strategy) -> Dict:
        """결과 분석"""
        if not trades:
            return {
                'status': 'NO_TRADES',
                'total_trades': 0,
                'message': '거래가 발생하지 않았습니다. 전략 파라미터를 조정하세요.'
            }
        
        trades_df = pd.DataFrame(trades)
        equity_df = pd.DataFrame(equity_curve)
        
        # 기본 통계
        total_trades = len(trades)
        winning_trades = len(trades_df[trades_df['pnl'] > 0])
        losing_trades = len(trades_df[trades_df['pnl'] < 0])
        win_rate = winning_trades / total_trades
        
        total_pnl = trades_df['pnl'].sum()
        total_pnl_pct = (total_pnl / self.initial_balance) * 100
        total_fees = trades_df['fees'].sum()
        
        # 최대 낙폭
        equity_series = equity_df['equity']
        rolling_max = equity_series.expanding().max()
        drawdowns = (rolling_max - equity_series) / rolling_max
        max_drawdown_pct = drawdowns.max() * 100
        
        # 추가 통계
        avg_win = trades_df[trades_df['pnl'] > 0]['pnl'].mean() if winning_trades > 0 else 0
        avg_loss = trades_df[trades_df['pnl'] < 0]['pnl'].mean() if losing_trades > 0 else 0
        profit_factor = abs(trades_df[trades_df['pnl'] > 0]['pnl'].sum() / trades_df[trades_df['pnl'] < 0]['pnl'].sum()) if losing_trades > 0 else float('inf')
        
        avg_duration = trades_df['duration_minutes'].mean()
        avg_confidence = trades_df['signal_confidence'].mean()
        
        # 일별 분석
        trades_df['date'] = pd.to_datetime(trades_df['entry_time']).dt.date
        daily_trades = trades_df.groupby('date').size()
        daily_pnl = trades_df.groupby('date')['pnl'].sum()
        
        return {
            'status': 'SUCCESS',
            'total_trades': total_trades,
            'winning_trades': winning_trades,
            'losing_trades': losing_trades,
            'win_rate': win_rate,
            'total_pnl': total_pnl,
            'total_pnl_pct': total_pnl_pct,
            'total_fees': total_fees,
            'max_drawdown_pct': max_drawdown_pct,
            'profit_factor': profit_factor,
            'avg_win': avg_win,
            'avg_loss': avg_loss,
            'avg_duration': avg_duration,
            'avg_confidence': avg_confidence,
            'signals_generated': strategy.signals_generated,
            'signals_count': signals_count,
            'daily_avg_trades': daily_trades.mean(),
            'best_day_pnl': daily_pnl.max(),
            'worst_day_pnl': daily_pnl.min(),
            'trades_detail': trades,
            'equity_curve': equity_curve
        }
    
    def print_comprehensive_results(self, result: Dict):
        """종합 결과 출력"""
        print("\n" + "=" * 70)
        print("최종 고빈도 스켈핑 전략 검증 결과")
        print("=" * 70)
        
        if result['status'] == 'NO_TRADES':
            print(result['message'])
            return
        
        print(f"거래 성과:")
        print(f"  총 거래수: {result['total_trades']:,}회")
        print(f"  승리 거래: {result['winning_trades']}회")
        print(f"  패배 거래: {result['losing_trades']}회")  
        print(f"  승률: {result['win_rate']:.1%}")
        print(f"  일평균 거래: {result['daily_avg_trades']:.1f}회")
        
        print(f"\n수익성:")
        print(f"  총 손익: {result['total_pnl']:+,.2f} USDT")
        print(f"  총 수익률: {result['total_pnl_pct']:+.2f}%")
        print(f"  총 수수료: {result['total_fees']:.2f} USDT")
        print(f"  Profit Factor: {result['profit_factor']:.2f}")
        print(f"  평균 수익: {result['avg_win']:+.2f} USDT")
        print(f"  평균 손실: {result['avg_loss']:+.2f} USDT")
        
        print(f"\n리스크 지표:")
        print(f"  최대 낙폭: {result['max_drawdown_pct']:.2f}%")
        print(f"  최고 일일 수익: {result['best_day_pnl']:+.2f} USDT")
        print(f"  최악 일일 손실: {result['worst_day_pnl']:+.2f} USDT")
        
        print(f"\n전략 효율:")
        print(f"  평균 보유시간: {result['avg_duration']:.1f}분")
        print(f"  평균 신호 신뢰도: {result['avg_confidence']:.2f}")
        print(f"  생성된 신호수: {result['signals_generated']:,}개")
        print(f"  매수신호: {result['signals_count']['BUY']:,}개")
        print(f"  매도신호: {result['signals_count']['SELL']:,}개")
        
        # 종합 평가
        print(f"\n" + "=" * 70)
        
        score = 0
        evaluation = []
        
        # 거래 빈도 평가
        if result['total_trades'] > 500:
            score += 2
            evaluation.append("[V] 고빈도 거래 달성")
        elif result['total_trades'] > 200:
            score += 1
            evaluation.append("[△] 중빈도 거래")
        else:
            evaluation.append("[X] 거래 빈도 부족")
        
        # 승률 평가
        if result['win_rate'] > 0.55:
            score += 2
            evaluation.append("[V] 우수한 승률")
        elif result['win_rate'] > 0.45:
            score += 1
            evaluation.append("[△] 평균적 승률")
        else:
            evaluation.append("[X] 낮은 승률")
        
        # 수익성 평가
        if result['total_pnl_pct'] > 1:
            score += 2
            evaluation.append("[V] 높은 수익률")
        elif result['total_pnl_pct'] > 0:
            score += 1
            evaluation.append("[△] 소폭 수익")
        else:
            evaluation.append("[X] 손실 발생")
        
        # 리스크 평가
        if result['max_drawdown_pct'] < 5:
            score += 1
            evaluation.append("[V] 낮은 리스크")
        elif result['max_drawdown_pct'] < 10:
            evaluation.append("[△] 보통 리스크")
        else:
            evaluation.append("[X] 높은 리스크")
        
        for eval_item in evaluation:
            try:
                print(eval_item)
            except UnicodeEncodeError:
                print(eval_item.encode('utf-8', errors='ignore').decode('utf-8'))
        
        # 최종 평가
        if score >= 6:
            print(f"\n[우수] 실전 거래 권장! (점수: {score}/7)")
        elif score >= 4:
            print(f"\n[보통] 추가 최적화 필요 (점수: {score}/7)")
        else:
            print(f"\n[부족] 전략 개선 필요 (점수: {score}/7)")


def main():
    """메인 실행"""
    backtester = FinalStrategyBacktester()
    
    # 종합 백테스트 실행
    result = backtester.comprehensive_backtest(days=7)
    
    # 결과 출력
    backtester.print_comprehensive_results(result)
    
    # 결과 저장
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    os.makedirs("final_results", exist_ok=True)
    
    # 상세 결과 저장
    import json
    save_result = result.copy()
    save_result.pop('trades_detail', None)  # 너무 큰 데이터 제거
    save_result.pop('equity_curve', None)
    
    with open(f"final_results/final_strategy_{timestamp}.json", 'w', encoding='utf-8') as f:
        json.dump(save_result, f, ensure_ascii=False, indent=2, default=str)
    
    print(f"\n결과가 final_results/final_strategy_{timestamp}.json에 저장되었습니다.")


if __name__ == "__main__":
    main()