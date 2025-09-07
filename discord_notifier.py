import requests
import json
from datetime import datetime
from typing import Dict, Optional, Any
import logging
from settings import settings

logger = logging.getLogger(__name__)


class DiscordNotifier:
    """Discord 웹훅을 통한 알림 시스템"""
    
    def __init__(self):
        self.webhook_url = settings.notifications.discord_webhook_url
        self.enabled = settings.notifications.enable_discord and bool(self.webhook_url)
        
        if not self.enabled:
            logger.warning("Discord 알림이 비활성화되었습니다. 웹훅 URL을 확인해주세요.")
    
    def _send_embed(self, embed: Dict[str, Any]) -> bool:
        """Discord 임베드 메시지 전송"""
        if not self.enabled:
            return False
        
        try:
            payload = {"embeds": [embed]}
            response = requests.post(self.webhook_url, json=payload, timeout=10)
            response.raise_for_status()
            return True
        except Exception as e:
            logger.error(f"Discord 알림 전송 실패: {e}")
            return False
    
    def send_trade_signal(self, signal_type: str, symbol: str, price: float, 
                         reason: str, confidence: float) -> bool:
        """거래 신호 알림"""
        if not settings.notifications.notify_on_trade:
            return False
        
        color = settings.notifications.color_profit if signal_type == "BUY" else settings.notifications.color_loss
        
        embed = {
            "title": f"🎯 거래 신호 발생",
            "color": color,
            "timestamp": datetime.utcnow().isoformat(),
            "fields": [
                {"name": "신호", "value": f"**{signal_type}**", "inline": True},
                {"name": "심볼", "value": symbol, "inline": True},
                {"name": "가격", "value": f"{price:,.2f} USDT", "inline": True},
                {"name": "신뢰도", "value": f"{confidence:.1%}", "inline": True},
                {"name": "사유", "value": reason, "inline": False}
            ],
            "footer": {"text": "Gate.io 스켈핑 봇"}
        }
        
        return self._send_embed(embed)
    
    def send_position_opened(self, side: str, symbol: str, entry_price: float, 
                           size: float, stop_loss: float, take_profit: float, 
                           allocated_amount: float = None) -> bool:
        """포지션 진입 알림"""
        if not settings.notifications.notify_on_trade:
            return False
        
        color = settings.notifications.color_info
        direction_emoji = "📈" if side == "long" else "📉"
        
        # 심볼에서 코인명 추출 (예: BTC_USDT -> BTC, LINK_USDT -> LINK)
        coin_name = symbol.split('_')[0]
        
        # 진입 시드 계산 (사이즈 * 진입가)
        position_value = size * entry_price
        
        # 기본 필드들
        fields = [
            {"name": "방향", "value": side.upper(), "inline": True},
            {"name": "심볼", "value": symbol, "inline": True},
            {"name": "진입 시드", "value": f"{position_value:.2f} USDT", "inline": True},
            {"name": "진입가", "value": f"{entry_price:,.2f} USDT", "inline": True},
            {"name": "손절가", "value": f"{stop_loss:,.2f} USDT", "inline": True},
            {"name": "익절가", "value": f"{take_profit:,.2f} USDT", "inline": True}
        ]
        
        embed = {
            "title": f"{direction_emoji} 포지션 진입",
            "color": color,
            "timestamp": datetime.utcnow().isoformat(),
            "fields": fields,
            "footer": {"text": "Gate.io 스켈핑 봇"}
        }
        
        return self._send_embed(embed)
    
    def send_position_closed(self, side: str, symbol: str, entry_price: float, 
                           exit_price: float, size: float, pnl: float, 
                           pnl_pct: float, exit_reason: str, 
                           allocated_amount: float = None) -> bool:
        """포지션 청산 알림"""
        is_profit = pnl > 0
        if not ((is_profit and settings.notifications.notify_on_profit) or 
                (not is_profit and settings.notifications.notify_on_loss)):
            return False
        
        color = settings.notifications.color_profit if is_profit else settings.notifications.color_loss
        result_emoji = "✅" if is_profit else "❌"
        
        # 심볼에서 코인명 추출 (예: BTC_USDT -> BTC, LINK_USDT -> LINK)
        coin_name = symbol.split('_')[0]
        
        # 진입 시드 계산 (사이즈 * 진입가)
        position_value = size * entry_price
        
        # 기본 필드들
        fields = [
            {"name": "방향", "value": side.upper(), "inline": True},
            {"name": "심볼", "value": symbol, "inline": True},
            {"name": "진입 시드", "value": f"{position_value:.2f} USDT", "inline": True},
            {"name": "진입가", "value": f"{entry_price:,.2f} USDT", "inline": True},
            {"name": "청산가", "value": f"{exit_price:,.2f} USDT", "inline": True},
            {"name": "청산사유", "value": exit_reason, "inline": True},
            {"name": "손익", "value": f"{pnl:+,.2f} USDT", "inline": True},
            {"name": "수익률", "value": f"{pnl_pct:+.2f}%", "inline": True}
        ]
        
        embed = {
            "title": f"{result_emoji} 포지션 청산",
            "color": color,
            "timestamp": datetime.utcnow().isoformat(),
            "fields": fields,
            "footer": {"text": "Gate.io 스켈핑 봇"}
        }
        
        return self._send_embed(embed)
    
    def send_daily_summary(self, date: str, total_trades: int, winning_trades: int,
                          total_pnl: float, win_rate: float, balance: float) -> bool:
        """일일 요약 알림"""
        if not settings.notifications.notify_on_daily_summary:
            return False
        
        color = settings.notifications.color_profit if total_pnl > 0 else settings.notifications.color_loss
        
        embed = {
            "title": "📊 일일 거래 요약",
            "color": color,
            "timestamp": datetime.utcnow().isoformat(),
            "fields": [
                {"name": "날짜", "value": date, "inline": False},
                {"name": "총 거래", "value": str(total_trades), "inline": True},
                {"name": "승리 거래", "value": str(winning_trades), "inline": True},
                {"name": "승률", "value": f"{win_rate:.1%}", "inline": True},
                {"name": "일일 손익", "value": f"{total_pnl:+,.2f} USDT", "inline": True},
                {"name": "현재 잔고", "value": f"{balance:,.2f} USDT", "inline": True}
            ],
            "footer": {"text": "Gate.io 스켈핑 봇"}
        }
        
        return self._send_embed(embed)
    
    def send_backtest_result(self, result_summary: Dict[str, Any]) -> bool:
        """백테스트 결과 알림"""
        color = settings.notifications.color_profit if result_summary['net_pnl'] > 0 else settings.notifications.color_loss
        
        embed = {
            "title": "📈 백테스트 결과",
            "color": color,
            "timestamp": datetime.utcnow().isoformat(),
            "fields": [
                {"name": "기간", "value": f"{result_summary.get('period', 'N/A')}일", "inline": True},
                {"name": "총 거래", "value": str(result_summary['total_trades']), "inline": True},
                {"name": "승률", "value": f"{result_summary['win_rate']:.1%}", "inline": True},
                {"name": "순손익", "value": f"{result_summary['net_pnl']:+,.2f} USDT", "inline": True},
                {"name": "수익률", "value": f"{result_summary['total_pnl_pct']:+.2f}%", "inline": True},
                {"name": "Profit Factor", "value": f"{result_summary['profit_factor']:.2f}", "inline": True},
                {"name": "최대 낙폭", "value": f"{result_summary['max_drawdown_pct']:.2f}%", "inline": True},
                {"name": "샤프 비율", "value": f"{result_summary['sharpe_ratio']:.2f}", "inline": True}
            ],
            "footer": {"text": "Gate.io 스켈핑 봇"}
        }
        
        return self._send_embed(embed)
    
    def send_error_alert(self, error_type: str, error_message: str, 
                        additional_info: Optional[str] = None) -> bool:
        """오류 알림"""
        if not settings.notifications.notify_on_error:
            return False
        
        fields = [
            {"name": "오류 유형", "value": error_type, "inline": True},
            {"name": "오류 메시지", "value": error_message[:1000], "inline": False}
        ]
        
        if additional_info:
            fields.append({"name": "추가 정보", "value": additional_info[:1000], "inline": False})
        
        embed = {
            "title": "⚠️ 시스템 오류 발생",
            "color": settings.notifications.color_error,
            "timestamp": datetime.utcnow().isoformat(),
            "fields": fields,
            "footer": {"text": "Gate.io 스켈핑 봇"}
        }
        
        return self._send_embed(embed)
    
    def send_bot_status(self, status: str, message: str) -> bool:
        """봇 상태 알림"""
        status_colors = {
            "started": settings.notifications.color_info,
            "stopped": settings.notifications.color_warning,
            "error": settings.notifications.color_error,
            "info": settings.notifications.color_info
        }
        
        status_emojis = {
            "started": "🚀",
            "stopped": "⏹️",
            "error": "🔥",
            "info": "ℹ️"
        }
        
        color = status_colors.get(status, settings.notifications.color_info)
        emoji = status_emojis.get(status, "ℹ️")
        
        embed = {
            "title": f"{emoji} 봇 상태",
            "color": color,
            "timestamp": datetime.utcnow().isoformat(),
            "fields": [
                {"name": "상태", "value": status.upper(), "inline": True},
                {"name": "메시지", "value": message, "inline": False}
            ],
            "footer": {"text": "Gate.io 스켈핑 봇"}
        }
        
        return self._send_embed(embed)
    
    def send_multi_symbol_bot_started(self, symbols_count: int, balance: float, 
                                    allocated_amount: float, allocation_pct: float, 
                                    leverage: int) -> bool:
        """다중 심볼 봇 시작 알림"""
        embed = {
            "title": "🚀 다중심볼 봇 시작",
            "color": settings.notifications.color_info,
            "timestamp": datetime.utcnow().isoformat(),
            "fields": [
                {"name": "거래대상", "value": f"{symbols_count}개 심볼", "inline": True},
                {"name": "레버리지", "value": f"{leverage}x", "inline": True},
                {"name": "총잔고", "value": f"{balance:.2f} USDT", "inline": True},
                {"name": "사용자금", "value": f"{allocated_amount:.2f} USDT", "inline": True},
                {"name": "자금비율", "value": f"{allocation_pct:.0%}", "inline": True},
                {"name": "상태", "value": "가동중", "inline": True}
            ],
            "footer": {"text": "Gate.io 스켈핑 봇"}
        }
        
        return self._send_embed(embed)
    
    def test_connection(self) -> bool:
        """Discord 연결 테스트"""
        embed = {
            "title": "🧪 Discord 연결 테스트",
            "color": settings.notifications.color_info,
            "timestamp": datetime.utcnow().isoformat(),
            "fields": [
                {"name": "상태", "value": "연결 성공!", "inline": False},
                {"name": "시간", "value": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "inline": False}
            ],
            "footer": {"text": "Gate.io 스켈핑 봇"}
        }
        
        result = self._send_embed(embed)
        if result:
            logger.info("Discord 연결 테스트 성공")
        else:
            logger.error("Discord 연결 테스트 실패")
        
        return result


# 전역 알림 인스턴스
discord_notifier = DiscordNotifier()


if __name__ == "__main__":
    # 테스트 실행
    print("Discord 알림 테스트 시작...")
    
    if discord_notifier.enabled:
        # 연결 테스트
        discord_notifier.test_connection()
        
        # 거래 신호 테스트
        discord_notifier.send_trade_signal("BUY", "BTC_USDT", 45000.0, "상승 추세 돌파", 0.85)
        
        # 포지션 진입 테스트
        discord_notifier.send_position_opened("long", "BTC_USDT", 45000.0, 0.1, 44000.0, 46000.0)
        
        # 포지션 청산 테스트 (수익)
        discord_notifier.send_position_closed("long", "BTC_USDT", 45000.0, 45500.0, 0.1, 50.0, 1.11, "익절")
        
        print("테스트 알림을 Discord로 전송했습니다.")
    else:
        print("Discord 알림이 비활성화되어 있습니다. .env 파일의 DISCORD_WEBHOOK_URL을 설정해주세요.")
