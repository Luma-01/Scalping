import gate_api
from gate_api.exceptions import ApiException, GateApiException
import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import time
import pytz

# 한국시간 설정
KST = pytz.timezone('Asia/Seoul')

def get_kst_time() -> str:
    """한국시간 HH:MM:SS 형태로 반환"""
    return datetime.now(KST).strftime('%H:%M:%S')


class GateIOConnector:
    """Gate.io 공식 SDK 기반 커넥터"""
    
    def __init__(self, api_key: str = "", secret_key: str = "", testnet: bool = True):
        self.api_key = api_key
        self.secret_key = secret_key
        self.testnet = testnet
        
        # SDK 설정
        configuration = gate_api.Configuration(
            host = "https://fx-api-testnet.gateio.ws/api/v4" if testnet else "https://api.gateio.ws/api/v4",
            key = api_key,
            secret = secret_key
        )
        
        # API 클라이언트 초기화
        self.spot_api = gate_api.SpotApi(gate_api.ApiClient(configuration))
        self.futures_api = gate_api.FuturesApi(gate_api.ApiClient(configuration))
        
        if testnet:
            print(f"{get_kst_time()} 🎮 [GATEIO] SDK 초기화 완료 (테스트넷)")
        else:
            print(f"{get_kst_time()} 🚀 [GATEIO] SDK 초기화 완료 (라이브)")
    
    def get_futures_klines(self, symbol: str, interval: str = "1m", limit: int = 200) -> pd.DataFrame:
        """선물 K라인 데이터 조회"""
        try:
            # Gate.io SDK를 사용한 K라인 조회
            result = self.futures_api.list_futures_candlesticks(
                settle='usdt',
                contract=symbol,
                interval=interval,
                limit=limit
            )
            
            # 데이터프레임으로 변환
            data = []
            for candle in result:
                timestamp = pd.to_datetime(int(candle.t), unit='s')
                data.append({
                    'timestamp': timestamp,
                    'open': float(candle.o),
                    'high': float(candle.h),
                    'low': float(candle.l),
                    'close': float(candle.c),
                    'volume': float(candle.v)
                })
            
            df = pd.DataFrame(data)
            if not df.empty:
                df = df.reset_index(drop=True)  # 인덱스 리셋
                df.sort_values('timestamp', inplace=True)
            
            # K라인 개별 로그 제거 (스팸방지)
            return df
            
        except (ApiException, GateApiException) as e:
            print(f"K라인 조회 실패: {e}")
            return pd.DataFrame()
    
    def get_futures_ticker(self, symbol: str) -> Dict:
        """선물 티커 정보 조회"""
        try:
            result = self.futures_api.list_futures_tickers(settle='usdt', contract=symbol)
            if result:
                ticker = result[0]
                return {
                    'symbol': symbol,
                    'last_price': float(ticker.last),
                    'bid_price': float(ticker.highest_bid) if ticker.highest_bid else 0,
                    'ask_price': float(ticker.lowest_ask) if ticker.lowest_ask else 0,
                    'volume': float(ticker.base_volume),
                    'change_percentage': float(ticker.change_percentage)
                }
        except (ApiException, GateApiException) as e:
            print(f"티커 조회 실패: {e}")
        
        return {}
    
    def get_futures_balance(self) -> Dict:
        """선물 잔고 조회"""
        try:
            result = self.futures_api.list_futures_accounts(settle='usdt')
            if result:
                return {
                    'total_balance': float(result.total),
                    'available_balance': float(result.available),
                    'position_margin': float(result.position_margin),
                    'unrealized_pnl': float(result.unrealised_pnl)
                }
        except (ApiException, GateApiException) as e:
            print(f"잔고 조회 실패: {e}")
        
        return {}
    
    def set_leverage(self, symbol: str, leverage: int) -> bool:
        """레버리지 설정 (심볼별 최대 레버리지 고려)"""
        try:
            # Gate.io SDK를 사용한 레버리지 설정
            result = self.futures_api.update_position_leverage(
                settle='usdt',
                contract=symbol,
                leverage=str(leverage)
            )
            print(f"{get_kst_time()} ✅ [LEVERAGE] {symbol} = {leverage}x")
            return True
        except (ApiException, GateApiException) as e:
            # 레버리지 제한 오류 시 범위를 줍여보고 재시도
            if "LEVERAGE_EXCEEDED" in str(e) or "limit" in str(e).lower():
                # 에러 메시지에서 최대값 추출 시도
                error_str = str(e)
                if "limit [" in error_str:
                    try:
                        # "limit [1, 10]" 형태에서 최대값 추출
                        start = error_str.find("limit [") + len("limit [")
                        end = error_str.find("]", start)
                        range_str = error_str[start:end]
                        max_leverage = int(range_str.split(", ")[1])
                        
                        # 최대 레버리지로 재시도
                        result = self.futures_api.update_position_leverage(
                            settle='usdt',
                            contract=symbol,
                            leverage=str(max_leverage)
                        )
                        print(f"{get_kst_time()} ✅ [LEVERAGE] {symbol} = {max_leverage}x (최대 허용)")
                        return True
                    except:
                        pass
                        
                # 기본 대안 레버리지 시도 (10x)
                try:
                    result = self.futures_api.update_position_leverage(
                        settle='usdt',
                        contract=symbol,
                        leverage="10"
                    )
                    print(f"{get_kst_time()} ✅ [LEVERAGE] {symbol} = 10x (대안)")
                    return True
                except:
                    pass
            
            print(f"{get_kst_time()} ❌ [ERROR] 레버리지 설정 실패: {symbol} - {e}")
            return False
    
    def get_top_volume_symbols(self, limit: int = 15) -> List[str]:
        """거래량 상위 심볼 조회"""
        try:
            # 모든 USDT 선물 티커 조회
            result = self.futures_api.list_futures_tickers(settle='usdt')
            
            print(f"{get_kst_time()} 🔍 [DEBUG] 첫 번째 티커 속성 확인: {dir(result[0]) if result else 'No data'}")
            
            # 속성명 확인해서 거래량 기준으로 정렬
            if result and hasattr(result[0], 'volume_24h'):
                sorted_tickers = sorted(result, 
                                      key=lambda x: float(x.volume_24h) if x.volume_24h else 0, 
                                      reverse=True)
            elif result and hasattr(result[0], 'vol'):
                sorted_tickers = sorted(result, 
                                      key=lambda x: float(x.vol) if x.vol else 0, 
                                      reverse=True)
            else:
                # 속성을 찾을 수 없으면 기본 인기 심볼 반환
                print("거래량 속성을 찾을 수 없습니다. 기본 심볼을 사용합니다.")
                return ['BTC_USDT', 'ETH_USDT', 'BNB_USDT', 'ADA_USDT', 'SOL_USDT',
                       'XRP_USDT', 'DOGE_USDT', 'AVAX_USDT', 'DOT_USDT', 'MATIC_USDT',
                       'ATOM_USDT', 'LINK_USDT', 'UNI_USDT', 'LTC_USDT', 'BCH_USDT']
            
            # 상위 limit개 심볼 추출 (USDT 페어만)
            top_symbols = []
            for ticker in sorted_tickers[:limit*2]:  # 여유분으로 더 많이 가져옴
                symbol = ticker.contract
                if symbol.endswith('_USDT') and len(top_symbols) < limit:
                    # 일반적인 암호화폐만 포함 (너무 exotic한 것 제외)
                    base = symbol.replace('_USDT', '')
                    if len(base) <= 10:  # 토큰명이 너무 길지 않은 것만
                        top_symbols.append(symbol)
            
            print(f"{get_kst_time()} ✅ [SYMBOLS] 거래량 상위 {len(top_symbols)}개 심볼 조회 완료:")
            for i, symbol in enumerate(top_symbols, 1):
                print(f"  {i:2d}. {symbol}")
                
            return top_symbols
            
        except (ApiException, GateApiException) as e:
            print(f"{get_kst_time()} ❌ [ERROR] 거래량 상위 심볼 조회 실패: {e}")
            # 기본 인기 심볼 반환
            return ['BTC_USDT', 'ETH_USDT', 'BNB_USDT', 'ADA_USDT', 'SOL_USDT',
                   'XRP_USDT', 'DOGE_USDT', 'AVAX_USDT', 'DOT_USDT', 'MATIC_USDT',
                   'ATOM_USDT', 'LINK_USDT', 'UNI_USDT', 'LTC_USDT', 'BCH_USDT']
    
    def get_futures_positions(self) -> List[Dict]:
        """선물 포지션 조회"""
        try:
            result = self.futures_api.list_positions(settle='usdt')
            positions = []
            
            for position in result:
                if float(position.size) != 0:  # 포지션이 있는 경우만
                    positions.append({
                        'symbol': position.contract,
                        'side': 'long' if float(position.size) > 0 else 'short',
                        'size': abs(float(position.size)),
                        'entry_price': float(position.entry_price) if position.entry_price else 0,
                        'mark_price': float(position.mark_price) if position.mark_price else 0,
                        'unrealized_pnl': float(position.unrealised_pnl) if position.unrealised_pnl else 0,
                        'margin': float(position.margin) if position.margin else 0
                    })
            
            return positions
            
        except (ApiException, GateApiException) as e:
            print(f"포지션 조회 실패: {e}")
            return []
    
    def create_futures_order(self, symbol: str, side: str, size: float, 
                           order_type: str = "market", price: float = None,
                           time_in_force: str = "ioc") -> Dict:
        """선물 주문 생성"""
        try:
            # 주문 객체 생성
            order = gate_api.FuturesOrder(
                contract=symbol,
                size=int(size) if side == 'long' else -int(size),
                price=str(price) if price else None,
                tif=time_in_force
            )
            
            result = self.futures_api.create_futures_order(settle='usdt', futures_order=order)
            
            return {
                'order_id': result.id,
                'symbol': result.contract,
                'side': 'long' if result.size > 0 else 'short',
                'size': abs(result.size),
                'price': float(result.price) if result.price else 0,
                'status': result.status,
                'create_time': result.create_time
            }
            
        except (ApiException, GateApiException) as e:
            print(f"주문 생성 실패: {e}")
            return {}
    
    def cancel_futures_order(self, symbol: str, order_id: str) -> bool:
        """선물 주문 취소"""
        try:
            result = self.futures_api.cancel_futures_order(
                settle='usdt', 
                contract=symbol, 
                order_id=order_id
            )
            return True
        except (ApiException, GateApiException) as e:
            print(f"주문 취소 실패: {e}")
            return False
    
    def get_futures_orders(self, symbol: str, status: str = "open") -> List[Dict]:
        """선물 주문 조회"""
        try:
            result = self.futures_api.list_futures_orders(
                settle='usdt',
                contract=symbol,
                status=status
            )
            
            orders = []
            for order in result:
                orders.append({
                    'order_id': order.id,
                    'symbol': order.contract,
                    'side': 'long' if order.size > 0 else 'short',
                    'size': abs(order.size),
                    'price': float(order.price) if order.price else 0,
                    'filled': order.fill_price,
                    'status': order.status,
                    'create_time': order.create_time
                })
            
            return orders
            
        except (ApiException, GateApiException) as e:
            print(f"주문 조회 실패: {e}")
            return []
    
    def close_position(self, symbol: str) -> bool:
        """포지션 전체 청산"""
        try:
            positions = self.get_futures_positions()
            
            for position in positions:
                if position['symbol'] == symbol:
                    # 반대 방향으로 주문하여 청산
                    close_side = 'short' if position['side'] == 'long' else 'long'
                    
                    order = self.create_futures_order(
                        symbol=symbol,
                        side=close_side,
                        size=position['size'],
                        order_type='market'
                    )
                    
                    if order:
                        print(f"포지션 청산 완료: {symbol}")
                        return True
            
            return False
            
        except Exception as e:
            print(f"포지션 청산 실패: {e}")
            return False
    
    def test_connection(self) -> bool:
        """연결 테스트"""
        try:
            # 서버 시간 조회로 연결 테스트
            result = self.spot_api.get_system_time()
            print(f"{get_kst_time()} ✅ [GATEIO] 연결 성공! 서버 시간: {result}")
            return True
            
        except (ApiException, GateApiException) as e:
            print(f"{get_kst_time()} ❌ [ERROR] Gate.io 연결 실패: {e}")
            return False


# 사용 예시
if __name__ == "__main__":
    from settings import settings
    
    connector = GateIOConnector(
        api_key=settings.gate_api_key,
        secret_key=settings.gate_secret_key,
        testnet=settings.gate_testnet
    )
    
    # 연결 테스트
    if connector.test_connection():
        print(f"{get_kst_time()} ✅ [GATEIO] SDK 연결 성공!")
        
        # 데이터 조회 테스트
        df = connector.get_futures_klines('BTC_USDT', '1m', 10)
        print(f"최신 BTC 가격: {df['close'].iloc[-1] if not df.empty else 'N/A'}")
    else:
        print(f"{get_kst_time()} ❌ [ERROR] Gate.io 연결 실패!")