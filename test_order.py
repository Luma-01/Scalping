import os
import sys
import time
import pandas as pd
from datetime import datetime, timedelta

# 현재 디렉토리를 Python path에 추가
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from settings import settings
from gateio_connector import GateIOConnector, get_kst_time
from final_high_frequency_strategy import FinalHighFrequencyStrategy, Signal, Position
from discord_notifier import discord_notifier

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

class OrderTester:
    def __init__(self, symbol='XRP_USDT'):
        self.connector = None
        self.test_symbol = symbol
        self.position = None
        self.balance = 10000.0  # 테스트 시드
        
    def initialize(self):
        """초기화"""
        try:
            log_info("INIT", "주문 테스터 초기화 중", "🚀")
            
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
                
            log_success("Gate.io 연결 성공")
            return True
            
        except Exception as e:
            log_error(f"초기화 실패: {e}")
            return False
    
    def get_current_price(self) -> float:
        """현재 가격 조회"""
        try:
            ticker = self.connector.get_futures_ticker(self.test_symbol)
            if ticker and 'last_price' in ticker:
                return float(ticker['last_price'])
            return 0.0
        except Exception as e:
            log_error(f"가격 조회 실패: {e}")
            return 0.0
    
    def test_order(self, side='long'):
        """강제 주문 테스트 (매수/매도)"""
        try:
            current_price = self.get_current_price()
            if current_price <= 0:
                log_error("가격 조회 실패")
                return False
            
            log_info("PRICE", f"{self.test_symbol} 현재 가격: {current_price}", "💰")
            
            # 레버리지 강제 설정 (20배)
            leverage_result = self.connector.set_leverage(self.test_symbol, 20)
            if leverage_result:
                log_info("LEVERAGE", f"{self.test_symbol} 레버리지 20배로 설정", "⚙️")
            else:
                log_info("LEVERAGE", f"{self.test_symbol} 레버리지 설정 실패 (기존값 유지)", "⚠️")
            
            # 포지션 크기 계산 - 잔고를 고려한 안전한 크기
            try:
                balance_info = self.connector.get_futures_balance()
                available_balance = float(balance_info.get('available_balance', 0))
                log_info("BALANCE", f"사용 가능한 마진: {available_balance:.3f} USDT", "💰")
            except:
                available_balance = 1.0  # 안전한 기본값
                log_info("BALANCE", "잔고 조회 실패 - 최소 크기로 테스트", "⚠️")
            
            # Contract Size를 API에서 동적으로 조회
            contract_info = self.connector.get_contract_info(self.test_symbol)
            contract_size = contract_info.get('contract_size', 1)
            
            # 원하는 암호화폐 수량 (테스트용)
            desired_crypto_amount = contract_size  # Contract Size와 동일하게 설정 (SDK에서 1계약)
            size = desired_crypto_amount  # 이제 create_futures_order에서 자동 변환됨
            
            log_info("CONTRACT", f"동적 조회: {self.test_symbol.split('_')[0]} 1 계약 = {contract_size} {self.test_symbol.split('_')[0]}", "📋")
            required_margin = (desired_crypto_amount * current_price) / 20
            log_info("MARGIN", f"실제 필요 마진: {required_margin:.3f} USDT (사용가능: {available_balance:.3f})", "📊")
            log_info("SIZE", f"원하는 암호화폐 수량: {desired_crypto_amount} {self.test_symbol.split('_')[0]}", "📏")
            
            
            side_text = "매수" if side == 'long' else "매도"
            log_info("TEST", f"강제 {side_text} 주문 실행 - 크기: {size}", "🔥")
            
            # 주문 생성
            order = self.connector.create_futures_order(
                symbol=self.test_symbol,
                side=side,
                size=size,
                order_type='market'
            )
            
            if order and order.get('order_id'):
                log_success(f"{side_text} 주문 성공 - ID: {order['order_id']}")
                
                # 실제 거래된 정보 확인
                actual_crypto_size = order.get('size', size)  # 실제 암호화폐 수량
                actual_contracts = order.get('contracts', 1)  # 실제 계약 수
                order_contract_size = order.get('contract_size', contract_size)  # 주문에 사용된 Contract Size
                
                log_info("RESULT", f"실제 거래: {actual_contracts}계약 = {actual_crypto_size} {self.test_symbol.split('_')[0]}", "🎯")
                log_info("VERIFY", f"Contract Size 검증: {order_contract_size} (API: {contract_size})", "✅")
                
                # 포지션 기록
                if side == 'long':
                    stop_loss = current_price * 0.997   # 0.3% 손절
                    take_profit = current_price * 1.003  # 0.3% 익절
                else:
                    stop_loss = current_price * 1.003   # 0.3% 손절 (숏은 반대)
                    take_profit = current_price * 0.997  # 0.3% 익절 (숏은 반대)
                
                self.position = Position(
                    symbol=self.test_symbol,
                    side=side,
                    size=actual_crypto_size,  # 실제 암호화폐 수량 사용
                    entry_price=current_price,
                    entry_time=datetime.now(),
                    stop_loss=stop_loss,
                    take_profit=take_profit
                )
                
                trade_text = "BUY" if side == 'long' else "SELL"
                log_trade(trade_text, self.test_symbol, current_price, actual_crypto_size)
                
                # Discord 알림
                discord_notifier.send_position_opened(
                    side, self.test_symbol, current_price, actual_crypto_size,
                    self.position.stop_loss, self.position.take_profit
                )
                
                return True
            else:
                log_error(f"{side_text} 주문 실패")
                return False
                
        except Exception as e:
            log_error(f"{side_text} 주문 테스트 실패: {e}")
            return False
    
    def wait_and_close_position(self, wait_seconds: int = 30):
        """지정된 시간 대기 후 포지션 청산"""
        if not self.position:
            log_error("청산할 포지션 없음")
            return
        
        log_info("WAIT", f"{wait_seconds}초 대기 후 포지션 청산", "⏰")
        time.sleep(wait_seconds)
        
        try:
            current_price = self.get_current_price()
            if current_price <= 0:
                log_error("청산용 가격 조회 실패")
                return
            
            log_info("CLOSE", f"포지션 청산 실행 - 현재가: {current_price}", "📤")
            
            # 청산 주문 (포지션과 반대 방향)
            close_side = 'short' if self.position.side == 'long' else 'long'
            order = self.connector.create_futures_order(
                symbol=self.test_symbol,
                side=close_side,
                size=self.position.size,
                order_type='market'
            )
            
            if order and order.get('order_id'):
                # 손익 계산 (롱/숏 구분)
                if self.position.side == 'long':
                    pnl = (current_price - self.position.entry_price) * self.position.size
                else:
                    pnl = (self.position.entry_price - current_price) * self.position.size
                
                pnl_pct = (pnl / (self.position.entry_price * self.position.size)) * 100 * settings.trading.leverage
                
                log_success(f"청산 주문 성공 - ID: {order['order_id']}")
                log_position("CLOSE", self.test_symbol, pnl)
                
                # Discord 알림
                discord_notifier.send_position_closed(
                    self.position.side, self.test_symbol, self.position.entry_price,
                    current_price, self.position.size, pnl, pnl_pct, "테스트완료"
                )
                
                self.position = None
                
            else:
                log_error("청산 주문 실패")
                
        except Exception as e:
            log_error(f"포지션 청산 실패: {e}")

def main():
    """메인 테스트 함수"""
    print("=" * 60)
    print("Gate.io Contract Size 테스터")
    print("=" * 60)
    
    # 테스트할 코인 선택
    symbols = {
        '1': 'XRP_USDT',
        '2': 'BTC_USDT', 
        '3': 'ETH_USDT',
        '4': 'DOGE_USDT',
        '5': 'SOL_USDT'
    }
    
    print("테스트할 코인을 선택하세요:")
    for key, symbol in symbols.items():
        print(f"{key}. {symbol}")
    print("=" * 60)
    
    choice = input("선택 (1-5): ")
    if choice not in symbols:
        print("잘못된 선택입니다.")
        return
    
    selected_symbol = symbols[choice]
    print(f"\n{selected_symbol} Contract Size 테스트를 시작합니다.")
    print("=" * 60)
    
    tester = OrderTester(selected_symbol)
    
    if not tester.initialize():
        print("초기화 실패 - 테스트 중단")
        return
    
    print("테스트 옵션:")
    print("1. 롱 포지션 테스트 (매수)")
    print("2. 숏 포지션 테스트 (매도)")
    print("=" * 60)
    
    # 테스트 타입 선택
    test_type = input("테스트 타입을 선택하세요 (1: 롱, 2: 숏, q: 취소): ")
    if test_type == 'q':
        print("테스트 취소")
        return
    elif test_type == '2':
        side = 'short'
        side_text = "숏(매도)"
    else:
        side = 'long'
        side_text = "롱(매수)"
    
    print(f"\n{side_text} 테스트 시퀀스:")
    print(f"1. 강제 {side_text} 주문 실행")
    print("2. 30초 대기")
    print("3. 포지션 청산")
    print("=" * 60)
    
    # 최종 확인
    confirm = input(f"{side_text} 테스트를 실행하시겠습니까? (y/N): ")
    if confirm.lower() != 'y':
        print("테스트 취소")
        return
    
    try:
        # 1단계: 주문 실행
        if tester.test_order(side):
            # 2단계: 대기 및 청산
            tester.wait_and_close_position(30)
            log_success("테스트 완료 - 모든 과정 성공")
        else:
            log_error(f"테스트 실패 - {side_text} 주문 실패")
            
    except KeyboardInterrupt:
        log_info("STOP", "사용자 중단 요청", "⚠️")
        if tester.position:
            log_info("EMERGENCY", "긴급 청산 실행", "🚨")
            tester.wait_and_close_position(0)
    
    except Exception as e:
        log_error(f"테스트 중 예외 발생: {e}")
        if tester.position:
            log_info("EMERGENCY", "긴급 청산 실행", "🚨")
            tester.wait_and_close_position(0)

if __name__ == "__main__":
    main()