#!/usr/bin/env python3
"""
Credit Card Tracker
- Tracks spending across multiple credit cards
- Manages credit limits and due dates
- Calculates remaining available credit
- Secure storage of card configurations
"""
import json
import pandas as pd
import keyring
import argparse
import sys
from datetime import datetime, timedelta
from pathlib import Path
from cryptography.fernet import Fernet
from transaction_processor import categorize_transaction, process_csv_file

class CreditCardTracker:
    def __init__(self):
        self.cards = {}
        self.cipher_suite = self._setup_encryption()
        self.config_file = 'credit_cards.enc'
        self.load_cards()
    
    def _setup_encryption(self):
        """Set up encryption for secure storage."""
        encryption_key = keyring.get_password("credit_card_tracker", "encryption_key")
        
        if not encryption_key:
            key = Fernet.generate_key()
            keyring.set_password("credit_card_tracker", "encryption_key", key.decode())
            encryption_key = key.decode()
            
        return Fernet(encryption_key.encode())
    
    def add_card(self, name, credit_limit, statement_date, due_date, description=""):
        """Add a new credit card to track."""
        self.cards[name] = {
            'credit_limit': float(credit_limit),
            'statement_date': int(statement_date),  # Day of month (e.g., 15 for 15th)
            'due_date': int(due_date),  # Day of month (e.g., 12 for 12th)
            'description': description,
            'current_balance': 0.0,
            'last_updated': datetime.now().isoformat()
        }
        self.save_cards()
        print(f"Added credit card: {name}")
    
    def remove_card(self, name):
        """Remove a credit card."""
        if name in self.cards:
            del self.cards[name]
            self.save_cards()
            print(f"Removed credit card: {name}")
        else:
            print(f"Card '{name}' not found")
    
    def list_cards(self):
        """List all configured credit cards."""
        if not self.cards:
            print("No credit cards configured")
            return
        
        print("\n=== Configured Credit Cards ===")
        for name, card in self.cards.items():
            print(f"{name}:")
            print(f"  Credit Limit: ${card['credit_limit']:,.2f}")
            print(f"  Statement Date: {card['statement_date']} (day of month)")
            print(f"  Due Date: {card['due_date']} (day of month)")
            print(f"  Current Balance: ${card['current_balance']:,.2f}")
            print(f"  Available Credit: ${card['credit_limit'] - card['current_balance']:,.2f}")
            if card['description']:
                print(f"  Description: {card['description']}")
            print()
    
    def update_balance(self, name, amount):
        """Manually update a card's balance."""
        if name not in self.cards:
            print(f"Card '{name}' not found")
            return
        
        self.cards[name]['current_balance'] = float(amount)
        self.cards[name]['last_updated'] = datetime.now().isoformat()
        self.save_cards()
        print(f"Updated {name} balance to ${amount:,.2f}")
    
    def process_transactions(self, csv_files, card_mapping=None):
        """Process transaction files and update card balances."""
        if not csv_files:
            print("No transaction files provided")
            return
        
        # Combine all transaction files
        all_dfs = []
        for file_path in csv_files:
            df = process_csv_file(file_path)
            if not df.empty:
                all_dfs.append(df)
        
        if not all_dfs:
            print("No valid transaction data found")
            return
        
        # Combine all DataFrames
        df = pd.concat(all_dfs, ignore_index=True) if len(all_dfs) > 1 else all_dfs[0]
        
        # If no card mapping provided, try to auto-detect or ask user
        if not card_mapping:
            card_mapping = self._auto_detect_cards(df)
        
        # Calculate spending for each card
        for card_name in self.cards.keys():
            if card_name in card_mapping:
                # Filter transactions for this card based on file pattern or description
                card_df = self._filter_transactions_for_card(df, card_mapping[card_name])
                
                # Calculate total spending (negative amounts)
                spending = abs(card_df[card_df['Amount'] < 0]['Amount'].sum())
                
                # Update balance
                self.cards[card_name]['current_balance'] = spending
                self.cards[card_name]['last_updated'] = datetime.now().isoformat()
        
        self.save_cards()
        print(f"Updated balances from {len(df)} transactions")
    
    def _auto_detect_cards(self, df):
        """Attempt to auto-detect which card transactions belong to."""
        card_mapping = {}
        
        # Simple heuristic: if file name or transaction patterns suggest a card
        for card_name in self.cards.keys():
            card_lower = card_name.lower()
            if 'chase' in card_lower:
                card_mapping[card_name] = 'chase'
            elif 'apple' in card_lower:
                card_mapping[card_name] = 'apple'
            elif 'amex' in card_lower:
                card_mapping[card_name] = 'amex'
            elif 'citi' in card_lower:
                card_mapping[card_name] = 'citi'
        
        return card_mapping
    
    def _filter_transactions_for_card(self, df, card_identifier):
        """Filter transactions for a specific card."""
        # For now, return all transactions
        # In a real implementation, you'd filter based on:
        # - File source
        # - Transaction patterns
        # - Card-specific identifiers
        return df
    
    def show_summary(self):
        """Display current spending summary for all cards."""
        if not self.cards:
            print("No credit cards configured")
            return
        
        print("\n" + "="*50)
        print("CREDIT CARD SPENDING SUMMARY")
        print("="*50)
        
        total_spent = 0.0
        total_available = 0.0
        
        for name, card in self.cards.items():
            balance = card['current_balance']
            limit = card['credit_limit']
            available = limit - balance
            
            total_spent += balance
            total_available += available
            
            # Format the display
            if balance > 0:
                print(f"{name:<15} $ {balance:>10,.2f}")
            else:
                print(f"{name:<15} $ {'-':>10}")
        
        print("-" * 30)
        print(f"{'Left to Spend':<15} $ {total_available:>10,.2f}")
        print("-" * 30)
        print(f"**Total Spent   $ {total_spent:>10,.2f}**")
        print("="*50)
    
    def show_due_dates(self):
        """Show upcoming due dates."""
        if not self.cards:
            print("No credit cards configured")
            return
        
        today = datetime.now()
        current_month = today.month
        current_year = today.year
        
        print("\n=== Upcoming Due Dates ===")
        due_dates = []
        
        for name, card in self.cards.items():
            # Calculate next due date
            due_day = card['due_date']
            
            # If due date hasn't passed this month, use this month
            if due_day >= today.day:
                due_date = datetime(current_year, current_month, due_day)
            else:
                # Due date has passed, use next month
                if current_month == 12:
                    due_date = datetime(current_year + 1, 1, due_day)
                else:
                    due_date = datetime(current_year, current_month + 1, due_day)
            
            days_until_due = (due_date - today).days
            due_dates.append((name, due_date, days_until_due, card['current_balance']))
        
        # Sort by days until due
        due_dates.sort(key=lambda x: x[2])
        
        for name, due_date, days_until, balance in due_dates:
            status = ""
            if days_until <= 3:
                status = " ⚠️  URGENT"
            elif days_until <= 7:
                status = " ⚡ SOON"
            
            print(f"{name:<15} {due_date.strftime('%Y-%m-%d')} ({days_until:>2d} days) ${balance:>8,.2f}{status}")
    
    def reset_balances(self):
        """Reset all card balances to zero."""
        for card in self.cards.values():
            card['current_balance'] = 0.0
            card['last_updated'] = datetime.now().isoformat()
        
        self.save_cards()
        print("Reset all card balances to $0.00")
    
    def save_cards(self):
        """Save card configuration to encrypted file."""
        try:
            json_data = json.dumps(self.cards, indent=2)
            encrypted_data = self.cipher_suite.encrypt(json_data.encode())
            
            with open(self.config_file, 'wb') as f:
                f.write(encrypted_data)
        except Exception as e:
            print(f"Error saving cards: {e}")
    
    def load_cards(self):
        """Load card configuration from encrypted file."""
        try:
            if not Path(self.config_file).exists():
                return
            
            with open(self.config_file, 'rb') as f:
                encrypted_data = f.read()
            
            decrypted_data = self.cipher_suite.decrypt(encrypted_data).decode()
            self.cards = json.loads(decrypted_data)
        except Exception as e:
            print(f"Note: Could not load existing cards ({e}). Starting fresh.")
            self.cards = {}

def main():
    """Main function with command line interface."""
    parser = argparse.ArgumentParser(description='Credit Card Spending Tracker')
    parser.add_argument('--add-card', nargs=4, metavar=('NAME', 'LIMIT', 'STMT_DATE', 'DUE_DATE'),
                       help='Add new card: name, credit_limit, statement_date, due_date')
    parser.add_argument('--add-card-desc', help='Description for the card being added')
    parser.add_argument('--remove-card', help='Remove a credit card')
    parser.add_argument('--list-cards', action='store_true', help='List all configured cards')
    parser.add_argument('--update-balance', nargs=2, metavar=('NAME', 'AMOUNT'),
                       help='Update card balance: card_name amount')
    parser.add_argument('--process-transactions', nargs='+', metavar='CSV_FILE',
                       help='Process transaction files to update balances')
    parser.add_argument('--summary', action='store_true', help='Show spending summary')
    parser.add_argument('--due-dates', action='store_true', help='Show upcoming due dates')
    parser.add_argument('--reset', action='store_true', help='Reset all balances to zero')
    
    args = parser.parse_args()
    
    tracker = CreditCardTracker()
    
    if args.add_card:
        name, limit, stmt_date, due_date = args.add_card
        description = args.add_card_desc or ""
        tracker.add_card(name, limit, stmt_date, due_date, description)
    
    elif args.remove_card:
        tracker.remove_card(args.remove_card)
    
    elif args.list_cards:
        tracker.list_cards()
    
    elif args.update_balance:
        name, amount = args.update_balance
        tracker.update_balance(name, float(amount))
    
    elif args.process_transactions:
        tracker.process_transactions(args.process_transactions)
    
    elif args.due_dates:
        tracker.show_due_dates()
    
    elif args.reset:
        confirm = input("Are you sure you want to reset all balances to $0.00? (yes/no): ")
        if confirm.lower() == 'yes':
            tracker.reset_balances()
        else:
            print("Reset cancelled")
    
    elif args.summary:
        tracker.show_summary()
    
    else:
        # Default: show summary
        tracker.show_summary()

if __name__ == "__main__":
    main()