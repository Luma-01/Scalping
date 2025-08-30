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
            print(f"{get_kst_time()} ❌ [KLINE] {symbol} K라인 조회 실패: {e}")
            return pd.DataFrame()
        except Exception as e:
            print(f"{get_kst_time()} ❌ [KLINE] {symbol} K라인 조회 예외: {e}")
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
                    'volume': float(ticker.volume_24h) if hasattr(ticker, 'volume_24h') else 0,
                    'change_percentage': float(ticker.change_percentage) if ticker.change_percentage else 0
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
        """거래량 상위 심볼 조회 - 안정적인 주요 심볼 사용"""
        # Gate.io 선물 거래에서 실제 거래량이 높은 주요 심볼들 (2025년 1월 기준)
        major_symbols = [
            'BTC_USDT',   # 비트코인 - 가장 높은 거래량
            'ETH_USDT',   # 이더리움 - 2위 거래량
            'SOL_USDT',   # 솔라나 - 3위 거래량
            'XRP_USDT',   # 리플 - 4위 거래량  
            'DOGE_USDT',  # 도지코인 - 5위 거래량
            'ADA_USDT',   # 카르다노
            'AVAX_USDT',  # 아발란체
            'LINK_USDT',  # 체인링크
            'DOT_USDT',   # 폴카닷
            'MATIC_USDT', # 폴리곤
            'UNI_USDT',   # 유니스왑
            'LTC_USDT',   # 라이트코인
            'BCH_USDT',   # 비트코인캐시
            'FIL_USDT',   # 파일코인
            'ATOM_USDT',  # 코스모스
            'TRX_USDT',   # 트론
            'ETC_USDT',   # 이더리움클래식
            'NEAR_USDT',  # 니어프로토콜
            'ICP_USDT',   # 인터넷컴퓨터
            'ARB_USDT'    # 아비트럼
        ]
        
        try:
            # 모든 USDT 선물 티커 조회
            result = self.futures_api.list_futures_tickers(settle='usdt')
            
            if not result:
                return major_symbols[:limit]
            
            # Gate.io 공식 문서에 따른 올바른 거래량 속성 선택
            # volume_24h_base: 베이스 화폐 단위의 거래량 (가장 정확)
            # volume_24h_settle: 결제 화폐 단위의 거래량 (USDT 선물의 경우 적합)
            # volume_24h: 총 거래량 (계약 단위)
            
            volume_attr = None
            attrs_priority = ['volume_24h_settle', 'volume_24h_base', 'volume_24h']
            
            print(f"{get_kst_time()} 🔍 [DEBUG] 거래량 속성 확인:")
            for attr in attrs_priority:
                if hasattr(result[0], attr):
                    # 첫 번째 티커에서 값이 유효한지 확인
                    test_value = getattr(result[0], attr)
                    if test_value and float(test_value) > 0:
                        volume_attr = attr
                        print(f"  {attr}: 사용 가능 (값: {test_value})")
                        break
                    else:
                        print(f"  {attr}: 값 없음 또는 0")
            
            if not volume_attr:
                print(f"{get_kst_time()} ❌ [ERROR] 유효한 거래량 속성을 찾을 수 없음")
                return major_symbols[:limit]
            
            print(f"{get_kst_time()} ✅ [VOLUME] {volume_attr} 속성으로 정렬")
            
            # 선택된 속성으로 정렬
            sorted_tickers = sorted(result, 
                                  key=lambda x: float(getattr(x, volume_attr)) if getattr(x, volume_attr) else 0, 
                                  reverse=True)
            
            # 상위 15개 출력 (디버깅)
            print(f"{get_kst_time()} 🔍 [TOP15] {volume_attr} 기준 상위 15개:")
            for i, ticker in enumerate(sorted_tickers[:15], 1):
                volume = float(getattr(ticker, volume_attr)) if getattr(ticker, volume_attr) else 0
                print(f"  {i:2d}. {ticker.contract:<15} ({volume:,.0f})")
            
            # USDT 페어만 선별하여 최종 리스트 생성
            top_symbols = []
            for ticker in sorted_tickers:
                symbol = ticker.contract
                if symbol.endswith('_USDT') and len(top_symbols) < limit:
                    top_symbols.append(symbol)
            
            print(f"{get_kst_time()} ✅ [SYMBOLS] 거래량 상위 {len(top_symbols)}개 심볼:")
            for i, symbol in enumerate(top_symbols, 1):
                print(f"  {i:2d}. {symbol}")
                
            return top_symbols
            
        except (ApiException, GateApiException) as e:
            print(f"{get_kst_time()} ❌ [ERROR] 심볼 조회 실패: {e}")
            # 최소한의 안전한 심볼 반환
            return ['BTC_USDT', 'ETH_USDT', 'SOL_USDT', 'XRP_USDT', 'DOGE_USDT'][:limit]
    
    def get_contract_info(self, symbol: str) -> Dict:
        """Contract 정보 조회 (Contract Size 포함)"""
        try:
            result = self.futures_api.get_futures_contract(settle='usdt', contract=symbol)
            if result:
                contract_info = {
                    'symbol': result.name,
                    'order_size_min': float(result.order_size_min) if result.order_size_min else 1,
                    'order_size_max': float(result.order_size_max) if result.order_size_max else 1000000,
                    'quanto_multiplier': float(result.quanto_multiplier) if hasattr(result, 'quanto_multiplier') and result.quanto_multiplier else None
                }
                
                # Contract Size 계산 (SDK 주문 크기 1당 실제 암호화폐 수량)
                # Gate.io에서는 보통 quanto_multiplier가 Contract Size 역할을 함
                if contract_info['quanto_multiplier']:
                    contract_info['contract_size'] = contract_info['quanto_multiplier']
                else:
                    # quanto_multiplier가 없으면 기본값 사용 (추후 실제 거래에서 학습)
                    base_symbol = symbol.split('_')[0]
                    if base_symbol in ['XRP', 'DOGE']:
                        contract_info['contract_size'] = 10
                    elif base_symbol in ['BTC']:
                        contract_info['contract_size'] = 0.0001
                    elif base_symbol in ['ETH']:
                        contract_info['contract_size'] = 0.01
                    else:
                        contract_info['contract_size'] = 1
                
                print(f"{get_kst_time()} 📋 [CONTRACT] {symbol} Contract Size: {contract_info['contract_size']}")
                return contract_info
                
        except (ApiException, GateApiException) as e:
            print(f"Contract 정보 조회 실패: {e}")
            # 기본값 반환
            base_symbol = symbol.split('_')[0]
            if base_symbol in ['XRP', 'DOGE']:
                contract_size = 10
            elif base_symbol in ['BTC']:
                contract_size = 0.0001
            elif base_symbol in ['ETH']:
                contract_size = 0.01
            else:
                contract_size = 1
            
            print(f"{get_kst_time()} 📋 [CONTRACT] {symbol} Contract Size (기본값): {contract_size}")
            return {
                'symbol': symbol,
                'contract_size': contract_size,
                'order_size_min': 1,
                'order_size_max': 1000000
            }

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
        """선물 주문 생성 (Contract Size 고려)"""
        try:
            # 1. Contract 정보 조회하여 Contract Size 획득
            contract_info = self.get_contract_info(symbol)
            contract_size = contract_info.get('contract_size', 1)
            
            # 2. 실제 원하는 암호화폐 수량을 SDK 계약 단위로 변환
            # 예: 10 XRP를 원하면 Contract Size가 10이므로 SDK에는 1계약 주문
            sdk_size = size / contract_size
            
            print(f"{get_kst_time()} 📊 [ORDER] {symbol} 원하는 수량: {size} {symbol.split('_')[0]}")
            print(f"{get_kst_time()} 📊 [ORDER] Contract Size: {contract_size}, SDK 주문: {sdk_size}계약")
            
            # 3. size 계산: long이면 양수, short이면 음수
            order_size = sdk_size if side == 'long' else -sdk_size
            
            # 4. 정수로 변환 (Gate.io는 정수 크기 요구)
            order_size_int = int(order_size)
            if order_size_int == 0:
                print(f"{get_kst_time()} ❌ [ERROR] 주문 크기가 0이 됨. 최소 1계약 이상 필요")
                return {}
            
            # 5. 주문 객체 생성
            if order_type == "market":
                # 시장가 주문: price는 '0', tif는 'ioc'
                order = gate_api.FuturesOrder(
                    contract=symbol,
                    size=order_size_int,
                    price='0',  # 시장가는 '0'
                    tif='ioc'   # 시장가는 보통 IOC
                )
            else:
                # 지정가 주문
                order = gate_api.FuturesOrder(
                    contract=symbol,
                    size=order_size_int,
                    price=str(price),
                    tif=time_in_force
                )
            
            result = self.futures_api.create_futures_order(settle='usdt', futures_order=order)
            
            # 6. 실제 거래된 암호화폐 수량 계산
            actual_contracts = abs(result.size)
            actual_crypto_size = actual_contracts * contract_size
            
            print(f"{get_kst_time()} ✅ [ORDER] 실제 거래: {actual_contracts}계약 = {actual_crypto_size} {symbol.split('_')[0]}")
            
            return {
                'order_id': result.id,
                'symbol': result.contract,
                'side': 'long' if result.size > 0 else 'short',
                'size': actual_crypto_size,  # 실제 암호화폐 수량
                'contracts': actual_contracts,  # SDK 계약 수
                'contract_size': contract_size,
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
    
    def get_futures_trades(self, start_time: int = None, end_time: int = None, 
                          symbol: str = None, limit: int = 100) -> List[Dict]:
        """선물 거래내역 조회
        
        Args:
            start_time: 시작 시간 (timestamp)
            end_time: 종료 시간 (timestamp)  
            symbol: 심볼 (None이면 전체)
            limit: 조회 개수
        """
        try:
            trades = []
            
            if symbol:
                # 특정 심볼의 거래내역
                result = self.futures_api.list_my_trades(
                    settle='usdt',
                    contract=symbol,
                    from_=start_time,
                    to=end_time,
                    limit=limit
                )
                trades.extend(result)
            else:
                # 전체 심볼의 거래내역 (최근 거래된 심볼들 조회)
                try:
                    # 먼저 최근 거래 기록이 있는 심볼들 찾기
                    recent_symbols = set()
                    
                    # 계정의 포지션 기록에서 심볼 추출
                    positions = self.futures_api.list_positions(settle='usdt')
                    for pos in positions:
                        if float(pos.size) != 0:  # 포지션이 있는 심볼
                            recent_symbols.add(pos.contract)
                    
                    # 각 심볼별로 거래내역 조회
                    for symbol_name in recent_symbols:
                        try:
                            symbol_trades = self.futures_api.list_my_trades(
                                settle='usdt',
                                contract=symbol_name,
                                from_=start_time,
                                to=end_time,
                                limit=limit
                            )
                            trades.extend(symbol_trades)
                        except Exception as e:
                            continue  # 해당 심볼 조회 실패시 넘어감
                    
                except Exception:
                    # 포지션 조회 실패시 주요 심볼들로 시도
                    major_symbols = ['BTC_USDT', 'ETH_USDT', 'XRP_USDT', 'SOL_USDT', 'DOGE_USDT']
                    for symbol_name in major_symbols:
                        try:
                            symbol_trades = self.futures_api.list_my_trades(
                                settle='usdt',
                                contract=symbol_name,
                                from_=start_time,
                                to=end_time,
                                limit=limit
                            )
                            trades.extend(symbol_trades)
                        except Exception:
                            continue
            
            # 결과를 Dict 형태로 변환
            trade_list = []
            for trade in trades:
                trade_dict = {
                    'id': trade.id,
                    'create_time': trade.create_time,
                    'contract': trade.contract,
                    'order_id': trade.order_id,
                    'size': float(trade.size),
                    'price': float(trade.price),
                    'role': trade.role,  # taker, maker
                    'text': getattr(trade, 'text', ''),
                    'fee': float(getattr(trade, 'fee', 0)),
                    'point_fee': float(getattr(trade, 'point_fee', 0))
                }
                
                # PnL 계산 (대략적)
                if hasattr(trade, 'pnl'):
                    trade_dict['pnl'] = float(trade.pnl)
                else:
                    trade_dict['pnl'] = 0
                
                trade_list.append(trade_dict)
            
            # 시간순 정렬
            trade_list.sort(key=lambda x: x['create_time'], reverse=True)
            
            print(f"{get_kst_time()} 📊 [TRADES] {len(trade_list)}개 거래내역 조회 완료")
            return trade_list
            
        except (ApiException, GateApiException) as e:
            print(f"{get_kst_time()} ❌ [ERROR] 거래내역 조회 실패: {e}")
            return []
    
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