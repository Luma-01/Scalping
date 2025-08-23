"""
간단한 다중 타임프레임 스켈핑 백테스트
HTF 트렌드 + LTF Price Action
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, Optional
import warnings
warnings.filterwarnings('ignore')


class SimpleScalpingBacktest:
    """간단한 스켈핑 백테스트"""
    
    def __init__(self, initial_balance: float = 10000):
        self.initial_balance = initial_balance
        self.balance = initial_balance
        
        # 거래 추적
        self.trades = []
        self.positions = {}
        self.total_trades = 0
        self.winning_trades = 0
        self.max_drawdown = 0
        self.max_balance = initial_balance
        
    def load_data(self, file_path: str) -> pd.DataFrame:
        """데이터 로드"""
        df = pd.read_csv(file_path)
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        return df.sort_values('timestamp').reset_index(drop=True)
    
    def create_15m_data(self, df_1m: pd.DataFrame) -> pd.DataFrame:
        """1분봉을 15분봉으로 변환"""
        df_temp = df_1m.copy().set_index('timestamp')
        df_15m = df_temp.resample('15T').agg({
            'open': 'first',
            'high': 'max', 
            'low': 'min',
            'close': 'last',
            'volume': 'sum'
        }).dropna().reset_index()
        return df_15m
    
    def get_trend(self, df_15m: pd.DataFrame, target_time: datetime) -> str:
        """HTF 트렌드 확인 (EMA 20/50)"""
        # 해당 시점까지의 데이터
        mask = df_15m['timestamp'] <= target_time
        data = df_15m[mask].tail(100)
        
        if len(data) < 50:
            return 'neutral'
            
        # EMA 계산
        ema_20 = data['close'].ewm(span=20).mean().iloc[-1]
        ema_50 = data['close'].ewm(span=50).mean().iloc[-1] 
        current = data['close'].iloc[-1]
        
        if current > ema_20 > ema_50:
            return 'bullish'
        elif current < ema_20 < ema_50:
            return 'bearish'
        return 'neutral'
    
    def get_price_action_signal(self, df: pd.DataFrame, idx: int) -> Optional[str]:
        """간단한 Price Action 신호"""
        if idx < 10:
            return None
            
        # 최근 3개 캔들의 연속성 확인
        recent = df.iloc[idx-2:idx+1]
        
        # 연속 상승
        if all(recent['close'].iloc[i] > recent['close'].iloc[i-1] for i in range(1, len(recent))):
            if all(recent['close'].iloc[i] > recent['open'].iloc[i] for i in range(len(recent))):
                return 'BUY'
        
        # 연속 하락        
        if all(recent['close'].iloc[i] < recent['close'].iloc[i-1] for i in range(1, len(recent))):
            if all(recent['close'].iloc[i] < recent['open'].iloc[i] for i in range(len(recent))):
                return 'SELL'
                
        return None
    
    def run_backtest(self, df_1m: pd.DataFrame, start_date: str, end_date: str):
        """백테스트 실행"""
        print(f"백테스트 기간: {start_date} ~ {end_date}")
        
        # 날짜 필터링
        mask = (df_1m['timestamp'] >= start_date) & (df_1m['timestamp'] <= end_date)
        test_data = df_1m[mask].reset_index(drop=True)
        
        # 15분봉 생성
        df_15m = self.create_15m_data(test_data)
        
        print(f"백테스트 데이터: {len(test_data):,}개 1분봉")
        print("백테스트 진행 중...")
        
        # 거래 로직
        position = None
        entry_time = None
        
        for idx, row in test_data.iterrows():
            current_time = row['timestamp']
            current_price = row['close']
            
            # 진행률 표시
            if idx % 50000 == 0:
                progress = idx / len(test_data) * 100
                print(f"진행률: {progress:.1f}% | 잔고: ${self.balance:,.2f}")
            
            # 포지션이 있으면 청산 조건 확인
            if position:
                # 10분 경과 또는 손익 0.3% 도달시 청산
                time_limit = current_time - entry_time > timedelta(minutes=10)
                
                if position == 'long':
                    profit_target = entry_price * 1.003
                    stop_loss = entry_price * 0.997
                    exit_condition = current_price >= profit_target or current_price <= stop_loss or time_limit
                else:  # short
                    profit_target = entry_price * 0.997  
                    stop_loss = entry_price * 1.003
                    exit_condition = current_price <= profit_target or current_price >= stop_loss or time_limit
                
                if exit_condition:
                    # 청산 실행
                    reason = "익절" if (position == 'long' and current_price >= entry_price * 1.003) or (position == 'short' and current_price <= entry_price * 0.997) else "손절" if not time_limit else "시간만료"
                    
                    # 손익 계산 (레버리지 20배)
                    if position == 'long':
                        pnl_pct = (current_price - entry_price) / entry_price
                    else:
                        pnl_pct = (entry_price - current_price) / entry_price
                    
                    leveraged_pnl = pnl_pct * 20 * 1000  # 20배 레버리지, $1000 포지션
                    self.balance += leveraged_pnl
                    
                    # 통계 업데이트
                    self.total_trades += 1
                    if leveraged_pnl > 0:
                        self.winning_trades += 1
                    
                    # 최대 낙폭 추적
                    self.max_balance = max(self.max_balance, self.balance)
                    drawdown = (self.max_balance - self.balance) / self.max_balance
                    self.max_drawdown = max(self.max_drawdown, drawdown)
                    
                    # 거래 기록
                    self.trades.append({
                        'timestamp': current_time,
                        'type': 'exit',
                        'side': position,
                        'price': current_price,
                        'pnl': leveraged_pnl,
                        'pnl_pct': pnl_pct * 100,
                        'reason': reason
                    })
                    
                    position = None
                    
            # 포지션이 없으면 진입 신호 확인
            elif idx > 1000:  # 충분한 과거 데이터가 있을 때만
                # HTF 트렌드 확인
                trend = self.get_trend(df_15m, current_time)
                
                if trend != 'neutral':
                    # LTF 신호 확인
                    signal = self.get_price_action_signal(test_data, idx)
                    
                    # 트렌드와 신호 일치 확인
                    valid_signal = (trend == 'bullish' and signal == 'BUY') or (trend == 'bearish' and signal == 'SELL')
                    
                    if valid_signal:
                        position = 'long' if signal == 'BUY' else 'short'
                        entry_price = current_price
                        entry_time = current_time
                        
                        self.trades.append({
                            'timestamp': current_time,
                            'type': 'entry', 
                            'side': position,
                            'price': current_price,
                            'trend': trend
                        })
        
        return self.generate_report()
    
    def generate_report(self) -> Dict:
        """결과 보고서 생성"""
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
            'total_pnl': sum(trade_pnls)
        }
    
    def print_report(self, report: Dict):
        """결과 출력"""
        print("\\n" + "=" * 60)
        print("스켈핑 백테스트 결과")  
        print("=" * 60)
        print(f"초기 자본: ${self.initial_balance:,.2f}")
        print(f"최종 잔고: ${report['final_balance']:,.2f}")
        print(f"총 수익률: {report['total_return_pct']:+.2f}%")
        print(f"총 손익: ${report['total_pnl']:+.2f}")
        print()
        print(f"총 거래: {report['total_trades']}회")
        print(f"승리: {report['winning_trades']}회")
        print(f"패배: {report['losing_trades']}회")
        print(f"승률: {report['win_rate']:.1f}%")
        print(f"Profit Factor: {report['profit_factor']:.2f}")
        print(f"최대 낙폭: {report['max_drawdown_pct']:.2f}%")
        print("=" * 60)


def main():
    print("간단한 스켈핑 백테스트")
    print("=" * 40)
    
    # 백테스터 초기화
    backtester = SimpleScalpingBacktest(10000)
    
    # 데이터 로드
    df = backtester.load_data("과거데이터/BTCUSDT_1m_2024-01-01~2024-12-31.csv")
    print(f"데이터 로드 완료: {len(df):,}개 캔들")
    
    # 백테스트 실행 (3개월 샘플)
    result = backtester.run_backtest(df, "2024-01-01", "2024-03-31")
    
    # 결과 출력
    backtester.print_report(result)


if __name__ == "__main__":
    main()