"""
Backwards compatibility shim for qr_login.py.
Redirects to unified auth_manager.py.
"""

from auth_manager import TikTokAuthManager, TikTokQRLoginManager, SESSION_FILE

__all__ = ["TikTokAuthManager", "TikTokQRLoginManager", "SESSION_FILE"]
