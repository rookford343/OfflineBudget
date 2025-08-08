"""
Credit Card Tracker Core Package
"""
from .credit_card_tracker import CreditCardTracker, TimePeriodAnalyzer
from .transaction_processor import main as process_transactions

__version__ = "1.0.0"
__all__ = ['CreditCardTracker', 'TimePeriodAnalyzer', 'process_transactions']