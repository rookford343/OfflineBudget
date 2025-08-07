#!/usr/bin/env python3
"""
Enhanced Credit Card Tracker
- Tracks spending across multiple credit cards
- Manages credit limits, due dates, and balances
- Soft/hard spending limits with alerts
- Automatic transaction processing
- Secure storage of card configurations
"""
import json
import pandas as pd
import keyring
import argparse
import sys
import re
from datetime import datetime, timedelta
from pathlib import Path
from cryptography.fernet import Fernet
from transaction_processor import categorize_transaction, process_csv_file

class CreditCardTracker:
    def __init__(self):
        self.cards = {}
        self.spending_limits = {}
        self.cipher_suite = self._setup_encryption()
        self.config_file = 'credit_cards.enc'
        self.limits_file = 'spending_limits.enc'
        self.load_cards()
        self.load_spending_limits()
    
    def _setup_encryption(self):
        """Set up encryption for secure storage."""
        encryption_key = keyring.get_password("credit_card_tracker", "encryption_key")
        
        if not encryption_key:
            key = Fernet.generate_key()
            keyring.set_password("credit_card_tracker", "encryption_key", key.decode())
            encryption_key = key.decode()
            
        return Fernet(encryption_key.encode())
    
    def add_card(self, name, credit_limit, statement_date, due_date, description="", balance_due=0.0):
        """Add a new credit card to track."""
        self.cards[name] = {
            'credit_limit': float(credit_limit),
            'statement_date': int(statement_date),  # Day of month (e.g., 15 for 15th)
            'due_date': int(due_date),  # Day of month (e.g., 12 for 12th)
            'description': description,
            'current_balance': 0.0,  # New spending since last statement
            'balance_due': float(balance_due),  # Balance from previous statement
            'last_updated': datetime.now().isoformat(),
            'last_statement_reset': datetime.now().isoformat()
        }
        self.save_cards()
        print(f"Added credit card: {name}")
    
    def update_card(self, name, **kwargs):
        """Update existing card details."""
        if name not in self.cards:
            print(f"Card '{name}' not found")
            return
        
        card = self.cards[name]
        updated_fields = []
        
        if 'credit_limit' in kwargs:
            card['credit_limit'] = float(kwargs['credit_limit'])
            updated_fields.append(f"credit limit: ${card['credit_limit']:,.2f}")
        
        if 'statement_date' in kwargs:
            card['statement_date'] = int(kwargs['statement_date'])
            updated_fields.append(f"statement date: {card['statement_date']}")
        
        if 'due_date' in kwargs:
            card['due_date'] = int(kwargs['due_date'])
            updated_fields.append(f"due date: {card['due_date']}")
        
        if 'description' in kwargs:
            card['description'] = kwargs['description']
            updated_fields.append(f"description: {card['description']}")
        
        if 'balance_due' in kwargs:
            card['balance_due'] = float(kwargs['balance_due'])
            updated_fields.append(f"balance due: ${card['balance_due']:,.2f}")
        
        if updated_fields:
            card['last_updated'] = datetime.now().isoformat()
            self.save_cards()
            print(f"Updated {name}: {', '.join(updated_fields)}")
        else:
            print("No valid fields provided for update")
    
    def set_spending_limits(self, soft_limit, hard_limit):
        """Set monthly spending limits."""
        current_month = datetime.now().strftime('%Y-%m')
        
        self.spending_limits[current_month] = {
            'soft_limit': float(soft_limit),
            'hard_limit': float(hard_limit),
            'created_date': datetime.now().isoformat()
        }
        
        self.save_spending_limits()
        print(f"Set spending limits for {current_month}:")
        print(f"  Soft limit (savings goal): ${soft_limit:,.2f}")
        print(f"  Hard limit (emergency):    ${hard_limit:,.2f}")
    
    def get_current_spending_limits(self):
        """Get spending limits for current month."""
        current_month = datetime.now().strftime('%Y-%m')
        return self.spending_limits.get(current_month, {
            'soft_limit': 0.0,
            'hard_limit': 0.0
        })
    
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
            total_balance = card['current_balance'] + card['balance_due']
            available_credit = card['credit_limit'] - total_balance
            
            print(f"{name}:")
            print(f"  Credit Limit:    ${card['credit_limit']:,.2f}")
            print(f"  Balance Due:     ${card['balance_due']:,.2f}")
            print(f"  New Spending:    ${card['current_balance']:,.2f}")
            print(f"  Total Balance:   ${total_balance:,.2f}")
            print(f"  Available Credit: ${available_credit:,.2f}")
            print(f"  Statement Date:  {card['statement_date']} (day of month)")
            print(f"  Due Date:        {card['due_date']} (day of month)")
            if card['description']:
                print(f"  Description:     {card['description']}")
            print()
    
    def update_balance(self, name, amount, balance_type='current'):
        """Update a card's balance."""
        if name not in self.cards:
            print(f"Card '{name}' not found")
            return
        
        if balance_type == 'current':
            self.cards[name]['current_balance'] = float(amount)
            print(f"Updated {name} current balance to ${amount:,.2f}")
        elif balance_type == 'due':
            self.cards[name]['balance_due'] = float(amount)
            print(f"Updated {name} balance due to ${amount:,.2f}")
        else:
            print("Invalid balance type. Use 'current' or 'due'")
            return
        
        self.cards[name]['last_updated'] = datetime.now().isoformat()
        self.save_cards()
    
    def process_transactions_auto(self, csv_files, card_patterns=None):
        """Automatically process transaction files and update card balances."""
        if not csv_files:
            print("No transaction files provided")
            return
        
        # Default card patterns for auto-detection
        if not card_patterns:
            card_patterns = {
                'chase': ['chase', 'sapphire'],
                'apple': ['apple'],
                'amex': ['amex', 'american express'],
                'citi': ['citi', 'citibank']
            }
        
        # Process each file and try to match to cards
        for file_path in csv_files:
            file_name = Path(file_path).name.lower()
            df = process_csv_file(file_path)
            
            if df.empty:
                print(f"No valid data in {file_path}")
                continue
            
            # Try to match file to a credit card
            matched_card = None
            for card_name in self.cards.keys():
                card_name_lower = card_name.lower()
                
                # Check if any pattern matches
                for pattern_key, patterns in card_patterns.items():
                    if any(pattern in card_name_lower for pattern in patterns):
                        if any(pattern in file_name for pattern in patterns):
                            matched_card = card_name
                            break
                
                # Direct name matching
                if not matched_card and any(word in file_name for word in card_name_lower.split()):
                    matched_card = card_name
                
                if matched_card:
                    break
            
            if not matched_card:
                print(f"Could not auto-match {file_path} to any configured card")
                print("Available cards:", list(self.cards.keys()))
                continue
            
            # Calculate new spending since last statement
            new_spending = abs(df[df['Amount'] < 0]['Amount'].sum())
            
            # Update the card's current balance
            old_balance = self.cards[matched_card]['current_balance']
            self.cards[matched_card]['current_balance'] = new_spending
            self.cards[matched_card]['last_updated'] = datetime.now().isoformat()
            
            print(f"Updated {matched_card}: ${old_balance:,.2f} → ${new_spending:,.2f} (from {len(df)} transactions)")
        
        self.save_cards()
    
    def reset_statement_period(self, card_name=None):
        """Reset current balance to 0 for new statement period."""
        if card_name:
            if card_name not in self.cards:
                print(f"Card '{card_name}' not found")
                return
            cards_to_reset = [card_name]
        else:
            cards_to_reset = list(self.cards.keys())
        
        for name in cards_to_reset:
            # Move current balance to balance_due if needed
            current = self.cards[name]['current_balance']
            if current > 0:
                confirm = input(f"Move ${current:,.2f} from current to balance due for {name}? (y/n): ")
                if confirm.lower() == 'y':
                    self.cards[name]['balance_due'] += current
            
            # Reset current balance
            self.cards[name]['current_balance'] = 0.0
            self.cards[name]['last_statement_reset'] = datetime.now().isoformat()
            print(f"Reset statement period for {name}")
        
        self.save_cards()
    
    def show_summary(self):
        """Display current spending summary for all cards."""
        if not self.cards:
            print("No credit cards configured")
            return
        
        limits = self.get_current_spending_limits()
        current_month = datetime.now().strftime('%B %Y')
        
        print("\n" + "="*50)
        print(f"CREDIT CARD SPENDING SUMMARY - {current_month}")
        print("="*50)
        
        total_new_spending = 0.0
        total_balance_due = 0.0
        total_available = 0.0
        
        for name, card in self.cards.items():
            new_spending = card['current_balance']  # New spending since statement
            balance_due = card['balance_due']  # Previous statement balance
            limit = card['credit_limit']
            total_balance = new_spending + balance_due
            available = limit - total_balance
            
            total_new_spending += new_spending
            total_balance_due += balance_due
            total_available += available
            
            # Format the display - only show new spending
            if new_spending > 0:
                print(f"{name:<15} $ {new_spending:>10,.2f}")
            else:
                print(f"{name:<15} $ {'-':>10}")
        
        print("-" * 30)
        
        # Calculate spending limit status and left to spend
        limits = self.get_current_spending_limits()
        spending_status = ""
        
        if limits['soft_limit'] > 0:
            # Left to spend = soft limit - total new spending
            left_to_spend = limits['soft_limit'] - total_new_spending
            
            # Determine status indicators
            if limits['hard_limit'] > 0 and total_new_spending > limits['hard_limit']:
                spending_status = " 🚨 CRITICAL"
            elif total_new_spending > limits['soft_limit']:
                spending_status = " ⚠️  CAUTION"
        else:
            # No spending limits set, show available credit instead
            left_to_spend = total_available
        
        print(f"{'Left to Spend':<15} $ {left_to_spend:>10,.2f}{spending_status}")
        print("-" * 30)
        print(f"**New Spending  $ {total_new_spending:>10,.2f}**")
        
        if total_balance_due > 0:
            print(f"  Balance Due   $ {total_balance_due:>10,.2f}")
            print(f"  Total Owed    $ {(total_new_spending + total_balance_due):>10,.2f}")
        
        print("="*50)
    
    def show_due_dates(self):
        """Show upcoming due dates with balances."""
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
            total_balance = card['current_balance'] + card['balance_due']
            balance_due = card['balance_due']
            
            due_dates.append((name, due_date, days_until_due, total_balance, balance_due))
        
        # Sort by days until due
        due_dates.sort(key=lambda x: x[2])
        
        print(f"{'Card':<15} {'Due Date':<12} {'Days':<5} {'Balance Due':<12} {'Total Balance':<15} {'Status'}")
        print("-" * 70)
        
        for name, due_date, days_until, total_balance, balance_due in due_dates:
            status = ""
            if days_until <= 3:
                status = "⚠️  URGENT"
            elif days_until <= 7:
                status = "⚡ SOON"
            
            print(f"{name:<15} {due_date.strftime('%Y-%m-%d'):<12} {days_until:>3}d ${balance_due:>9,.2f} ${total_balance:>12,.2f} {status}")
    
    def reset_balances(self, balance_type='current'):
        """Reset card balances."""
        if balance_type == 'current':
            for card in self.cards.values():
                card['current_balance'] = 0.0
                card['last_updated'] = datetime.now().isoformat()
            print("Reset all current balances to $0.00")
        elif balance_type == 'due':
            for card in self.cards.values():
                card['balance_due'] = 0.0
                card['last_updated'] = datetime.now().isoformat()
            print("Reset all due balances to $0.00")
        elif balance_type == 'all':
            for card in self.cards.values():
                card['current_balance'] = 0.0
                card['balance_due'] = 0.0
                card['last_updated'] = datetime.now().isoformat()
            print("Reset all balances to $0.00")
        else:
            print("Invalid balance type. Use 'current', 'due', or 'all'")
            return
        
        self.save_cards()
    
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
            
            # Migrate old format cards that don't have balance_due
            for name, card in self.cards.items():
                if 'balance_due' not in card:
                    card['balance_due'] = 0.0
                if 'last_statement_reset' not in card:
                    card['last_statement_reset'] = datetime.now().isoformat()
            
        except Exception as e:
            print(f"Note: Could not load existing cards ({e}). Starting fresh.")
            self.cards = {}
    
    def save_spending_limits(self):
        """Save spending limits to encrypted file."""
        try:
            json_data = json.dumps(self.spending_limits, indent=2)
            encrypted_data = self.cipher_suite.encrypt(json_data.encode())
            
            with open(self.limits_file, 'wb') as f:
                f.write(encrypted_data)
        except Exception as e:
            print(f"Error saving spending limits: {e}")
    
    def load_spending_limits(self):
        """Load spending limits from encrypted file."""
        try:
            if not Path(self.limits_file).exists():
                return
            
            with open(self.limits_file, 'rb') as f:
                encrypted_data = f.read()
            
            decrypted_data = self.cipher_suite.decrypt(encrypted_data).decode()
            self.spending_limits = json.loads(decrypted_data)
        except Exception as e:
            print(f"Note: Could not load spending limits ({e}). Starting fresh.")
            self.spending_limits = {}

def main():
    """Main function with command line interface."""
    parser = argparse.ArgumentParser(description='Enhanced Credit Card Spending Tracker')
    
    # Card management
    parser.add_argument('--add-card', nargs='+', 
                       help='Add new card: name credit_limit statement_date due_date [balance_due]')
    parser.add_argument('--add-card-desc', help='Description for the card being added')
    parser.add_argument('--update-card', nargs='+', 
                       help='Update card: name [--credit-limit X] [--statement-date X] [--due-date X] [--balance-due X]')
    parser.add_argument('--remove-card', help='Remove a credit card')
    parser.add_argument('--list-cards', action='store_true', help='List all configured cards')
    
    # Balance management
    parser.add_argument('--update-balance', nargs=3, metavar=('NAME', 'AMOUNT', 'TYPE'),
                       help='Update card balance: card_name amount type(current/due)')
    parser.add_argument('--reset', choices=['current', 'due', 'all'], 
                       help='Reset balances: current, due, or all')
    parser.add_argument('--reset-statement', nargs='?', const='all',
                       help='Reset statement period for card (or all cards)')
    
    # Spending limits
    parser.add_argument('--set-limits', nargs=2, metavar=('SOFT', 'HARD'),
                       help='Set monthly spending limits: soft_limit hard_limit')
    
    # Transaction processing
    parser.add_argument('--process-auto', nargs='+', metavar='CSV_FILE',
                       help='Auto-process transaction files to update balances')
    
    # Display
    parser.add_argument('--summary', action='store_true', help='Show spending summary')
    parser.add_argument('--due-dates', action='store_true', help='Show upcoming due dates')
    
    args = parser.parse_args()
    tracker = CreditCardTracker()
    
    if args.add_card:
        if len(args.add_card) < 4:
            print("Error: --add-card requires name, credit_limit, statement_date, due_date")
            return
        
        name, limit, stmt_date, due_date = args.add_card[:4]
        balance_due = float(args.add_card[4]) if len(args.add_card) > 4 else 0.0
        description = args.add_card_desc or ""
        tracker.add_card(name, limit, stmt_date, due_date, description, balance_due)
    
    elif args.update_card:
        if len(args.update_card) < 2:
            print("Error: --update-card requires at least card name and one field to update")
            return
        
        name = args.update_card[0]
        update_args = args.update_card[1:]
        
        # Parse update arguments
        kwargs = {}
        i = 0
        while i < len(update_args):
            if update_args[i] == '--credit-limit' and i + 1 < len(update_args):
                kwargs['credit_limit'] = update_args[i + 1]
                i += 2
            elif update_args[i] == '--statement-date' and i + 1 < len(update_args):
                kwargs['statement_date'] = update_args[i + 1]
                i += 2
            elif update_args[i] == '--due-date' and i + 1 < len(update_args):
                kwargs['due_date'] = update_args[i + 1]
                i += 2
            elif update_args[i] == '--balance-due' and i + 1 < len(update_args):
                kwargs['balance_due'] = update_args[i + 1]
                i += 2
            elif update_args[i] == '--description' and i + 1 < len(update_args):
                kwargs['description'] = update_args[i + 1]
                i += 2
            else:
                i += 1
        
        tracker.update_card(name, **kwargs)
    
    elif args.remove_card:
        tracker.remove_card(args.remove_card)
    
    elif args.list_cards:
        tracker.list_cards()
    
    elif args.update_balance:
        name, amount, balance_type = args.update_balance
        tracker.update_balance(name, float(amount), balance_type)
    
    elif args.set_limits:
        soft_limit, hard_limit = args.set_limits
        tracker.set_spending_limits(float(soft_limit), float(hard_limit))
    
    elif args.process_auto:
        tracker.process_transactions_auto(args.process_auto)
    
    elif args.due_dates:
        tracker.show_due_dates()
    
    elif args.reset:
        confirm = input(f"Are you sure you want to reset {args.reset} balances? (yes/no): ")
        if confirm.lower() == 'yes':
            tracker.reset_balances(args.reset)
        else:
            print("Reset cancelled")
    
    elif args.reset_statement:
        if args.reset_statement == 'all':
            tracker.reset_statement_period()
        else:
            tracker.reset_statement_period(args.reset_statement)
    
    elif args.summary:
        tracker.show_summary()
    
    else:
        # Default: show summary
        tracker.show_summary()

if __name__ == "__main__":
    main()