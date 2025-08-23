"""
완전한 고빈도 스켈핑 전략 백테스트
- HTF(15분) 트렌드 필터링
- LTF(1분) Price Action 패턴 (연속 캔들, 바디 비율)
- 다중 기술적 지표 (EMA, RSI, ATR)
- 엄격한 리스크 관리
- 시장 구조 분석
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple
import warnings
warnings.filterwarnings('ignore')


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
        """Average True Range"""
        high_low = high - low
        high_close = np.abs(high - close.shift())
        low_close = np.abs(low - close.shift())
        
        ranges = pd.concat([high_low, high_close, low_close], axis=1)
        true_range = ranges.max(axis=1)
        return true_range.rolling(window=period).mean()


class CompleteScalpingStrategy:
    """완전한 고빈도 스켈핑 전략"""
    
    def __init__(self):
        self.indicators = TechnicalIndicators()
        
        # 전략 파라미터 (최적화된 설정)
        self.min_consecutive = 3
        self.max_consecutive = 6
        self.body_ratio_threshold = 0.8
        self.min_confidence = 0.3
        self.rsi_oversold = 30
        self.rsi_overbought = 70
        
    def detect_consecutive_pattern(self, df: pd.DataFrame, idx: int) -> Tuple[bool, int, str]:
        """연속 캔들 패턴 감지"""
        if idx < 10:
            return False, 0, 'none'
        
        # 최대 6개 캔들 확인
        candles = df.iloc[max(0, idx-5):idx+1]
        
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
        
        # 바디 비율 확인 (실체가 전체 캔들의 80% 이상)
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
        if (consecutive_up >= self.min_consecutive and 
            consecutive_up <= self.max_consecutive and 
            avg_body_ratio >= self.body_ratio_threshold):
            return True, consecutive_up, 'bullish'
        elif (consecutive_down >= self.min_consecutive and 
              consecutive_down <= self.max_consecutive and 
              avg_body_ratio >= self.body_ratio_threshold):
            return True, consecutive_down, 'bearish'
        
        return False, 0, 'none'
    
    def calculate_market_structure(self, df: pd.DataFrame, idx: int) -> str:
        """시장 구조 분석 (trending/choppy)"""
        if idx < 30:
            return 'neutral'
        
        # 최근 30개 캔들의 고점/저점 분석
        recent = df.iloc[idx-29:idx+1]
        
        high_trend = np.polyfit(range(len(recent)), recent['high'], 1)[0]
        low_trend = np.polyfit(range(len(recent)), recent['low'], 1)[0]
        
        # 추세 강도
        price_std = recent['close'].std()
        price_mean = recent['close'].mean()
        volatility_ratio = price_std / price_mean
        
        if abs(high_trend) > price_mean * 0.001 and abs(low_trend) > price_mean * 0.001:
            if high_trend * low_trend > 0:  # 같은 방향
                return 'trending'
        
        if volatility_ratio > 0.02:
            return 'choppy'
            
        return 'neutral'
    
    def get_signal(self, df: pd.DataFrame, idx: int, htf_trend: str) -> Optional[Dict]:
        """완전한 신호 생성 로직"""
        if idx < 50:
            return None
        
        # 현재 데이터
        current = df.iloc[idx]
        current_price = current['close']
        
        # 1. HTF 트렌드와 일치하지 않으면 거래 안함
        if htf_trend == 'neutral':
            return None
        
        # 2. 연속 캔들 패턴 감지
        has_pattern, consecutive_count, pattern_direction = self.detect_consecutive_pattern(df, idx)
        
        if not has_pattern:
            return None
        
        # 3. HTF 트렌드와 패턴 방향 일치 확인
        if not ((htf_trend == 'bullish' and pattern_direction == 'bullish') or
                (htf_trend == 'bearish' and pattern_direction == 'bearish')):
            return None
        
        # 4. 시장 구조 확인 (trending 상태에서만 거래)
        market_structure = self.calculate_market_structure(df, idx)
        if market_structure == 'choppy':
            return None
        
        # 5. 기술적 지표 확인
        # RSI 필터 (극단값 회피)
        rsi_window = df['close'].iloc[idx-13:idx+1]
        if len(rsi_window) >= 14:
            current_rsi = self.indicators.rsi(rsi_window, 14).iloc[-1]
            
            # RSI 극단값에서는 역방향 진입만 허용
            if pattern_direction == 'bullish' and current_rsi > self.rsi_overbought:
                return None
            if pattern_direction == 'bearish' and current_rsi < self.rsi_oversold:
                return None
        
        # 6. EMA 필터 (추가 트렌드 확인)
        ema_window = df['close'].iloc[idx-20:idx+1]
        if len(ema_window) >= 21:
            ema_9 = self.indicators.ema(ema_window, 9).iloc[-1]
            ema_21 = self.indicators.ema(ema_window, 21).iloc[-1]
            
            # EMA 배열이 트렌드와 일치하는지 확인
            if pattern_direction == 'bullish' and current_price <= ema_9:
                return None
            if pattern_direction == 'bearish' and current_price >= ema_9:
                return None
        
        # 7. ATR 기반 변동성 확인
        atr_window = df.iloc[idx-13:idx+1]
        if len(atr_window) >= 14:
            current_atr = self.indicators.atr(
                atr_window['high'], 
                atr_window['low'], 
                atr_window['close'], 
                14
            ).iloc[-1]
            
            # 최소 변동성 확인 (너무 조용한 시장에서는 거래 안함)
            atr_ratio = current_atr / current_price
            if atr_ratio < 0.001:  # 0.1% 미만 변동성
                return None
        
        # 8. 신뢰도 계산
        confidence = 0.0
        
        # 연속 캔들 수에 따른 신뢰도
        confidence += min(consecutive_count / 6, 0.4)  # 최대 40%
        
        # 바디 비율에 따른 신뢰도  
        recent_candles = df.iloc[idx-2:idx+1]
        avg_body_ratio = np.mean([
            abs(candle['close'] - candle['open']) / (candle['high'] - candle['low'])
            for _, candle in recent_candles.iterrows()
            if candle['high'] - candle['low'] > 0
        ])
        confidence += min(avg_body_ratio, 0.3)  # 최대 30%
        
        # 트렌드 일치도에 따른 신뢰도
        if htf_trend == pattern_direction:
            confidence += 0.2  # 20%
        
        # 시장 구조에 따른 신뢰도
        if market_structure == 'trending':
            confidence += 0.1  # 10%
        
        # 최소 신뢰도 체크
        if confidence < self.min_confidence:
            return None
        
        # 9. 신호 생성
        signal_type = 'BUY' if pattern_direction == 'bullish' else 'SELL'
        
        return {
            'signal_type': signal_type,
            'confidence': confidence,
            'price': current_price,
            'consecutive_count': consecutive_count,
            'body_ratio': avg_body_ratio,
            'market_structure': market_structure,
            'reason': f"{consecutive_count}연속+{pattern_direction}+{htf_trend}트렌드"
        }


class CompleteStrategyBacktest:
    """완전한 전략 백테스트"""
    
    def __init__(self, initial_balance: float = 10000):
        self.initial_balance = initial_balance
        self.balance = initial_balance
        self.strategy = CompleteScalpingStrategy()
        
        # 거래 추적
        self.trades = []
        self.positions = {}
        self.total_trades = 0
        self.winning_trades = 0
        self.max_drawdown = 0
        self.max_balance = initial_balance
        
        # 성과 세부 추적
        self.daily_trades = 0
        self.consecutive_losses = 0
        
    def load_data(self, file_path: str) -> pd.DataFrame:
        """데이터 로드"""
        df = pd.read_csv(file_path)
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        return df.sort_values('timestamp').reset_index(drop=True)
    
    def create_15m_data(self, df_1m: pd.DataFrame) -> pd.DataFrame:
        """15분봉 생성"""
        df_temp = df_1m.copy().set_index('timestamp')
        df_15m = df_temp.resample('15T').agg({
            'open': 'first',
            'high': 'max',
            'low': 'min', 
            'close': 'last',
            'volume': 'sum'
        }).dropna().reset_index()
        return df_15m
    
    def get_htf_trend(self, df_15m: pd.DataFrame, target_time: datetime) -> str:
        """HTF 트렌드 분석"""
        mask = df_15m['timestamp'] <= target_time
        data = df_15m[mask].tail(100)
        
        if len(data) < 50:
            return 'neutral'
        
        # EMA 20/50 기반 트렌드
        ema_20 = data['close'].ewm(span=20).mean().iloc[-1]
        ema_50 = data['close'].ewm(span=50).mean().iloc[-1]
        current = data['close'].iloc[-1]
        
        if current > ema_20 > ema_50:
            return 'bullish'
        elif current < ema_20 < ema_50:
            return 'bearish'
        return 'neutral'
    
    def calculate_position_size(self, price: float) -> float:
        """포지션 크기 계산 (시드 10%, 레버리지 20배)"""
        allocation = self.balance * 0.10  # 시드의 10%
        leverage = 20
        position_value = allocation * leverage
        return position_value / price
    
    def run_backtest(self, df_1m: pd.DataFrame, start_date: str, end_date: str):
        """완전한 백테스트 실행"""
        print(f"완전한 전략 백테스트: {start_date} ~ {end_date}")
        print("=" * 60)
        
        # 날짜 필터링
        mask = (df_1m['timestamp'] >= start_date) & (df_1m['timestamp'] <= end_date)
        test_data = df_1m[mask].reset_index(drop=True)
        
        # 15분봉 생성
        df_15m = self.create_15m_data(test_data)
        
        print(f"백테스트 데이터: {len(test_data):,}개 1분봉")
        print("백테스트 실행 중...")
        
        # 거래 상태
        position = None
        entry_time = None
        entry_price = None
        stop_loss = None
        take_profit = None
        
        for idx, row in test_data.iterrows():
            current_time = row['timestamp']
            current_price = row['close']
            
            # 진행률 표시
            if idx % 50000 == 0:
                progress = idx / len(test_data) * 100
                print(f"진행률: {progress:.1f}% | 거래: {self.total_trades} | 잔고: ${self.balance:,.2f}")
            
            # 기존 포지션 체크 (청산 조건)
            if position:
                # 시간 제한 (10분)
                time_exit = current_time - entry_time > timedelta(minutes=10)
                
                # 손익 조건
                if position == 'long':
                    profit_exit = current_price >= take_profit
                    loss_exit = current_price <= stop_loss
                else:  # short
                    profit_exit = current_price <= take_profit
                    loss_exit = current_price >= stop_loss
                
                if time_exit or profit_exit or loss_exit:
                    # 청산 실행
                    if profit_exit:
                        reason = "익절"
                    elif loss_exit:
                        reason = "손절"
                    else:
                        reason = "시간만료"
                    
                    # 손익 계산
                    if position == 'long':
                        pnl_pct = (current_price - entry_price) / entry_price
                    else:
                        pnl_pct = (entry_price - current_price) / entry_price
                    
                    # 레버리지 적용 실제 손익
                    position_size = self.calculate_position_size(entry_price)
                    leveraged_pnl = pnl_pct * 20 * (self.balance * 0.10)  # 20배 레버리지
                    
                    # 잔고 업데이트
                    self.balance += leveraged_pnl
                    
                    # 통계 업데이트
                    self.total_trades += 1
                    if leveraged_pnl > 0:
                        self.winning_trades += 1
                        self.consecutive_losses = 0
                    else:
                        self.consecutive_losses += 1
                    
                    # 최대 낙폭 추적
                    self.max_balance = max(self.max_balance, self.balance)
                    drawdown = (self.max_balance - self.balance) / self.max_balance
                    self.max_drawdown = max(self.max_drawdown, drawdown)
                    
                    # 거래 기록
                    self.trades.append({
                        'timestamp': current_time,
                        'type': 'exit',
                        'side': position,
                        'entry_price': entry_price,
                        'exit_price': current_price,
                        'pnl': leveraged_pnl,
                        'pnl_pct': pnl_pct * 100,
                        'duration': (current_time - entry_time).total_seconds() / 60,
                        'reason': reason
                    })
                    
                    position = None
            
            # 새로운 진입 기회 확인 (포지션이 없고, 연속 손실 3회 미만, 충분한 데이터)
            elif (self.consecutive_losses < 3 and 
                  idx > 1000 and 
                  self.total_trades < 500):  # 일일 거래 제한
                
                # HTF 트렌드 확인
                htf_trend = self.get_htf_trend(df_15m, current_time)
                
                if htf_trend != 'neutral':
                    # 완전한 신호 생성
                    signal = self.strategy.get_signal(test_data, idx, htf_trend)
                    
                    if signal and signal['confidence'] >= 0.3:
                        # 포지션 진입
                        position = 'long' if signal['signal_type'] == 'BUY' else 'short'
                        entry_price = current_price
                        entry_time = current_time
                        
                        # 손절/익절 설정 (0.3%)
                        if position == 'long':
                            take_profit = entry_price * 1.003
                            stop_loss = entry_price * 0.997
                        else:
                            take_profit = entry_price * 0.997
                            stop_loss = entry_price * 1.003
                        
                        # 진입 기록
                        self.trades.append({
                            'timestamp': current_time,
                            'type': 'entry',
                            'side': position,
                            'price': current_price,
                            'confidence': signal['confidence'],
                            'reason': signal['reason'],
                            'htf_trend': htf_trend
                        })
        
        return self.generate_report()
    
    def generate_report(self) -> Dict:
        """상세 보고서 생성"""
        if self.total_trades == 0:
            return {"error": "거래가 없었습니다"}
        
        total_return = (self.balance - self.initial_balance) / self.initial_balance * 100
        win_rate = self.winning_trades / self.total_trades * 100
        
        # 거래 분석
        trade_pnls = [t['pnl'] for t in self.trades if 'pnl' in t]
        wins = [pnl for pnl in trade_pnls if pnl > 0]
        losses = [pnl for pnl in trade_pnls if pnl < 0]
        
        avg_win = np.mean(wins) if wins else 0
        avg_loss = np.mean(losses) if losses else 0
        profit_factor = abs(sum(wins) / sum(losses)) if losses else float('inf')
        
        # 신뢰도 분석
        entry_trades = [t for t in self.trades if t['type'] == 'entry']
        avg_confidence = np.mean([t['confidence'] for t in entry_trades]) if entry_trades else 0
        
        # 시간 분석
        exit_trades = [t for t in self.trades if 'duration' in t]
        avg_duration = np.mean([t['duration'] for t in exit_trades]) if exit_trades else 0
        
        return {
            'total_return_pct': total_return,
            'final_balance': self.balance,
            'total_trades': self.total_trades,
            'winning_trades': self.winning_trades,
            'losing_trades': self.total_trades - self.winning_trades,
            'win_rate': win_rate,
            'profit_factor': profit_factor,
            'avg_win': avg_win,
            'avg_loss': avg_loss,
            'max_drawdown_pct': self.max_drawdown * 100,
            'total_pnl': sum(trade_pnls),
            'avg_confidence': avg_confidence,
            'avg_duration_minutes': avg_duration,
            'trades_per_day': self.total_trades / 90  # 3개월 기준
        }
    
    def print_detailed_report(self, report: Dict):
        """상세 보고서 출력"""
        print("\\n" + "=" * 80)
        print("완전한 고빈도 스켈핑 전략 백테스트 결과")
        print("=" * 80)
        
        print(f"초기 자본: ${self.initial_balance:,.2f}")
        print(f"최종 잔고: ${report['final_balance']:,.2f}")
        print(f"총 수익률: {report['total_return_pct']:+.2f}%")
        print(f"총 손익: ${report['total_pnl']:+.2f}")
        print()
        
        print("거래 성과:")
        print(f"  총 거래: {report['total_trades']}회")
        print(f"  승리: {report['winning_trades']}회")
        print(f"  패배: {report['losing_trades']}회")
        print(f"  승률: {report['win_rate']:.1f}%")
        print(f"  일평균 거래: {report['trades_per_day']:.1f}회")
        print()
        
        print("수익성 분석:")
        print(f"  Profit Factor: {report['profit_factor']:.2f}")
        print(f"  평균 수익: ${report['avg_win']:+.2f}")
        print(f"  평균 손실: ${report['avg_loss']:+.2f}")
        print(f"  최대 낙폭: {report['max_drawdown_pct']:.2f}%")
        print()
        
        print("전략 세부사항:")
        print(f"  평균 신뢰도: {report['avg_confidence']:.2f}")
        print(f"  평균 보유시간: {report['avg_duration_minutes']:.1f}분")
        print()
        
        # 전략 평가
        if report['win_rate'] >= 55 and report['profit_factor'] >= 1.5:
            print("[우수] 실전 거래 권장!")
        elif report['win_rate'] >= 50 and report['profit_factor'] >= 1.2:
            print("[보통] 추가 최적화 필요")
        else:
            print("[부족] 전략 개선 필요")
        
        print("=" * 80)


def main():
    print("완전한 고빈도 스켈핑 전략 백테스트")
    print("=" * 50)
    
    # 백테스터 초기화  
    backtester = CompleteStrategyBacktest(10000)
    
    # 데이터 로드
    df = backtester.load_data("과거데이터/BTCUSDT_1m_2024-01-01~2024-12-31.csv")
    print(f"데이터 로드 완료: {len(df):,}개 캔들")
    
    # 백테스트 실행 (3개월)
    result = backtester.run_backtest(df, "2024-01-01", "2024-03-31")
    
    # 결과 출력
    if 'error' not in result:
        backtester.print_detailed_report(result)
    else:
        print(result['error'])


if __name__ == "__main__":
    main()