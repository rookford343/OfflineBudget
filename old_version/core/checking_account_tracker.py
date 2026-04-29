#!/usr/bin/env python3
"""
Clean Checking Account Tracker - Working Version
Handles Chase CSV format properly
"""
import json
import pandas as pd
import keyring
import argparse
import sys
import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from cryptography.fernet import Fernet

class CheckingAccountTracker:
    def __init__(self):
        self.checking_accounts = {}
        self.transactions = {}
        
        # Setup paths and encryption
        data_dir = self._get_data_directory()
        self.accounts_file = os.path.join(data_dir, 'checking_accounts.enc')
        self.transactions_file = os.path.join(data_dir, 'checking_transactions.enc')
        self.cipher_suite = self._setup_encryption()
        
        # Load existing data
        self.load_accounts()
        self.load_transactions()
    
    def _get_data_directory(self):
        current_file = Path(__file__)
        if current_file.parent.name == 'core':
            project_root = current_file.parent.parent
        else:
            project_root = current_file.parent
        
        data_dir = project_root / 'data'
        data_dir.mkdir(exist_ok=True)
        return str(data_dir)
    
    def _setup_encryption(self):
        encryption_key = keyring.get_password("checking_account_tracker", "encryption_key")
        if not encryption_key:
            key = Fernet.generate_key()
            keyring.set_password("checking_account_tracker", "encryption_key", key.decode())
            encryption_key = key.decode()
        return Fernet(encryption_key.encode())
    
    def add_account(self, name, current_balance, bank_name="", account_type="checking", description=""):
        if name in self.checking_accounts:
            print(f"❌ Account '{name}' already exists")
            return False
        
        self.checking_accounts[name] = {
            'current_balance': float(current_balance),
            'bank_name': bank_name,
            'account_type': account_type,
            'description': description,
            'created_date': datetime.now().isoformat(),
            'last_updated': datetime.now().isoformat()
        }
        
        self.save_accounts()
        print(f"✅ Added checking account: {name}")
        print(f"   Balance: ${current_balance:,.2f}")
        if bank_name:
            print(f"   Bank: {bank_name}")
        return True
    
    def list_accounts(self):
        if not self.checking_accounts:
            print("No checking accounts found")
            return
        
        print("\n=== CHECKING ACCOUNTS ===")
        total_balance = 0
        
        for name, account in self.checking_accounts.items():
            balance = account['current_balance']
            total_balance += balance
            
            print(f"\n{name}:")
            print(f"  Balance: ${balance:,.2f}")
            if account['bank_name']:
                print(f"  Bank: {account['bank_name']}")
            if account['description']:
                print(f"  Description: {account['description']}")
            print(f"  Type: {account['account_type'].title()}")
        
        print(f"\n💰 Total Balance: ${total_balance:,.2f}")
    
    def analyze_csv_structure(self, csv_file_path):
        try:
            print(f"🔍 ANALYZING CSV STRUCTURE: {csv_file_path}")
            print("=" * 60)
            
            # Try different encodings
            df = None
            for encoding in ['utf-8', 'latin-1', 'cp1252']:
                try:
                    df = pd.read_csv(csv_file_path, encoding=encoding)
                    print(f"✅ Successfully read with {encoding} encoding")
                    break
                except:
                    continue
            
            if df is None:
                print("❌ Could not read CSV")
                return None
            
            print(f"\n📊 BASIC INFO:")
            print(f"   Total rows: {len(df)}")
            print(f"   Total columns: {len(df.columns)}")
            
            print(f"\n📋 COLUMN NAMES:")
            for i, col in enumerate(df.columns):
                print(f"   {i+1}. '{col}'")
            
            print(f"\n📊 FIRST 3 ROWS:")
            for i, (idx, row) in enumerate(df.head(3).iterrows()):
                print(f"   Row {i+1}: {dict(row)}")
            
            return df
            
        except Exception as e:
            print(f"❌ Error analyzing CSV: {e}")
            return None
    
    def process_csv_file(self, csv_file_path, account_name):
        if account_name not in self.checking_accounts:
            print(f"❌ Account '{account_name}' not found")
            return False
        
        try:
            # Read CSV
            df = None
            for encoding in ['utf-8', 'latin-1', 'cp1252']:
                try:
                    df = pd.read_csv(csv_file_path, encoding=encoding)
                    print(f"✅ Successfully read CSV with {encoding} encoding")
                    break
                except:
                    continue
            
            if df is None:
                print("❌ Could not read CSV file")
                return False
            
            print(f"📊 Loaded {len(df)} rows from CSV")
            
            # Convert to standard format
            df = self._convert_chase_csv(df)
            
            if df.empty:
                print("❌ No valid transactions found")
                return False
            
            # Process transactions
            processed_count = self._add_transactions(df, account_name)
            
            if processed_count > 0:
                print(f"✅ Processed {processed_count} transactions")
                
                # Calculate balance change
                total_change = df['Amount'].sum()
                print(f"   Net change: ${total_change:,.2f}")
                
                # Ask to update balance
                current_balance = self.checking_accounts[account_name]['current_balance']
                new_balance = current_balance + total_change
                
                update = input(f"Update {account_name} balance to ${new_balance:,.2f}? (y/n): ")
                if update.lower() == 'y':
                    self.checking_accounts[account_name]['current_balance'] = new_balance
                    self.checking_accounts[account_name]['last_updated'] = datetime.now().isoformat()
                    self.save_accounts()
                    print(f"✅ Updated balance to ${new_balance:,.2f}")
                
                return True
            else:
                print("❌ No transactions were processed")
                return False
                
        except Exception as e:
            print(f"❌ Error processing CSV: {e}")
            return False
    
    def _convert_chase_csv(self, df):
        print("🔄 Converting Chase CSV format...")
        
        # Check if this looks like the mixed Chase format
        expected_cols = ['Details', 'Posting Date', 'Description', 'Amount', 'Type']
        if not all(col in df.columns for col in expected_cols):
            print("❌ Not recognized as Chase format")
            return pd.DataFrame()
        
        # Check if Details contains dates (indicating mixed format)
        if len(df) > 0:
            sample_details = str(df['Details'].iloc[0])
            if not re.search(r'\d{2}/\d{2}/\d{4}', sample_details):
                print("❌ Details column doesn't contain dates")
                return pd.DataFrame()
        
        print("🏦 Detected Chase mixed column format")
        
        # Fix the mixed columns:
        # Details -> Transaction Date
        # Posting Date -> Description  
        # Description -> Amount
        # Amount -> Category
        
        standardized_df = pd.DataFrame()
        standardized_df['Transaction Date'] = df['Details']
        standardized_df['Description'] = df['Posting Date']
        standardized_df['Amount'] = pd.to_numeric(df['Description'], errors='coerce')
        standardized_df['Category'] = df['Amount'].fillna('')
        
        # Clean up data
        standardized_df = standardized_df.dropna(subset=['Amount'])
        standardized_df = standardized_df[standardized_df['Amount'] != 0]
        standardized_df = standardized_df[standardized_df['Description'].str.strip() != '']
        
        # Filter for valid dates
        date_pattern = r'\d{2}/\d{2}/\d{4}'
        standardized_df = standardized_df[
            standardized_df['Transaction Date'].str.contains(date_pattern, na=False)
        ]
        
        print(f"✅ Converted {len(standardized_df)} valid transactions")
        
        # Show samples
        if len(standardized_df) > 0:
            print("📊 Sample transactions:")
            for i, (idx, row) in enumerate(standardized_df.head(3).iterrows()):
                desc = row['Description'][:50] + "..." if len(row['Description']) > 50 else row['Description']
                print(f"   {i+1}. {row['Transaction Date']} | {desc} | ${row['Amount']:,.2f}")
        
        return standardized_df
    
    def _add_transactions(self, df, account_name):
        current_month = datetime.now().strftime('%Y-%m')
        
        if current_month not in self.transactions:
            self.transactions[current_month] = {}
        
        if account_name not in self.transactions[current_month]:
            self.transactions[current_month][account_name] = []
        
        processed_count = 0
        
        for _, row in df.iterrows():
            try:
                transaction = {
                    'date': str(row.get('Transaction Date', '')),
                    'description': str(row.get('Description', '')),
                    'amount': float(row.get('Amount', 0)),
                    'category': str(row.get('Category', '')),
                    'imported_date': datetime.now().isoformat()
                }
                
                self.transactions[current_month][account_name].append(transaction)
                processed_count += 1
                
            except Exception as e:
                print(f"⚠️ Error processing transaction: {e}")
                continue
        
        if processed_count > 0:
            self.save_transactions()
        
        return processed_count
    
    def pay_credit_card(self, account_name, credit_card_name, amount):
        if account_name not in self.checking_accounts:
            print(f"❌ Account '{account_name}' not found")
            return False
        
        amount = float(amount)
        current_balance = self.checking_accounts[account_name]['current_balance']
        
        if current_balance < amount:
            print(f"❌ Insufficient funds")
            print(f"   Available: ${current_balance:,.2f}")
            print(f"   Required: ${amount:,.2f}")
            return False
        
        # Process payment
        new_balance = current_balance - amount
        
        # Record transaction
        current_month = datetime.now().strftime('%Y-%m')
        if current_month not in self.transactions:
            self.transactions[current_month] = {}
        if account_name not in self.transactions[current_month]:
            self.transactions[current_month][account_name] = []
        
        payment_transaction = {
            'date': datetime.now().strftime('%Y-%m-%d'),
            'description': f'Credit Card Payment - {credit_card_name}',
            'amount': -amount,
            'category': 'Credit Card Payment',
            'imported_date': datetime.now().isoformat()
        }
        
        self.transactions[current_month][account_name].append(payment_transaction)
        
        # Update balance
        self.checking_accounts[account_name]['current_balance'] = new_balance
        self.checking_accounts[account_name]['last_updated'] = datetime.now().isoformat()
        self.save_accounts()
        self.save_transactions()
        
        print(f"✅ Credit card payment processed")
        print(f"   Paid: ${amount:,.2f} to {credit_card_name}")
        print(f"   New balance: ${new_balance:,.2f}")
        
        return True
    
    def show_summary(self, account_name=None):
        if account_name and account_name not in self.checking_accounts:
            print(f"❌ Account '{account_name}' not found")
            return
        
        print(f"\n=== TRANSACTION SUMMARY ===")
        
        accounts_to_check = [account_name] if account_name else list(self.checking_accounts.keys())
        current_month = datetime.now().strftime('%Y-%m')
        
        for acc_name in accounts_to_check:
            print(f"\n📊 {acc_name}:")
            
            total_income = 0
            total_expenses = 0
            transaction_count = 0
            
            if current_month in self.transactions and acc_name in self.transactions[current_month]:
                for transaction in self.transactions[current_month][acc_name]:
                    amount = transaction['amount']
                    transaction_count += 1
                    
                    if amount > 0:
                        total_income += amount
                    else:
                        total_expenses += abs(amount)
            
            net_change = total_income - total_expenses
            current_balance = self.checking_accounts[acc_name]['current_balance']
            
            print(f"   Transactions: {transaction_count}")
            print(f"   Income: ${total_income:,.2f}")
            print(f"   Expenses: ${total_expenses:,.2f}")
            print(f"   Net Change: ${net_change:+,.2f}")
            print(f"   Current Balance: ${current_balance:,.2f}")
    
    def save_accounts(self):
        try:
            json_data = json.dumps(self.checking_accounts, indent=2, default=str)
            encrypted_data = self.cipher_suite.encrypt(json_data.encode())
            with open(self.accounts_file, 'wb') as f:
                f.write(encrypted_data)
        except Exception as e:
            print(f"Error saving accounts: {e}")
    
    def load_accounts(self):
        try:
            if not Path(self.accounts_file).exists():
                return
            with open(self.accounts_file, 'rb') as f:
                encrypted_data = f.read()
            decrypted_data = self.cipher_suite.decrypt(encrypted_data).decode()
            self.checking_accounts = json.loads(decrypted_data)
        except Exception as e:
            print(f"Note: Could not load accounts ({e}). Starting fresh.")
            self.checking_accounts = {}
    
    def save_transactions(self):
        try:
            json_data = json.dumps(self.transactions, indent=2, default=str)
            encrypted_data = self.cipher_suite.encrypt(json_data.encode())
            with open(self.transactions_file, 'wb') as f:
                f.write(encrypted_data)
        except Exception as e:
            print(f"Error saving transactions: {e}")
    
    def load_transactions(self):
        try:
            if not Path(self.transactions_file).exists():
                return
            with open(self.transactions_file, 'rb') as f:
                encrypted_data = f.read()
            decrypted_data = self.cipher_suite.decrypt(encrypted_data).decode()
            self.transactions = json.loads(decrypted_data)
        except Exception as e:
            print(f"Note: Could not load transactions ({e}). Starting fresh.")
            self.transactions = {}

def main():
    parser = argparse.ArgumentParser(description='Checking Account Tracker')
    
    # Commands
    parser.add_argument('--add-account', nargs='+', help='Add account: name balance [bank] [description]')
    parser.add_argument('--list-accounts', action='store_true', help='List all accounts')
    parser.add_argument('--analyze-csv', help='Analyze CSV structure: csv_file')
    parser.add_argument('--process-csv', nargs=2, help='Process CSV: csv_file account_name')
    parser.add_argument('--pay-credit-card', nargs=3, help='Pay credit card: account_name card_name amount')
    parser.add_argument('--summary', nargs='?', const=None, help='Show summary [account_name]')
    
    args = parser.parse_args()
    tracker = CheckingAccountTracker()
    
    if args.add_account:
        name, balance = args.add_account[:2]
        bank = args.add_account[2] if len(args.add_account) > 2 else ""
        desc = args.add_account[3] if len(args.add_account) > 3 else ""
        tracker.add_account(name, balance, bank, description=desc)
    
    elif args.list_accounts:
        tracker.list_accounts()
    
    elif args.analyze_csv:
        tracker.analyze_csv_structure(args.analyze_csv)
    
    elif args.process_csv:
        csv_file, account_name = args.process_csv
        tracker.process_csv_file(csv_file, account_name)
    
    elif args.pay_credit_card:
        account_name, card_name, amount = args.pay_credit_card
        tracker.pay_credit_card(account_name, card_name, float(amount))
    
    elif args.summary is not None:
        account_name = args.summary if args.summary else None
        tracker.show_summary(account_name)
    
    else:
        tracker.list_accounts()

if __name__ == "__main__":
    main()