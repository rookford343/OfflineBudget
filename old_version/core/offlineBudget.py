#!/usr/bin/env python3
"""
Unified Budget Tracker
A comprehensive, secure budget management tool combining:
- Checking account tracking
- Credit card management
- Transaction processing with categorization
- Time period analysis and trend reporting
- Budget recommendations based on spending patterns
- Encrypted data storage

Security Features:
- All sensitive data encrypted at rest using Fernet encryption
- Encryption keys stored in system keyring
- Separate encryption contexts for different data types
"""

import json
import pandas as pd
import numpy as np
import keyring
import argparse
import sys
import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from cryptography.fernet import Fernet
from collections import defaultdict
import calendar
import warnings
warnings.filterwarnings('ignore')


# ============================================================================
# CORE ENCRYPTION & SECURITY
# ============================================================================

class SecureStorage:
    """Centralized secure storage with encryption."""
    
    def __init__(self, app_name="unified_budget_tracker", data_dir=None):
        self.app_name = app_name
        self.data_dir = data_dir
        self.cipher_suite = self._setup_encryption()
    
    def _setup_encryption(self):
        """Setup encryption using secret.key file or system keyring."""
        # First, check for existing secret.key file in data directory
        if self.data_dir:
            secret_key_file = os.path.join(self.data_dir, 'secret.key')
            if os.path.exists(secret_key_file):
                try:
                    with open(secret_key_file, 'rb') as f:
                        key = f.read()
                    return Fernet(key)
                except Exception as e:
                    print(f"Warning: Could not read secret.key file: {e}")
        
        # Fallback to keyring
        encryption_key = keyring.get_password(self.app_name, "encryption_key")
        if not encryption_key:
            key = Fernet.generate_key()
            keyring.set_password(self.app_name, "encryption_key", key.decode())
            encryption_key = key.decode()
        return Fernet(encryption_key.encode())
    
    def save_encrypted(self, data, filepath):
        """Save data with encryption."""
        try:
            json_data = json.dumps(data, indent=2, default=str)
            encrypted_data = self.cipher_suite.encrypt(json_data.encode())
            with open(filepath, 'wb') as f:
                f.write(encrypted_data)
            return True
        except Exception as e:
            print(f"Error saving encrypted data to {filepath}: {e}")
            return False
    
    def load_encrypted(self, filepath):
        """Load encrypted data."""
        try:
            if not Path(filepath).exists():
                return None
            with open(filepath, 'rb') as f:
                encrypted_data = f.read()
            decrypted_data = self.cipher_suite.decrypt(encrypted_data).decode()
            return json.loads(decrypted_data)
        except Exception as e:
            print(f"Could not load encrypted data from {filepath}: {e}")
            return None


# ============================================================================
# TRANSACTION CATEGORIZATION & MERCHANT CLEANING
# ============================================================================

class TransactionCategorizer:
    """Handles transaction categorization and merchant name cleaning."""
    
    # Standard categories used throughout the system
    CATEGORIES = ['Shopping', 'Food & Drinks', 'Services', 'Entertainment', 'Groceries', 'Other']
    
    @staticmethod
    def clean_merchant_name(description):
        """Clean merchant names by removing store numbers and extra data."""
        if not description or pd.isna(description):
            return "UNKNOWN MERCHANT"
        
        description = str(description).upper().strip()
        
        # Special handling for common merchants
        merchant_patterns = {
            'AMAZON': lambda d: d.startswith('AMAZON'),
            'COSTCO': lambda d: d.startswith('COSTCO'),
            'TARGET': lambda d: d.startswith('TARGET'),
            'WALMART': lambda d: d.startswith('WALMART') or d.startswith('WAL-MART'),
            'STARBUCKS': lambda d: d.startswith('STARBUCKS'),
            'MCDONALDS': lambda d: 'MCDONALD' in d,
            'CVS': lambda d: d.startswith('CVS'),
            'HOME DEPOT': lambda d: 'HOME DEPOT' in d,
            'CHIPOTLE': lambda d: 'CHIPOTLE' in d,
            'SHELL': lambda d: d.startswith('SHELL'),
            'CHASE': lambda d: 'CHASE CREDIT' in d or 'CHASE AUTO' in d,
        }
        
        for merchant, pattern in merchant_patterns.items():
            if pattern(description):
                return merchant
        
        # Generic cleaning
        if '*' in description:
            description = description.split('*')[0].strip()
        if '#' in description and not description.startswith('#'):
            description = description.split('#')[0].strip()
        
        # Remove common suffixes
        suffixes = [' STORE', ' WHSE', ' GAS', ' SUPERCENTER', ' WHOLESALE',
                   ' PHARMACY', ' COFFEE', ' MEXICAN GRILL', ' SERVICE STATION',
                   ' INC', ' LLC', ' CORP', ' CO']
        
        for suffix in suffixes:
            if description.endswith(suffix):
                description = description[:-len(suffix)].strip()
        
        # Clean trailing numbers and special characters
        description = re.sub(r'\s+\d+$', '', description)
        description = re.sub(r'[^A-Za-z\s&\'-]', ' ', description)
        description = re.sub(r'\s+', ' ', description).strip()
        
        return description or "UNKNOWN MERCHANT"
    
    @staticmethod
    def categorize_transaction(description='', memo='', original_category=''):
        """Categorize transaction based on keywords and original category."""
        # Handle NaN values
        description = '' if pd.isna(description) else str(description)
        memo = '' if pd.isna(memo) else str(memo)
        original_category = '' if pd.isna(original_category) else str(original_category)
        
        # Check original category first
        if original_category.strip():
            category_mapping = {
                'shopping': 'Shopping', 'merchandise': 'Shopping', 'retail': 'Shopping',
                'health & wellness': 'Services', 'healthcare': 'Services',
                'professional services': 'Services', 'bills & utilities': 'Services',
                'restaurants': 'Food & Drinks', 'fast food': 'Food & Drinks',
                'coffee shops': 'Food & Drinks', 'dining': 'Food & Drinks',
                'supermarkets': 'Groceries', 'grocery stores': 'Groceries',
                'travel': 'Entertainment', 'recreation': 'Entertainment',
                'entertainment': 'Entertainment'
            }
            
            original_lower = original_category.lower()
            if original_category in TransactionCategorizer.CATEGORIES:
                return original_category
            
            for bank_variant, our_category in category_mapping.items():
                if bank_variant in original_lower:
                    return our_category
        
        # Fallback to keyword matching
        text = f"{description} {memo}".lower()
        
        keywords = {
            'Shopping': ['amazon', 'walmart', 'target', 'costco', 'home depot', 'lowes',
                        'best buy', 'macys', 'nordstrom', 'tjmaxx', 'marshalls', 'kohls',
                        'cvs', 'walgreens', 'pharmacy', 'shopping', 'retail', 'store'],
            'Food & Drinks': ['mcdonalds', 'burger king', 'subway', 'starbucks', 'dunkin',
                             'chipotle', 'panera', 'restaurant', 'cafe', 'pizza', 'coffee',
                             'doordash', 'uber eats', 'grubhub', 'dining'],
            'Services': ['bank', 'atm', 'fee', 'insurance', 'medical', 'dental', 'doctor',
                        'gym', 'fitness', 'subscription', 'netflix', 'spotify', 'internet',
                        'utility', 'electric', 'gas', 'water'],
            'Entertainment': ['movie', 'theater', 'concert', 'ticket', 'amusement', 'zoo',
                            'museum', 'sports', 'bowling', 'golf', 'gaming', 'vacation',
                            'travel', 'hotel', 'airline'],
            'Groceries': ['grocery', 'supermarket', 'kroger', 'safeway', 'publix',
                         'whole foods', 'trader joes', 'aldi', 'market', 'produce']
        }
        
        for category, terms in keywords.items():
            if any(term in text for term in terms):
                return category
        
        return 'Other'


# ============================================================================
# CSV PROCESSING
# ============================================================================

class CSVProcessor:
    """Handles CSV file processing with multiple format support."""
    
    @staticmethod
    def read_csv_robust(file_path):
        """Read CSV with multiple encoding attempts and Chase-specific fixes."""
        encodings = ['utf-8', 'latin-1', 'cp1252']
        
        for encoding in encodings:
            try:
                # First, try reading normally
                df = pd.read_csv(file_path, encoding=encoding)
                
                # Check for Chase checking account format with header mismatch
                # This happens when the CSV has trailing commas causing column shift
                if 'Details' in df.columns and 'Posting Date' in df.columns:
                    # Check if first row of Details looks like a date (MM/DD/YYYY)
                    if len(df) > 0 and isinstance(df['Details'].iloc[0], str):
                        if re.match(r'\d{2}/\d{2}/\d{4}', str(df['Details'].iloc[0])):
                            # This is the shifted format - need to fix it
                            print("  Detected Chase CSV with column shift - fixing...")
                            
                            # Re-read with correct column names
                            df = pd.read_csv(file_path, encoding=encoding,
                                           names=['Details', 'Transaction Date', 'Description', 
                                                  'Amount', 'Type', 'Balance', 'Check', 'Extra'],
                                           skiprows=1)  # Skip the incorrect header
                            
                            # Drop the extra empty column
                            if 'Extra' in df.columns:
                                df = df.drop('Extra', axis=1)
                
                return df
                
            except (UnicodeDecodeError, Exception):
                continue
        
        raise Exception(f"Could not decode {file_path} with any standard encoding")
    
    @staticmethod
    def detect_and_convert_format(df):
        """Detect CSV format and convert to standard format."""
        # Standard columns we expect
        expected = ['Transaction Date', 'Description', 'Amount']
        
        # Check if it's already in standard format
        if all(col in df.columns for col in expected):
            return CSVProcessor._standardize_dataframe(df)
        
        # Check for Chase checking account format (Details, Posting Date, Description, Amount, Type, Balance)
        chase_checking_cols = ['Details', 'Posting Date', 'Description', 'Amount', 'Type']
        if all(col in df.columns for col in chase_checking_cols):
            return CSVProcessor._convert_chase_checking_format(df)
        
        # Check for Chase credit card mixed format (Details with dates)
        chase_cc_cols = ['Details', 'Posting Date', 'Description', 'Amount', 'Type']
        if all(col in df.columns for col in chase_cc_cols):
            # Check if Details contains dates (credit card format)
            if len(df) > 0:
                sample_details = str(df['Details'].iloc[0])
                if re.search(r'\d{2}/\d{2}/\d{4}', sample_details):
                    return CSVProcessor._convert_chase_cc_format(df)
        
        # Check for Citi/other debit-credit format
        if 'Debit' in df.columns and 'Credit' in df.columns:
            return CSVProcessor._convert_debit_credit_format(df)
        
        # Try to auto-detect
        return CSVProcessor._auto_detect_format(df)
    
    @staticmethod
    def _convert_chase_checking_format(df):
        """Convert Chase checking account format (Details contains DEBIT/CREDIT/etc)."""
        if len(df) == 0:
            return pd.DataFrame()
        
        # For Chase checking, after our fix, the format is:
        # Details = DEBIT/CREDIT/DSLIP/CHECK
        # Transaction Date = actual date (or Posting Date in original)
        # Description = merchant
        # Amount = amount (already signed correctly)
        
        # Check which date column we have
        date_col = 'Transaction Date' if 'Transaction Date' in df.columns else 'Posting Date'
        
        standardized = pd.DataFrame({
            'Transaction Date': df[date_col],
            'Description': df['Description'],
            'Amount': df['Amount'],
            'Category': df.get('Type', ''),
            'Memo': df.get('Details', '')
        })
        
        return CSVProcessor._standardize_dataframe(standardized)
    
    @staticmethod
    def _convert_chase_cc_format(df):
        """Convert Chase credit card format (Details contains dates)."""
        if len(df) == 0:
            return pd.DataFrame()
        
        # Extract transaction date from Details column
        df['Transaction Date'] = df['Details'].str.extract(r'(\d{2}/\d{2}/\d{4})')
        
        # Keep Description and Amount as-is
        standardized = pd.DataFrame({
            'Transaction Date': df['Transaction Date'],
            'Description': df['Description'],
            'Amount': df['Amount'],
            'Category': df.get('Type', ''),
            'Memo': ''
        })
        
        return CSVProcessor._standardize_dataframe(standardized)
    
    @staticmethod
    def _convert_debit_credit_format(df):
        """Convert debit/credit column format to single Amount column."""
        # Combine Debit (negative) and Credit (positive) into Amount
        df['Amount'] = df.get('Credit', 0).fillna(0) - df.get('Debit', 0).fillna(0)
        
        standardized = pd.DataFrame({
            'Transaction Date': df.get('Transaction Date', df.get('Date', df.get('Posting Date', ''))),
            'Description': df.get('Description', df.get('Merchant', '')),
            'Amount': df['Amount'],
            'Category': df.get('Category', ''),
            'Memo': df.get('Memo', '')
        })
        
        return CSVProcessor._standardize_dataframe(standardized)
    
    @staticmethod
    def _auto_detect_format(df):
        """Attempt to auto-detect and standardize format."""
        # Look for date column
        date_col = None
        for col in df.columns:
            if 'date' in col.lower():
                date_col = col
                break
        
        # Look for description column
        desc_col = None
        for col in df.columns:
            if any(term in col.lower() for term in ['description', 'merchant', 'name']):
                desc_col = col
                break
        
        # Look for amount column
        amount_col = None
        for col in df.columns:
            if 'amount' in col.lower():
                amount_col = col
                break
        
        if not all([date_col, desc_col, amount_col]):
            print("Warning: Could not auto-detect CSV format")
            return pd.DataFrame()
        
        standardized = pd.DataFrame({
            'Transaction Date': df[date_col],
            'Description': df[desc_col],
            'Amount': df[amount_col],
            'Category': df.get('Category', ''),
            'Memo': df.get('Memo', '')
        })
        
        return CSVProcessor._standardize_dataframe(standardized)
    
    @staticmethod
    def _standardize_dataframe(df):
        """Clean and standardize a dataframe."""
        # Clean amount field
        if 'Amount' in df.columns:
            df['Amount'] = df['Amount'].astype(str).str.replace(r'[\$,]', '', regex=True)
            df['Amount'] = pd.to_numeric(df['Amount'], errors='coerce')
        
        # Remove empty rows
        df = df.dropna(subset=['Amount'])
        
        # Parse and sort by date
        if 'Transaction Date' in df.columns:
            try:
                df['parsed_date'] = pd.to_datetime(df['Transaction Date'], errors='coerce')
                df = df.dropna(subset=['parsed_date'])
                df = df.sort_values('parsed_date', ascending=False)
                df = df.drop('parsed_date', axis=1)
            except:
                pass
        
        return df


# ============================================================================
# ACCOUNT MANAGEMENT
# ============================================================================

class AccountManager:
    """Manages checking accounts and credit cards."""
    
    def __init__(self, storage):
        self.storage = storage
        self.checking_accounts = {}
        self.credit_cards = {}
        self.category_budgets = {}
        self.spending_limits = {'soft_limit': None, 'hard_limit': None}
    
    def add_checking_account(self, name, balance, bank_name="", description=""):
        """Add a new checking account."""
        if name in self.checking_accounts:
            return False, f"Account '{name}' already exists"
        
        self.checking_accounts[name] = {
            'current_balance': float(balance),
            'bank_name': bank_name,
            'description': description,
            'created_date': datetime.now().isoformat(),
            'last_updated': datetime.now().isoformat()
        }
        
        return True, f"Added checking account: {name}"
    
    def add_credit_card(self, name, credit_limit, statement_date, due_date,
                       description="", balance_due=0.0, current_balance=0.0):
        """Add a new credit card."""
        if name in self.credit_cards:
            return False, f"Card '{name}' already exists"
        
        self.credit_cards[name] = {
            'credit_limit': float(credit_limit),
            'statement_date': int(statement_date),
            'due_date': int(due_date),
            'description': description,
            'balance_due': float(balance_due),
            'current_balance': float(current_balance),
            'created_date': datetime.now().isoformat(),
            'last_updated': datetime.now().isoformat()
        }
        
        return True, f"Added credit card: {name}"
    
    def update_account_balance(self, account_name, new_balance):
        """Update checking account balance."""
        if account_name not in self.checking_accounts:
            return False, f"Account '{account_name}' not found"
        
        old_balance = self.checking_accounts[account_name]['current_balance']
        self.checking_accounts[account_name]['current_balance'] = float(new_balance)
        self.checking_accounts[account_name]['last_updated'] = datetime.now().isoformat()
        
        return True, f"Updated {account_name}: ${old_balance:,.2f} → ${new_balance:,.2f}"
    
    def update_card_balance(self, card_name, amount, balance_type='current'):
        """Update credit card balance."""
        if card_name not in self.credit_cards:
            return False, f"Card '{card_name}' not found"
        
        if balance_type == 'current':
            self.credit_cards[card_name]['current_balance'] = float(amount)
        elif balance_type == 'due':
            self.credit_cards[card_name]['balance_due'] = float(amount)
        
        self.credit_cards[card_name]['last_updated'] = datetime.now().isoformat()
        return True, f"Updated {card_name} {balance_type} balance to ${amount:,.2f}"
    
    def get_total_checking_balance(self):
        """Calculate total across all checking accounts."""
        return sum(acc['current_balance'] for acc in self.checking_accounts.values())
    
    def get_total_credit_available(self):
        """Calculate total available credit."""
        return sum(
            card['credit_limit'] - card['current_balance']
            for card in self.credit_cards.values()
        )
    
    def get_total_credit_used(self):
        """Calculate total credit used."""
        return sum(card['current_balance'] for card in self.credit_cards.values())


# ============================================================================
# TRANSACTION MANAGER
# ============================================================================

class TransactionManager:
    """Manages transaction data and analysis."""
    
    def __init__(self, storage, categorizer):
        self.storage = storage
        self.categorizer = categorizer
        self.transactions = {}  # month -> account -> [transactions]
        self.category_spending = {}  # month -> category -> amount
    
    def add_transactions_from_df(self, df, account_name):
        """Add transactions from a DataFrame."""
        if df.empty:
            return 0
        
        # Add categorization
        df['custom_category'] = df.apply(
            lambda row: self.categorizer.categorize_transaction(
                row.get('Description', ''),
                row.get('Memo', ''),
                row.get('Category', '')
            ), axis=1
        )
        
        # Add cleaned merchant names
        df['clean_merchant'] = df['Description'].apply(
            self.categorizer.clean_merchant_name
        )
        
        # Group by month
        df['parsed_date'] = pd.to_datetime(df['Transaction Date'], errors='coerce')
        df = df.dropna(subset=['parsed_date'])
        
        count = 0
        for _, row in df.iterrows():
            month_key = row['parsed_date'].strftime('%Y-%m')
            
            if month_key not in self.transactions:
                self.transactions[month_key] = {}
            if account_name not in self.transactions[month_key]:
                self.transactions[month_key][account_name] = []
            
            transaction = {
                'date': row['parsed_date'].strftime('%Y-%m-%d'),
                'description': str(row.get('Description', '')),
                'clean_merchant': str(row.get('clean_merchant', '')),
                'amount': float(row.get('Amount', 0)),
                'category': str(row.get('custom_category', 'Other')),
                'original_category': str(row.get('Category', '')),
                'imported_date': datetime.now().isoformat()
            }
            
            self.transactions[month_key][account_name].append(transaction)
            count += 1
        
        # Update category spending
        self._update_category_spending(df)
        
        return count
    
    def _update_category_spending(self, df):
        """Update category spending totals."""
        if 'parsed_date' not in df.columns:
            df['parsed_date'] = pd.to_datetime(df['Transaction Date'], errors='coerce')
        
        df = df.dropna(subset=['parsed_date'])
        
        for _, row in df.iterrows():
            month_key = row['parsed_date'].strftime('%Y-%m')
            category = row.get('custom_category', 'Other')
            amount = abs(float(row.get('Amount', 0)))
            
            if month_key not in self.category_spending:
                self.category_spending[month_key] = {}
            
            if category not in self.category_spending[month_key]:
                self.category_spending[month_key][category] = 0.0
            
            self.category_spending[month_key][category] += amount
    
    def get_monthly_summary(self, month=None):
        """Get transaction summary for a specific month."""
        if month is None:
            month = datetime.now().strftime('%Y-%m')
        
        if month not in self.transactions:
            return {
                'total_income': 0,
                'total_expenses': 0,
                'net_change': 0,
                'transaction_count': 0,
                'by_category': {}
            }
        
        total_income = 0
        total_expenses = 0
        by_category = defaultdict(float)
        count = 0
        
        for account_transactions in self.transactions[month].values():
            for txn in account_transactions:
                amount = txn['amount']
                count += 1
                
                if amount > 0:
                    total_income += amount
                else:
                    total_expenses += abs(amount)
                    by_category[txn['category']] += abs(amount)
        
        return {
            'total_income': total_income,
            'total_expenses': total_expenses,
            'net_change': total_income - total_expenses,
            'transaction_count': count,
            'by_category': dict(by_category)
        }
    
    def get_all_transactions_df(self):
        """Get all transactions as a DataFrame."""
        all_txns = []
        
        for month, accounts in self.transactions.items():
            for account, txns in accounts.items():
                for txn in txns:
                    all_txns.append({
                        'month': month,
                        'account': account,
                        **txn
                    })
        
        if not all_txns:
            return pd.DataFrame()
        
        df = pd.DataFrame(all_txns)
        df['date'] = pd.to_datetime(df['date'])
        return df.sort_values('date', ascending=False)


# ============================================================================
# ANALYTICS & REPORTING
# ============================================================================

class BudgetAnalytics:
    """Advanced analytics and reporting."""
    
    def __init__(self, transaction_manager, account_manager):
        self.txn_mgr = transaction_manager
        self.acct_mgr = account_manager
    
    def generate_spending_trends(self, months=6, category=None):
        """Generate spending trends over time."""
        df = self.txn_mgr.get_all_transactions_df()
        if df.empty:
            return {}
        
        # Filter to recent months
        cutoff_date = datetime.now() - timedelta(days=30 * months)
        df = df[df['date'] >= cutoff_date]
        
        # Filter by category if specified
        if category and category != 'all':
            df = df[df['category'] == category]
        
        # Group by month
        df['month'] = df['date'].dt.to_period('M')
        monthly = df.groupby('month').agg({
            'amount': lambda x: abs(x[x < 0]).sum(),  # Only expenses
        }).reset_index()
        
        monthly['month'] = monthly['month'].astype(str)
        
        # Calculate trend
        if len(monthly) >= 2:
            amounts = monthly['amount'].values
            avg = np.mean(amounts)
            trend = np.polyfit(range(len(amounts)), amounts, 1)[0]
            trend_pct = (trend / avg * 100) if avg > 0 else 0
        else:
            avg = monthly['amount'].mean() if len(monthly) > 0 else 0
            trend = 0
            trend_pct = 0
        
        return {
            'monthly_data': monthly.to_dict('records'),
            'average_monthly': avg,
            'trend_direction': 'increasing' if trend > 0 else 'decreasing' if trend < 0 else 'stable',
            'trend_percentage': trend_pct,
            'category': category or 'all'
        }
    
    def generate_category_breakdown(self, month=None):
        """Generate detailed category breakdown."""
        summary = self.txn_mgr.get_monthly_summary(month)
        by_category = summary['by_category']
        
        total = sum(by_category.values())
        
        breakdown = []
        for category in TransactionCategorizer.CATEGORIES:
            amount = by_category.get(category, 0)
            percentage = (amount / total * 100) if total > 0 else 0
            
            breakdown.append({
                'category': category,
                'amount': amount,
                'percentage': percentage
            })
        
        # Sort by amount
        breakdown.sort(key=lambda x: x['amount'], reverse=True)
        
        return breakdown
    
    def recommend_budgets(self, months=3):
        """Recommend budget amounts based on historical spending."""
        df = self.txn_mgr.get_all_transactions_df()
        if df.empty:
            return {}
        
        # Get recent months
        cutoff_date = datetime.now() - timedelta(days=30 * months)
        df = df[df['date'] >= cutoff_date]
        df = df[df['amount'] < 0]  # Only expenses
        
        # Calculate average by category
        by_category = df.groupby('category')['amount'].apply(
            lambda x: abs(x).sum() / months
        ).to_dict()
        
        recommendations = {}
        for category in TransactionCategorizer.CATEGORIES:
            avg = by_category.get(category, 0)
            # Recommend 10% buffer
            recommended = avg * 1.1
            recommendations[category] = {
                'average_monthly': avg,
                'recommended_budget': recommended,
                'buffer_percentage': 10
            }
        
        total_recommended = sum(r['recommended_budget'] for r in recommendations.values())
        recommendations['total'] = total_recommended
        
        return recommendations
    
    def analyze_merchant_spending(self, top_n=10, month=None):
        """Analyze spending by merchant."""
        df = self.txn_mgr.get_all_transactions_df()
        if df.empty:
            return []
        
        # Filter by month if specified
        if month:
            df['month'] = df['date'].dt.strftime('%Y-%m')
            df = df[df['month'] == month]
        
        # Only expenses
        df = df[df['amount'] < 0].copy()
        df['amount'] = df['amount'].abs()
        
        # Group by merchant
        merchant_summary = df.groupby('clean_merchant').agg({
            'amount': 'sum',
            'date': 'count'
        }).reset_index()
        
        merchant_summary.columns = ['merchant', 'total_spent', 'transaction_count']
        merchant_summary = merchant_summary.sort_values('total_spent', ascending=False)
        
        return merchant_summary.head(top_n).to_dict('records')
    
    def calculate_savings_rate(self, month=None):
        """Calculate savings rate."""
        summary = self.txn_mgr.get_monthly_summary(month)
        
        income = summary['total_income']
        expenses = summary['total_expenses']
        
        if income == 0:
            return {
                'savings_amount': 0,
                'savings_rate': 0,
                'income': 0,
                'expenses': 0
            }
        
        savings = income - expenses
        rate = (savings / income * 100) if income > 0 else 0
        
        return {
            'savings_amount': savings,
            'savings_rate': rate,
            'income': income,
            'expenses': expenses
        }


# ============================================================================
# UNIFIED BUDGET TRACKER
# ============================================================================

class UnifiedBudgetTracker:
    """Main budget tracker coordinating all components."""
    
    def __init__(self):
        # Get data directory first
        self.data_dir = self._get_data_directory()
        
        # Initialize components (pass data_dir to storage for secret.key lookup)
        self.storage = SecureStorage(data_dir=self.data_dir)
        self.categorizer = TransactionCategorizer()
        self.csv_processor = CSVProcessor()
        self.account_mgr = AccountManager(self.storage)
        self.txn_mgr = TransactionManager(self.storage, self.categorizer)
        self.analytics = BudgetAnalytics(self.txn_mgr, self.account_mgr)
        
        # Define file paths (matching existing file structure)
        self.accounts_file = os.path.join(self.data_dir, 'checking_accounts.enc')
        self.cards_file = os.path.join(self.data_dir, 'credit_cards.enc')
        self.transactions_file = os.path.join(self.data_dir, 'checking_transactions.enc')
        self.category_spending_file = os.path.join(self.data_dir, 'category_spending.enc')
        self.budgets_file = os.path.join(self.data_dir, 'category_budgets.enc')
        self.spending_limits_file = os.path.join(self.data_dir, 'spending_limits.enc')
        self.historical_file = os.path.join(self.data_dir, 'historical_spending.enc')
        
        # Load existing data
        self.load_all_data()
    
    def _get_data_directory(self):
        """Get or create data directory."""
        current_file = Path(__file__)
        # Check if we're in a 'core' subdirectory
        if current_file.parent.name == 'core':
            project_root = current_file.parent.parent
        else:
            project_root = current_file.parent
        
        data_dir = project_root / 'data'
        data_dir.mkdir(exist_ok=True)
        return str(data_dir)
    
    def load_all_data(self):
        """Load all encrypted data from existing files."""
        # Load checking accounts
        accounts_data = self.storage.load_encrypted(self.accounts_file)
        if accounts_data:
            self.account_mgr.checking_accounts = accounts_data
        
        # Load credit cards
        cards_data = self.storage.load_encrypted(self.cards_file)
        if cards_data:
            self.account_mgr.credit_cards = cards_data
        
        # Load checking transactions
        txn_data = self.storage.load_encrypted(self.transactions_file)
        if txn_data:
            self.txn_mgr.transactions = txn_data
        
        # Load category spending
        category_data = self.storage.load_encrypted(self.category_spending_file)
        if category_data:
            self.txn_mgr.category_spending = category_data
        
        # Load category budgets
        budget_data = self.storage.load_encrypted(self.budgets_file)
        if budget_data:
            self.account_mgr.category_budgets = budget_data
        
        # Load spending limits
        limits_data = self.storage.load_encrypted(self.spending_limits_file)
        if limits_data:
            self.account_mgr.spending_limits = limits_data
    
    def save_all_data(self):
        """Save all data with encryption to existing file structure."""
        self.storage.save_encrypted(self.account_mgr.checking_accounts, self.accounts_file)
        self.storage.save_encrypted(self.account_mgr.credit_cards, self.cards_file)
        self.storage.save_encrypted(self.txn_mgr.transactions, self.transactions_file)
        self.storage.save_encrypted(self.txn_mgr.category_spending, self.category_spending_file)
        self.storage.save_encrypted(self.account_mgr.category_budgets, self.budgets_file)
        self.storage.save_encrypted(self.account_mgr.spending_limits, self.spending_limits_file)
    
    # ========================================================================
    # ACCOUNT OPERATIONS
    # ========================================================================
    
    def add_checking_account(self, name, balance, bank_name="", description=""):
        """Add checking account."""
        success, message = self.account_mgr.add_checking_account(
            name, balance, bank_name, description
        )
        if success:
            self.save_all_data()
        print(message)
        return success
    
    def add_credit_card(self, name, limit, stmt_date, due_date, 
                       description="", balance_due=0, current_balance=0):
        """Add credit card."""
        success, message = self.account_mgr.add_credit_card(
            name, limit, stmt_date, due_date, description, balance_due, current_balance
        )
        if success:
            self.save_all_data()
        print(message)
        return success
    
    def list_accounts(self):
        """List all accounts and cards."""
        print("\n" + "="*70)
        print("CHECKING ACCOUNTS")
        print("="*70)
        
        if not self.account_mgr.checking_accounts:
            print("No checking accounts found")
        else:
            for name, account in self.account_mgr.checking_accounts.items():
                print(f"\n{name}:")
                print(f"  Balance: ${account['current_balance']:,.2f}")
                if account['bank_name']:
                    print(f"  Bank: {account['bank_name']}")
                if account['description']:
                    print(f"  Description: {account['description']}")
            
            total = self.account_mgr.get_total_checking_balance()
            print(f"\n{'Total Balance:':<20} ${total:>12,.2f}")
        
        print("\n" + "="*70)
        print("CREDIT CARDS")
        print("="*70)
        
        if not self.account_mgr.credit_cards:
            print("No credit cards found")
        else:
            for name, card in self.account_mgr.credit_cards.items():
                limit = card['credit_limit']
                current = card['current_balance']
                due = card['balance_due']
                available = limit - current
                utilization = (current / limit * 100) if limit > 0 else 0
                
                print(f"\n{name}:")
                print(f"  Current Balance: ${current:,.2f}")
                print(f"  Balance Due: ${due:,.2f}")
                print(f"  Credit Limit: ${limit:,.2f}")
                print(f"  Available: ${available:,.2f}")
                print(f"  Utilization: {utilization:.1f}%")
                print(f"  Statement Date: Day {card['statement_date']}")
                print(f"  Due Date: Day {card['due_date']}")
                if card['description']:
                    print(f"  Description: {card['description']}")
            
            total_used = self.account_mgr.get_total_credit_used()
            total_available = self.account_mgr.get_total_credit_available()
            print(f"\n{'Total Credit Used:':<20} ${total_used:>12,.2f}")
            print(f"{'Total Available:':<20} ${total_available:>12,.2f}")
    
    # ========================================================================
    # TRANSACTION OPERATIONS
    # ========================================================================
    
    def import_transactions(self, csv_files, account_name):
        """Import transactions from CSV files."""
        if account_name not in self.account_mgr.checking_accounts and \
           account_name not in self.account_mgr.credit_cards:
            print(f"Error: Account '{account_name}' not found")
            return False
        
        total_imported = 0
        
        for csv_file in csv_files:
            try:
                print(f"\nProcessing: {csv_file}")
                
                # Read CSV
                df = self.csv_processor.read_csv_robust(csv_file)
                
                # Detect and convert format
                df = self.csv_processor.detect_and_convert_format(df)
                
                if df.empty:
                    print(f"  No valid transactions found")
                    continue
                
                # Add transactions
                count = self.txn_mgr.add_transactions_from_df(df, account_name)
                total_imported += count
                
                print(f"  Imported {count} transactions")
                
                # Calculate net change
                net_change = df['Amount'].sum()
                print(f"  Net change: ${net_change:+,.2f}")
                
            except Exception as e:
                print(f"  Error processing {csv_file}: {e}")
                continue
        
        if total_imported > 0:
            self.save_all_data()
            print(f"\n✅ Total imported: {total_imported} transactions")
            return True
        
        return False
    
    # ========================================================================
    # REPORTING
    # ========================================================================
    
    def show_summary(self, month=None):
        """Show comprehensive budget summary."""
        if month is None:
            month = datetime.now().strftime('%Y-%m')
        
        month_name = datetime.strptime(month, '%Y-%m').strftime('%B %Y')
        
        print("\n" + "="*70)
        print(f"BUDGET SUMMARY - {month_name}")
        print("="*70)
        
        # Monthly transaction summary
        summary = self.txn_mgr.get_monthly_summary(month)
        
        print(f"\n{'Transaction Count:':<25} {summary['transaction_count']:>10}")
        print(f"{'Total Income:':<25} ${summary['total_income']:>12,.2f}")
        print(f"{'Total Expenses:':<25} ${summary['total_expenses']:>12,.2f}")
        print(f"{'Net Change:':<25} ${summary['net_change']:>+12,.2f}")
        
        # Savings rate
        savings = self.analytics.calculate_savings_rate(month)
        if savings['income'] > 0:
            print(f"{'Savings Rate:':<25} {savings['savings_rate']:>12.1f}%")
        
        # Category breakdown
        print("\n" + "-"*70)
        print("SPENDING BY CATEGORY")
        print("-"*70)
        
        breakdown = self.analytics.generate_category_breakdown(month)
        for item in breakdown:
            if item['amount'] > 0:
                bar_length = int(item['percentage'] / 2)  # Max 50 chars
                bar = "█" * bar_length
                print(f"{item['category']:<15} ${item['amount']:>10,.2f}  {item['percentage']:>5.1f}%  {bar}")
        
        # Budget vs actual (if budgets are set)
        if self.account_mgr.category_budgets:
            print("\n" + "-"*70)
            print("BUDGET VS ACTUAL")
            print("-"*70)
            
            for category, budget in self.account_mgr.category_budgets.items():
                actual = summary['by_category'].get(category, 0)
                remaining = budget - actual
                pct_used = (actual / budget * 100) if budget > 0 else 0
                
                status = "✓" if actual <= budget else "⚠"
                print(f"{status} {category:<15} Budget: ${budget:>8,.2f}  "
                      f"Actual: ${actual:>8,.2f}  Remaining: ${remaining:>+8,.2f}  "
                      f"({pct_used:.0f}%)")
        
        # Account balances
        print("\n" + "-"*70)
        print("CURRENT BALANCES")
        print("-"*70)
        
        checking_total = self.account_mgr.get_total_checking_balance()
        credit_used = self.account_mgr.get_total_credit_used()
        credit_available = self.account_mgr.get_total_credit_available()
        
        print(f"{'Checking Accounts:':<25} ${checking_total:>12,.2f}")
        print(f"{'Credit Used:':<25} ${credit_used:>12,.2f}")
        print(f"{'Credit Available:':<25} ${credit_available:>12,.2f}")
        print(f"{'Net Worth (approx):':<25} ${(checking_total - credit_used):>12,.2f}")
    
    def show_trends(self, months=6, category=None):
        """Show spending trends."""
        print("\n" + "="*70)
        print(f"SPENDING TRENDS - Last {months} Months")
        if category:
            print(f"Category: {category}")
        print("="*70)
        
        trends = self.analytics.generate_spending_trends(months, category)
        
        if not trends or not trends.get('monthly_data'):
            print("\nInsufficient data for trend analysis")
            return
        
        print(f"\n{'Average Monthly:':<25} ${trends['average_monthly']:>12,.2f}")
        print(f"{'Trend:':<25} {trends['trend_direction']:>12}")
        if abs(trends['trend_percentage']) > 0.1:
            print(f"{'Trend Rate:':<25} {trends['trend_percentage']:>+12.1f}%")
        
        print("\nMonthly Breakdown:")
        for entry in trends['monthly_data']:
            print(f"  {entry['month']}: ${entry['amount']:,.2f}")
    
    def show_top_merchants(self, top_n=10, month=None):
        """Show top merchants by spending."""
        month_str = f" - {month}" if month else ""
        print("\n" + "="*70)
        print(f"TOP {top_n} MERCHANTS{month_str}")
        print("="*70)
        
        merchants = self.analytics.analyze_merchant_spending(top_n, month)
        
        if not merchants:
            print("\nNo merchant data available")
            return
        
        for i, merchant in enumerate(merchants, 1):
            print(f"{i:2}. {merchant['merchant']:<40} ${merchant['total_spent']:>10,.2f} "
                  f"({merchant['transaction_count']} transactions)")
    
    def recommend_budgets(self, months=3):
        """Show budget recommendations."""
        print("\n" + "="*70)
        print(f"BUDGET RECOMMENDATIONS - Based on {months} Month Average")
        print("="*70)
        
        recommendations = self.analytics.recommend_budgets(months)
        
        if not recommendations or recommendations.get('total', 0) == 0:
            print("\nInsufficient data for recommendations")
            return
        
        print(f"\n{'Category':<15} {'Avg Monthly':>12} {'Recommended':>12} {'Buffer':>8}")
        print("-"*70)
        
        for category in TransactionCategorizer.CATEGORIES:
            if category in recommendations:
                rec = recommendations[category]
                print(f"{category:<15} ${rec['average_monthly']:>11,.2f} "
                      f"${rec['recommended_budget']:>11,.2f} "
                      f"{rec['buffer_percentage']:>6}%")
        
        print("-"*70)
        print(f"{'TOTAL':<15} {'':<12} ${recommendations['total']:>11,.2f}")
        print("\nTo set these budgets, use:")
        print("  --set-budgets Shopping:XXX 'Food & Drinks':XXX ...")


# ============================================================================
# COMMAND LINE INTERFACE
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description='Unified Budget Tracker - Secure personal finance management',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Add accounts
  %(prog)s --add-checking MyBank 5000 "Chase Bank"
  %(prog)s --add-card MyCard 10000 15 25 "Main credit card"
  
  # Import transactions
  %(prog)s --import transactions.csv --account MyBank
  
  # View reports
  %(prog)s --summary
  %(prog)s --trends 6
  %(prog)s --top-merchants 10
  %(prog)s --recommend-budgets
        """
    )
    
    # Account management
    acct_group = parser.add_argument_group('Account Management')
    acct_group.add_argument('--add-checking', nargs='+', metavar='ARG',
                           help='Add checking account: name balance [bank] [description]')
    acct_group.add_argument('--add-card', nargs='+', metavar='ARG',
                           help='Add credit card: name limit stmt_day due_day [balance_due] [current_balance]')
    acct_group.add_argument('--list-accounts', action='store_true',
                           help='List all accounts and cards')
    acct_group.add_argument('--update-balance', nargs=3, metavar='ARG',
                           help='Update balance: account_name amount type(checking/current/due)')
    
    # Transaction management
    txn_group = parser.add_argument_group('Transaction Management')
    txn_group.add_argument('--import', nargs='+', dest='import_files',
                          metavar='CSV_FILE',
                          help='Import transactions from CSV file(s)')
    txn_group.add_argument('--account', dest='account_name',
                          help='Account name for import operation')
    
    # Reporting
    report_group = parser.add_argument_group('Reports & Analysis')
    report_group.add_argument('--summary', nargs='?', const=None,
                             metavar='MONTH',
                             help='Show budget summary [YYYY-MM]')
    report_group.add_argument('--trends', nargs='?', const=6, type=int,
                             metavar='MONTHS',
                             help='Show spending trends (default: 6 months)')
    report_group.add_argument('--category', metavar='CATEGORY',
                             help='Filter analysis by category')
    report_group.add_argument('--top-merchants', nargs='?', const=10, type=int,
                             metavar='N',
                             help='Show top N merchants (default: 10)')
    report_group.add_argument('--recommend-budgets', nargs='?', const=3, type=int,
                             metavar='MONTHS',
                             help='Recommend budgets based on N months (default: 3)')
    
    # Budget management
    budget_group = parser.add_argument_group('Budget Management')
    budget_group.add_argument('--set-budgets', nargs='+',
                             metavar='CATEGORY:AMOUNT',
                             help='Set category budgets: "Shopping:500" "Food & Drinks:400"')
    
    args = parser.parse_args()
    
    # Initialize tracker
    tracker = UnifiedBudgetTracker()
    
    # Execute commands
    if args.add_checking:
        parts = args.add_checking
        name = parts[0]
        balance = float(parts[1])
        bank = parts[2] if len(parts) > 2 else ""
        desc = parts[3] if len(parts) > 3 else ""
        tracker.add_checking_account(name, balance, bank, desc)
    
    elif args.add_card:
        parts = args.add_card
        name = parts[0]
        limit = float(parts[1])
        stmt = int(parts[2])
        due = int(parts[3])
        balance_due = float(parts[4]) if len(parts) > 4 else 0
        current = float(parts[5]) if len(parts) > 5 else 0
        tracker.add_credit_card(name, limit, stmt, due, "", balance_due, current)
    
    elif args.list_accounts:
        tracker.list_accounts()
    
    elif args.update_balance:
        account, amount, balance_type = args.update_balance
        amount = float(amount)
        
        if balance_type == 'checking':
            success, msg = tracker.account_mgr.update_account_balance(account, amount)
            if success:
                tracker.save_all_data()
            print(msg)
        else:
            success, msg = tracker.account_mgr.update_card_balance(account, amount, balance_type)
            if success:
                tracker.save_all_data()
            print(msg)
    
    elif args.import_files:
        if not args.account_name:
            print("Error: --account required for import operation")
            return
        tracker.import_transactions(args.import_files, args.account_name)
    
    elif args.summary is not None:
        tracker.show_summary(args.summary)
    
    elif args.trends is not None:
        tracker.show_trends(args.trends, args.category)
    
    elif args.top_merchants is not None:
        tracker.show_top_merchants(args.top_merchants, args.summary)
    
    elif args.recommend_budgets is not None:
        tracker.recommend_budgets(args.recommend_budgets)
    
    elif args.set_budgets:
        budgets = {}
        for budget_str in args.set_budgets:
            if ':' in budget_str:
                category, amount = budget_str.split(':', 1)
                try:
                    budgets[category.strip()] = float(amount.strip())
                except ValueError:
                    print(f"Invalid amount for {category}: {amount}")
        
        if budgets:
            tracker.account_mgr.category_budgets.update(budgets)
            tracker.save_all_data()
            print("✅ Budgets updated:")
            for cat, amt in budgets.items():
                print(f"  {cat}: ${amt:,.2f}")
    
    else:
        # Default: show summary
        tracker.show_summary()


if __name__ == "__main__":
    main()