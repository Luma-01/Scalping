"""
향상된 다중 타임프레임 스켈핑 백테스트 엔진
HTF(15분) 트렌드 확인 + LTF(1분) 진입/청산
"""

import os
import sys
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import warnings
warnings.filterwarnings('ignore')

# 현재 디렉토리를 Python path에 추가
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from final_high_frequency_strategy import FinalHighFrequencyStrategy, Signal, Position, TechnicalIndicators
from settings import settings
from discord_notifier import discord_notifier


class EnhancedScalpingBacktest:
    """향상된 스켈핑 백테스트 엔진"""
    
    def __init__(self, initial_balance: float = 10000):
        self.initial_balance = initial_balance
        self.balance = initial_balance
        self.strategy = FinalHighFrequencyStrategy()
        self.indicators = TechnicalIndicators()
        
        # 거래 추적
        self.trades = []
        self.positions = {}
        self.equity_curve = []
        
        # 성과 지표
        self.total_trades = 0
        self.winning_trades = 0
        self.losing_trades = 0
        self.max_drawdown = 0
        self.max_balance = initial_balance
        
    def load_historical_data(self, file_path: str) -> pd.DataFrame:
        """과거 데이터 로드 및 전처리"""
        try:
            print(f"과거 데이터 로딩: {file_path}")
            
            # CSV 파일 읽기
            df = pd.read_csv(file_path)
            
            # 타임스탬프 변환
            df['timestamp'] = pd.to_datetime(df['timestamp'])
            df = df.sort_values('timestamp').reset_index(drop=True)
            
            print(f"데이터 로드 완료: {len(df):,}개 캔들 ({df['timestamp'].iloc[0]} ~ {df['timestamp'].iloc[-1]})")
            
            return df
            
        except Exception as e:
            print(f"데이터 로드 실패: {e}")
            return pd.DataFrame()
    
    def resample_to_15m(self, df_1m: pd.DataFrame) -> pd.DataFrame:
        """1분봉을 15분봉으로 리샘플링"""
        try:
            df_1m_copy = df_1m.copy()
            df_1m_copy.set_index('timestamp', inplace=True)
            
            # 15분봉으로 리샘플링
            df_15m = df_1m_copy.resample('15T').agg({
                'open': 'first',
                'high': 'max', 
                'low': 'min',
                'close': 'last',
                'volume': 'sum'
            }).dropna()
            
            df_15m.reset_index(inplace=True)
            print(f"15분봉 생성 완료: {len(df_15m)}개 캔들")
            
            return df_15m
            
        except Exception as e:
            print(f"15분봉 생성 실패: {e}")
            return pd.DataFrame()
    
    def get_htf_trend_at_time(self, df_15m: pd.DataFrame, target_time: datetime) -> str:
        """특정 시점의 HTF 트렌드 분석"""
        try:
            # 해당 시점까지의 15분봉 데이터 추출
            mask = df_15m['timestamp'] <= target_time
            htf_data = df_15m[mask].tail(100)  # 최근 100개 캔들
            
            if len(htf_data) < 50:
                return 'neutral'
            
            # EMA 기반 트렌드 분석
            closes = htf_data['close']
            ema_20 = closes.ewm(span=20).mean().iloc[-1]
            ema_50 = closes.ewm(span=50).mean().iloc[-1]
            current_price = closes.iloc[-1]
            
            if current_price > ema_20 > ema_50:
                return 'bullish'
            elif current_price < ema_20 < ema_50:
                return 'bearish'
            else:
                return 'neutral'
                
        except Exception as e:
            return 'neutral'
    
    def is_signal_aligned_with_trend(self, signal_type: str, htf_trend: str) -> bool:
        """신호가 HTF 트렌드와 일치하는지 확인"""
        if htf_trend == 'bullish' and signal_type == 'BUY':
            return True
        elif htf_trend == 'bearish' and signal_type == 'SELL':
            return True
        return False
    
    def calculate_position_size(self, price: float) -> float:
        """포지션 크기 계산 (시드의 10% 사용)"""
        allocation = self.balance * 0.10
        leverage = settings.trading.leverage
        size = (allocation * leverage) / price
        return round(size, 6)
    
    def execute_trade(self, signal: Signal, price: float, timestamp: datetime, 
                     symbol: str = 'BTCUSDT') -> bool:
        """거래 실행"""
        try:
            if symbol in self.positions:
                return False  # 이미 포지션이 있음
            
            # 포지션 크기 계산
            size = self.calculate_position_size(price)
            if size <= 0:
                return False
            
            # 포지션 생성
            side = 'long' if signal.signal_type == 'BUY' else 'short'
            position = Position(
                symbol=symbol,
                side=side,
                size=size,
                entry_price=price,
                entry_time=timestamp,
                stop_loss=price * (0.997 if side == 'long' else 1.003),  # 0.3% 손절
                take_profit=price * (1.003 if side == 'long' else 0.997)  # 0.3% 익절
            )
            
            self.positions[symbol] = position
            
            print(f"포지션 진입: {timestamp} | {side.upper()} {size} @ ${price:,.2f} (신뢰도: {signal.confidence:.2f})")
            return True
            
        except Exception as e:
            print(f"거래 실행 실패: {e}")
            return False
    
    def check_exit_conditions(self, position: Position, current_price: float, 
                            current_time: datetime) -> Optional[str]:
        """청산 조건 확인"""
        # 시간 기반 청산 (10분 최대 보유)
        if current_time - position.entry_time > timedelta(minutes=10):
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
    
    def close_position(self, symbol: str, price: float, timestamp: datetime, 
                      reason: str) -> Dict:
        """포지션 청산"""
        try:
            if symbol not in self.positions:
                return {}
            
            position = self.positions[symbol]
            
            # 손익 계산
            if position.side == 'long':
                pnl = (price - position.entry_price) * position.size
            else:
                pnl = (position.entry_price - price) * position.size
            
            # 레버리지 적용 손익
            leveraged_pnl = pnl * settings.trading.leverage
            pnl_pct = (leveraged_pnl / (position.entry_price * position.size * settings.trading.leverage)) * 100
            
            # 잔고 업데이트
            self.balance += leveraged_pnl
            
            # 거래 기록
            trade = {
                'timestamp': timestamp,
                'symbol': symbol,
                'side': position.side,
                'entry_price': position.entry_price,
                'exit_price': price,
                'size': position.size,
                'pnl': leveraged_pnl,
                'pnl_pct': pnl_pct,
                'duration': (timestamp - position.entry_time).total_seconds() / 60,
                'reason': reason
            }
            
            self.trades.append(trade)
            self.total_trades += 1
            
            if leveraged_pnl > 0:
                self.winning_trades += 1
            else:
                self.losing_trades += 1
            
            # 최대 낙폭 추적
            self.max_balance = max(self.max_balance, self.balance)
            current_drawdown = (self.max_balance - self.balance) / self.max_balance
            self.max_drawdown = max(self.max_drawdown, current_drawdown)
            
            # 자본 곡선 추가
            self.equity_curve.append({
                'timestamp': timestamp,
                'balance': self.balance,
                'drawdown': current_drawdown
            })
            
            print(f"포지션 청산: {timestamp} | {reason} | P&L: ${leveraged_pnl:+.2f} ({pnl_pct:+.2f}%) | 잔고: ${self.balance:,.2f}")
            
            # 포지션 제거
            del self.positions[symbol]
            
            return trade
            
        except Exception as e:
            print(f"포지션 청산 실패: {e}")
            return {}
    
    def run_backtest(self, df_1m: pd.DataFrame, df_15m: pd.DataFrame, 
                    start_date: str = "2024-01-01", end_date: str = "2024-12-31") -> Dict:
        """백테스트 실행"""
        try:
            print(f"\\n백테스트 시작: {start_date} ~ {end_date}")
            print("=" * 60)
            
            # 날짜 필터링
            start_time = pd.to_datetime(start_date)
            end_time = pd.to_datetime(end_date)
            
            mask = (df_1m['timestamp'] >= start_time) & (df_1m['timestamp'] <= end_time)
            test_data = df_1m[mask].reset_index(drop=True)
            
            print(f"백테스트 데이터: {len(test_data):,}개 1분봉")
            
            # 진행 상황 추적
            total_candles = len(test_data)
            progress_interval = max(1, total_candles // 20)  # 5% 간격
            
            for idx, row in test_data.iterrows():
                current_time = row['timestamp']
                current_price = row['close']
                
                # 진행 상황 출력
                if idx % progress_interval == 0:
                    progress = (idx / total_candles) * 100
                    print(f"진행률: {progress:.1f}% | {current_time} | 잔고: ${self.balance:,.2f}")
                
                # 기존 포지션 체크 (청산 조건)
                for symbol in list(self.positions.keys()):
                    position = self.positions[symbol]
                    exit_reason = self.check_exit_conditions(position, current_price, current_time)
                    if exit_reason:
                        self.close_position(symbol, current_price, current_time, exit_reason)
                
                # 새로운 진입 신호 체크 (포지션이 없을 때만)
                if len(self.positions) == 0 and idx >= 1000:  # 충분한 과거 데이터가 있을 때
                    
                    # HTF 트렌드 확인
                    htf_trend = self.get_htf_trend_at_time(df_15m, current_time)
                    
                    if htf_trend != 'neutral':
                        # LTF 신호 생성 (최근 1000개 캔들 사용)
                        ltf_window = test_data.iloc[max(0, idx-999):idx+1].copy()
                        
                        if len(ltf_window) >= 100:
                            signal = self.strategy.get_signal(ltf_window, len(ltf_window)-1)
                            
                            # 신호 조건 체크
                            if (signal.signal_type in ['BUY', 'SELL'] and 
                                signal.confidence >= 0.3 and
                                self.is_signal_aligned_with_trend(signal.signal_type, htf_trend)):
                                
                                self.execute_trade(signal, current_price, current_time)
            
            # 마지막 포지션 정리
            for symbol in list(self.positions.keys()):
                final_price = test_data['close'].iloc[-1]
                final_time = test_data['timestamp'].iloc[-1]
                self.close_position(symbol, final_price, final_time, "백테스트종료")
            
            return self.generate_report()
            
        except Exception as e:
            print(f"백테스트 실행 실패: {e}")
            return {}
    
    def generate_report(self) -> Dict:
        """백테스트 결과 보고서 생성"""
        if not self.trades:
            return {"error": "거래 기록이 없습니다"}
        
        # 기본 통계
        total_return = (self.balance - self.initial_balance) / self.initial_balance * 100
        win_rate = (self.winning_trades / self.total_trades * 100) if self.total_trades > 0 else 0
        
        # 거래 분석
        trade_pnls = [trade['pnl'] for trade in self.trades]
        avg_win = np.mean([pnl for pnl in trade_pnls if pnl > 0]) if self.winning_trades > 0 else 0
        avg_loss = np.mean([pnl for pnl in trade_pnls if pnl < 0]) if self.losing_trades > 0 else 0
        profit_factor = abs(avg_win * self.winning_trades / (avg_loss * self.losing_trades)) if avg_loss != 0 else float('inf')
        
        # 시간 분석
        durations = [trade['duration'] for trade in self.trades]
        avg_duration = np.mean(durations)
        
        report = {
            'period': f"{self.trades[0]['timestamp'].date()} ~ {self.trades[-1]['timestamp'].date()}",
            'initial_balance': self.initial_balance,
            'final_balance': self.balance,
            'total_return_pct': total_return,
            'total_trades': self.total_trades,
            'winning_trades': self.winning_trades,
            'losing_trades': self.losing_trades,
            'win_rate': win_rate,
            'profit_factor': profit_factor,
            'avg_win': avg_win,
            'avg_loss': avg_loss,
            'max_drawdown_pct': self.max_drawdown * 100,
            'avg_duration_minutes': avg_duration,
            'trades_per_day': self.total_trades / 365,  # 1년 기준
            'total_pnl': sum(trade_pnls)
        }
        
        return report
    
    def print_detailed_report(self, report: Dict):
        """상세 보고서 출력"""
        print("\\n" + "=" * 80)
        print("향상된 스켈핑 전략 백테스트 결과")
        print("=" * 80)
        
        print(f"기간: {report['period']}")
        print(f"초기 자본: ${report['initial_balance']:,.2f}")
        print(f"최종 잔고: ${report['final_balance']:,.2f}")
        print(f"총 수익률: {report['total_return_pct']:+.2f}%")
        print(f"총 손익: ${report['total_pnl']:+.2f}")
        print()
        
        print("거래 통계:")
        print(f"  총 거래수: {report['total_trades']}회")
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
        print(f"  평균 보유시간: {report['avg_duration_minutes']:.1f}분")
        print()
        
        # 성과 평가
        if report['win_rate'] >= 60 and report['profit_factor'] >= 1.5:
            print("[우수] 실전 거래 권장!")
        elif report['win_rate'] >= 50 and report['profit_factor'] >= 1.2:
            print("[보통] 추가 최적화 필요")
        else:
            print("[부족] 전략 개선 필요")
        
        print("=" * 80)


def main():
    """메인 실행"""
    print("향상된 다중 타임프레임 스켈핑 백테스트")
    print("=" * 60)
    
    # 백테스터 초기화
    backtester = EnhancedScalpingBacktest(initial_balance=10000)
    
    # 과거 데이터 로드
    data_path = "과거데이터/BTCUSDT_1m_2024-01-01~2024-12-31.csv"
    df_1m = backtester.load_historical_data(data_path)
    
    if df_1m.empty:
        print("❌ 데이터 로드 실패")
        return
    
    # 15분봉 생성
    df_15m = backtester.resample_to_15m(df_1m)
    
    if df_15m.empty:
        print("❌ 15분봉 생성 실패")
        return
    
    # 백테스트 실행
    result = backtester.run_backtest(df_1m, df_15m, "2024-01-01", "2024-12-31")
    
    if result:
        # 결과 출력
        backtester.print_detailed_report(result)
        
        # Discord 알림 (선택사항)
        try:
            pass  # Discord 알림은 일단 비활성화
        except:
            pass


if __name__ == "__main__":
    main()