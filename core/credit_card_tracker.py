#!/usr/bin/env python3
"""
Credit Card Tracker with Time Period Analysis
- Tracks spending across multiple credit cards
- Manages credit limits, due dates, and balances
- Soft/hard spending limits with alerts
- Category budget tracking
- Automatic transaction processing with merchant name cleaning
- Secure storage of card configurations
- Time period analysis with monthly/quarterly/yearly breakdowns
- Historical analysis storage and comparison
- NEW: Category spending reset and current month filtering
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
from collections import defaultdict
import calendar

class TimePeriodAnalyzer:
    def __init__(self, credit_card_tracker):
        """Initialize with reference to main credit card tracker."""
        self.tracker = credit_card_tracker
        self.historical_data = {}
        self.historical_file = 'historical_spending.enc'
        self.load_historical_data()
    
    def analyze_time_period(self, df, start_date=None, end_date=None, group_by='month'):
        """
        Analyze transactions over a specific time period.
        
        Args:
            df: DataFrame with transaction data
            start_date: Start date (YYYY-MM-DD) or None for all data
            end_date: End date (YYYY-MM-DD) or None for all data
            group_by: 'month', 'quarter', or 'year'
        """
        if df.empty:
            print("No transaction data available for analysis")
            return {}
        
        # Ensure we have a date column to work with
        if 'Transaction Date' not in df.columns:
            print("No 'Transaction Date' column found in data")
            return {}
        
        # Convert date column to datetime
        df = df.copy()
        try:
            df['parsed_date'] = pd.to_datetime(df['Transaction Date'])
        except:
            print("Could not parse transaction dates")
            return {}
        
        # Filter by date range if specified
        if start_date:
            try:
                start_dt = pd.to_datetime(start_date)
                df = df[df['parsed_date'] >= start_dt]
            except:
                print(f"Invalid start date format: {start_date}")
                return {}
        
        if end_date:
            try:
                end_dt = pd.to_datetime(end_date)
                df = df[df['parsed_date'] <= end_dt]
            except:
                print(f"Invalid end date format: {end_date}")
                return {}
        
        if df.empty:
            print("No transactions found in the specified date range")
            return {}
        
        # Add categorization
        df['custom_category'] = df.apply(
            lambda row: self.tracker._categorize_transaction(
                row.get('Description', ''), 
                row.get('Memo', ''),
                row.get('Category', '')
            ), axis=1
        )
        
        # Add time grouping column
        if group_by == 'month':
            df['period'] = df['parsed_date'].dt.to_period('M')
            df['period_str'] = df['parsed_date'].dt.strftime('%Y-%m')
        elif group_by == 'quarter':
            df['period'] = df['parsed_date'].dt.to_period('Q')
            df['period_str'] = df['parsed_date'].dt.strftime('%Y-Q') + df['parsed_date'].dt.quarter.astype(str)
        elif group_by == 'year':
            df['period'] = df['parsed_date'].dt.to_period('Y')
            df['period_str'] = df['parsed_date'].dt.strftime('%Y')
        else:
            print(f"Invalid group_by option: {group_by}")
            return {}
        
        # Filter to spending only (negative amounts)
        spending_df = df[df['Amount'] < 0].copy()
        spending_df['amount_abs'] = spending_df['Amount'].abs()
        
        # Group by period and category
        period_analysis = {}
        
        for period_str in sorted(spending_df['period_str'].unique()):
            period_data = spending_df[spending_df['period_str'] == period_str]
            
            # Calculate category totals for this period
            category_totals = period_data.groupby('custom_category')['amount_abs'].sum()
            
            # Ensure all categories are represented
            categories = ['Shopping', 'Food & Drinks', 'Services', 'Entertainment', 'Groceries', 'Other']
            category_dict = {}
            for cat in categories:
                category_dict[cat] = float(category_totals.get(cat, 0.0))
            
            period_analysis[period_str] = {
                'total_spending': float(period_data['amount_abs'].sum()),
                'transaction_count': len(period_data),
                'categories': category_dict,
                'average_transaction': float(period_data['amount_abs'].mean()) if len(period_data) > 0 else 0.0,
                'date_range': {
                    'start': period_data['Transaction Date'].min(),
                    'end': period_data['Transaction Date'].max()
                }
            }
        
        return period_analysis
    
    def display_period_analysis(self, period_analysis, show_categories=True):
        """Display formatted time period analysis."""
        if not period_analysis:
            print("No data to display")
            return
        
        periods = sorted(period_analysis.keys())
        
        print("\n" + "="*80)
        print("TIME PERIOD SPENDING ANALYSIS")
        print("="*80)
        
        # Summary table
        print(f"{'Period':<12} {'Total Spent':<12} {'Transactions':<12} {'Avg/Transaction':<15}")
        print("-" * 55)
        
        total_all_periods = 0
        total_transactions = 0
        
        for period in periods:
            data = period_analysis[period]
            total_spending = data['total_spending']
            transaction_count = data['transaction_count']
            avg_transaction = data['average_transaction']
            
            total_all_periods += total_spending
            total_transactions += transaction_count
            
            print(f"{period:<12} ${total_spending:<11,.2f} {transaction_count:<12} ${avg_transaction:<14,.2f}")
        
        print("-" * 55)
        overall_avg = total_all_periods / total_transactions if total_transactions > 0 else 0
        print(f"{'TOTAL':<12} ${total_all_periods:<11,.2f} {total_transactions:<12} ${overall_avg:<14,.2f}")
        
        if show_categories:
            print("\n" + "="*80)
            print("MONTHLY CATEGORY BREAKDOWN")
            print("="*80)
            
            # Category headers
            categories = ['Shopping', 'Food & Drinks', 'Services', 'Entertainment', 'Groceries', 'Other']
            header = f"{'Period':<12}"
            for cat in categories:
                header += f"{cat:<12}"
            print(header)
            print("-" * (12 + len(categories) * 12))
            
            # Category data for each period
            for period in periods:
                data = period_analysis[period]
                row = f"{period:<12}"
                for cat in categories:
                    amount = data['categories'][cat]
                    if amount > 0:
                        row += f"${amount:<11,.0f}"
                    else:
                        row += f"{'-':<12}"
                print(row)
            
            # Category totals
            print("-" * (12 + len(categories) * 12))
            totals_row = f"{'TOTALS':<12}"
            for cat in categories:
                cat_total = sum(period_analysis[p]['categories'][cat] for p in periods)
                if cat_total > 0:
                    totals_row += f"${cat_total:<11,.0f}"
                else:
                    totals_row += f"{'-':<12}"
            print(totals_row)
    
    def compare_periods(self, period_analysis, comparison_type='month_over_month'):
        """Compare spending between periods."""
        if len(period_analysis) < 2:
            print("Need at least 2 periods for comparison")
            return
        
        periods = sorted(period_analysis.keys())
        
        print(f"\n=== PERIOD COMPARISON ({comparison_type.upper()}) ===")
        
        if comparison_type == 'month_over_month':
            for i in range(1, len(periods)):
                current = periods[i]
                previous = periods[i-1]
                
                current_total = period_analysis[current]['total_spending']
                previous_total = period_analysis[previous]['total_spending']
                
                change = current_total - previous_total
                change_pct = (change / previous_total * 100) if previous_total > 0 else 0
                
                status = "📈" if change > 0 else "📉" if change < 0 else "➡️"
                
                print(f"{previous} → {current}: ${change:+,.2f} ({change_pct:+.1f}%) {status}")
        
        elif comparison_type == 'year_over_year':
            # Group by month across years
            monthly_comparison = defaultdict(list)
            
            for period in periods:
                if '-' in period:  # YYYY-MM format
                    year, month = period.split('-')
                    monthly_comparison[month].append((year, period_analysis[period]['total_spending']))
            
            print("\nYear-over-Year Comparison by Month:")
            for month in sorted(monthly_comparison.keys()):
                if len(monthly_comparison[month]) > 1:
                    print(f"\nMonth {month}:")
                    monthly_comparison[month].sort()  # Sort by year
                    for i in range(1, len(monthly_comparison[month])):
                        current_year, current_amount = monthly_comparison[month][i]
                        prev_year, prev_amount = monthly_comparison[month][i-1]
                        
                        change = current_amount - prev_amount
                        change_pct = (change / prev_amount * 100) if prev_amount > 0 else 0
                        
                        print(f"  {prev_year} → {current_year}: ${change:+,.2f} ({change_pct:+.1f}%)")
    
    def trend_analysis(self, period_analysis, category=None):
        """Analyze spending trends over time."""
        if len(period_analysis) < 3:
            print("Need at least 3 periods for trend analysis")
            return
        
        periods = sorted(period_analysis.keys())
        
        print(f"\n=== TREND ANALYSIS ===")
        
        if category:
            if category not in ['Shopping', 'Food & Drinks', 'Services', 'Entertainment', 'Groceries', 'Other']:
                print(f"Invalid category: {category}")
                return
            
            print(f"Category: {category}")
            values = [period_analysis[p]['categories'][category] for p in periods]
        else:
            print("Total Spending Trend")
            values = [period_analysis[p]['total_spending'] for p in periods]
        
        # Calculate trend direction
        if len(values) >= 3:
            recent_avg = sum(values[-3:]) / 3
            older_avg = sum(values[:-3]) / len(values[:-3]) if len(values) > 3 else values[0]
            
            trend_change = recent_avg - older_avg
            trend_pct = (trend_change / older_avg * 100) if older_avg > 0 else 0
            
            if trend_pct > 10:
                trend_indicator = "📈 INCREASING"
            elif trend_pct < -10:
                trend_indicator = "📉 DECREASING"
            else:
                trend_indicator = "➡️ STABLE"
            
            print(f"Overall Trend: {trend_indicator} ({trend_pct:+.1f}%)")
            
            # Show period-by-period values
            print(f"\n{'Period':<12} {'Amount':<12} {'Change':<12}")
            print("-" * 36)
            
            for i, period in enumerate(periods):
                amount = values[i]
                if i > 0:
                    change = amount - values[i-1]
                    change_str = f"${change:+,.2f}"
                else:
                    change_str = "-"
                
                print(f"{period:<12} ${amount:<11,.2f} {change_str:<12}")
    
    def save_historical_data(self):
        """Save historical analysis data to encrypted file."""
        try:
            json_data = json.dumps(self.historical_data, indent=2, default=str)
            encrypted_data = self.tracker.cipher_suite.encrypt(json_data.encode())
            
            with open(self.historical_file, 'wb') as f:
                f.write(encrypted_data)
        except Exception as e:
            print(f"Error saving historical data: {e}")
    
    def load_historical_data(self):
        """Load historical analysis data from encrypted file."""
        try:
            if not Path(self.historical_file).exists():
                return
            
            with open(self.historical_file, 'rb') as f:
                encrypted_data = f.read()
            
            decrypted_data = self.tracker.cipher_suite.decrypt(encrypted_data).decode()
            self.historical_data = json.loads(decrypted_data)
        except Exception as e:
            print(f"Note: Could not load historical data ({e}). Starting fresh.")
            self.historical_data = {}
    
    def store_period_analysis(self, analysis_name, period_analysis, metadata=None):
        """Store a period analysis for future reference."""
        self.historical_data[analysis_name] = {
            'analysis': period_analysis,
            'metadata': metadata or {},
            'created_date': datetime.now().isoformat()
        }
        self.save_historical_data()
        print(f"Stored analysis '{analysis_name}' with {len(period_analysis)} periods")
    
    def list_stored_analyses(self):
        """List all stored historical analyses."""
        if not self.historical_data:
            print("No stored analyses found")
            return
        
        print("\n=== STORED ANALYSES ===")
        for name, data in self.historical_data.items():
            created = data.get('created_date', 'Unknown')
            period_count = len(data.get('analysis', {}))
            metadata = data.get('metadata', {})
            
            print(f"Name: {name}")
            print(f"  Created: {created}")
            print(f"  Periods: {period_count}")
            if metadata:
                for key, value in metadata.items():
                    print(f"  {key.title()}: {value}")
            print()
    
    def load_stored_analysis(self, analysis_name):
        """Load a previously stored analysis."""
        if analysis_name not in self.historical_data:
            print(f"Analysis '{analysis_name}' not found")
            return None
        
        return self.historical_data[analysis_name]['analysis']

class CreditCardTracker:
    def __init__(self):
        self.cards = {}
        self.spending_limits = {}
        self.category_budgets = {}
        self.category_spending = {}

        # Update file paths to use data directory
        data_dir = self._get_data_directory()
        self.config_file = os.path.join(data_dir, 'credit_cards.enc')
        self.limits_file = os.path.join(data_dir, 'spending_limits.enc')
        self.budgets_file = os.path.join(data_dir, 'category_budgets.enc')
        self.spending_file = os.path.join(data_dir, 'category_spending.enc')

        # Set up encryption BEFORE loading files
        self.cipher_suite = self._setup_encryption()

        self.load_cards()
        self.load_spending_limits()
        self.load_category_budgets()
        self.load_category_spending()

    def _get_data_directory(self):
        """Get the data directory path, creating it if it doesn't exist."""
        import os
        from pathlib import Path
        
        # Get the project root directory (parent of core directory)
        current_file = Path(__file__)
        project_root = current_file.parent.parent
        data_dir = project_root / 'data'
        
        # Create data directory if it doesn't exist
        data_dir.mkdir(exist_ok=True)
        
        return str(data_dir)
    
    def _setup_encryption(self):
        """Set up encryption for secure storage."""
        encryption_key = keyring.get_password("credit_card_tracker", "encryption_key")
        
        if not encryption_key:
            key = Fernet.generate_key()
            keyring.set_password("credit_card_tracker", "encryption_key", key.decode())
            encryption_key = key.decode()
            
        return Fernet(encryption_key.encode())
    
    def _process_csv_file(self, file_path):
        """Process CSV files from various credit card providers with format detection."""
        print(f"Processing CSV file: {file_path}")
        
        try:
            # Try different encodings
            encodings = ['utf-8', 'latin-1', 'cp1252', 'iso-8859-1']
            df = None
            
            for encoding in encodings:
                try:
                    df = pd.read_csv(file_path, encoding=encoding)
                    print(f"✅ Successfully read file with {encoding} encoding")
                    break
                except UnicodeDecodeError:
                    continue
            
            if df is None:
                raise Exception("Could not decode file with any standard encoding")
            
            print(f"📊 Loaded {len(df)} rows, {len(df.columns)} columns")
            print(f"📋 Columns found: {list(df.columns)}")
            
            # Detect and convert format
            df = self._detect_and_convert_format(df, file_path)
            
            # Validate required columns
            required_columns = ['Transaction Date', 'Description', 'Amount']
            missing_columns = [col for col in required_columns if col not in df.columns]
            
            if missing_columns:
                print(f"⚠️ Missing required columns: {missing_columns}")
                print(f"   Available columns: {list(df.columns)}")
                return pd.DataFrame()
            
            # Clean amount field
            if 'Amount' in df.columns:
                df['Amount'] = pd.to_numeric(df['Amount'], errors='coerce')
            
            # Remove empty rows
            df = df.dropna(subset=['Amount'])
            
            # Sort by date if possible
            if 'Transaction Date' in df.columns:
                try:
                    df['parsed_date'] = pd.to_datetime(df['Transaction Date'], errors='coerce')
                    df = df.sort_values('parsed_date', ascending=False)
                    df = df.drop('parsed_date', axis=1)
                except:
                    pass
            
            print(f"✅ Processed {len(df)} valid transactions")
            return df
            
        except Exception as e:
            print(f"❌ Error processing CSV file: {e}")
            import traceback
            traceback.print_exc()
            return pd.DataFrame()
    
    def _detect_and_convert_format(self, df, file_path):
        """Detect CSV format and convert to standard format if needed."""
        import os
        
        filename = os.path.basename(file_path).lower()
        columns_lower = [col.lower() for col in df.columns]
        
        print(f"🔍 Detecting format for: {filename}")
        
        # Check if already in standard format (Chase format)
        if 'transaction date' in columns_lower and 'amount' in columns_lower:
            print("✅ Already in standard format (Chase)")
            return df
        
        # Detect Citi format
        if 'date' in columns_lower and 'debit' in columns_lower and 'credit' in columns_lower:
            print("🔄 Converting Citi format...")
            return self._convert_citi_format(df)
        
        # Detect Bank of America format
        if 'posted date' in columns_lower and 'payee' in columns_lower:
            print("🔄 Converting Bank of America format...")
            return self._convert_bofa_format(df)
        
        # Detect Wells Fargo format
        if 'date' in columns_lower and 'amount' in columns_lower and 'description' in columns_lower:
            print("🔄 Converting Wells Fargo format...")
            return self._convert_wells_fargo_format(df)
        
        # Detect Capital One format
        if 'transaction date' in columns_lower and 'debit' in columns_lower:
            print("🔄 Converting Capital One format...")
            return self._convert_capital_one_format(df)
        
        # Try generic conversion
        print("🔄 Attempting generic format conversion...")
        return self._convert_generic_format(df)

    def _convert_citi_format(self, df):
        """Convert Citi CSV format to standard format."""
        converted_df = pd.DataFrame()
        
        # Map column names (case-insensitive)
        column_mapping = {}
        for col in df.columns:
            col_lower = col.lower()
            if col_lower == 'date':
                column_mapping[col] = 'Transaction Date'
            elif 'description' in col_lower:
                column_mapping[col] = 'Description'
            elif 'category' in col_lower:
                column_mapping[col] = 'Category'
        
        # Copy mapped columns
        for old_col, new_col in column_mapping.items():
            converted_df[new_col] = df[old_col]
        
        # Add Post Date (same as Transaction Date)
        if 'Transaction Date' in converted_df.columns:
            converted_df['Post Date'] = converted_df['Transaction Date']
        
        # Handle Debit/Credit columns -> Amount
        debit_col = None
        credit_col = None
        
        for col in df.columns:
            col_lower = col.lower()
            if 'debit' in col_lower:
                debit_col = col
            elif 'credit' in col_lower:
                credit_col = col
        
        # Create Amount column (negative for debits, positive for credits)
        amounts = []
        types = []
        
        for idx, row in df.iterrows():
            debit_val = row[debit_col] if debit_col else None
            credit_val = row[credit_col] if credit_col else None
            
            # Clean and convert values
            if pd.notna(debit_val) and str(debit_val).strip():
                # Debit is spending (negative)
                amount_str = str(debit_val).replace('$', '').replace(',', '').strip()
                try:
                    amount = -abs(float(amount_str))
                    amounts.append(amount)
                    types.append('Sale')
                except:
                    amounts.append(0)
                    types.append('Unknown')
            elif pd.notna(credit_val) and str(credit_val).strip():
                # Credit is payment/refund (positive)
                amount_str = str(credit_val).replace('$', '').replace(',', '').strip()
                try:
                    amount = float(amount_str)
                    amounts.append(amount)
                    types.append('Payment')
                except:
                    amounts.append(0)
                    types.append('Unknown')
            else:
                amounts.append(0)
                types.append('Unknown')
        
        converted_df['Amount'] = amounts
        converted_df['Type'] = types
        
        # Add Memo column if not present
        if 'Memo' not in converted_df.columns:
            converted_df['Memo'] = ''
        
        # Ensure all required columns exist
        required_columns = ['Transaction Date', 'Post Date', 'Description', 'Category', 'Type', 'Amount', 'Memo']
        for col in required_columns:
            if col not in converted_df.columns:
                converted_df[col] = ''
        
        # Reorder columns
        converted_df = converted_df[required_columns]
        
        # Remove rows with zero amount
        converted_df = converted_df[converted_df['Amount'] != 0]
        
        print(f"✅ Converted {len(converted_df)} Citi transactions")
        
        # Debug: Show sample conversion
        if len(converted_df) > 0:
            sample = converted_df.head(3)
            print("Sample converted transactions:")
            for idx, row in sample.iterrows():
                print(f"  {row['Description'][:30]}: ${row['Amount']:.2f}")
        
        return converted_df

    def _convert_bofa_format(self, df):
        """Convert Bank of America format to standard format."""
        converted_df = pd.DataFrame()
        
        # Map columns
        column_mapping = {}
        for col in df.columns:
            col_lower = col.lower()
            if 'posted date' in col_lower or col_lower == 'date':
                column_mapping[col] = 'Transaction Date'
            elif 'payee' in col_lower or 'description' in col_lower:
                column_mapping[col] = 'Description'
            elif 'amount' in col_lower:
                column_mapping[col] = 'Amount'
            elif 'category' in col_lower:
                column_mapping[col] = 'Category'
        
        # Copy mapped columns
        for old_col, new_col in column_mapping.items():
            converted_df[new_col] = df[old_col]
        
        # Add missing columns
        if 'Post Date' not in converted_df.columns:
            converted_df['Post Date'] = converted_df.get('Transaction Date', '')
        
        if 'Type' not in converted_df.columns:
            # Determine type based on amount
            if 'Amount' in converted_df.columns:
                converted_df['Type'] = converted_df['Amount'].apply(
                    lambda x: 'Payment' if x > 0 else 'Sale'
                )
            else:
                converted_df['Type'] = 'Sale'
        
        if 'Memo' not in converted_df.columns:
            converted_df['Memo'] = ''
        
        if 'Category' not in converted_df.columns:
            converted_df['Category'] = ''
        
        # Ensure all required columns exist
        required_columns = ['Transaction Date', 'Post Date', 'Description', 'Category', 'Type', 'Amount', 'Memo']
        for col in required_columns:
            if col not in converted_df.columns:
                converted_df[col] = ''
        
        return converted_df[required_columns]

    def _convert_wells_fargo_format(self, df):
        """Convert Wells Fargo format to standard format."""
        converted_df = pd.DataFrame()
        
        # Wells Fargo typically has Date, Amount, *, *, Description
        column_mapping = {}
        for col in df.columns:
            col_lower = col.lower()
            if col_lower == 'date':
                column_mapping[col] = 'Transaction Date'
            elif 'amount' in col_lower:
                column_mapping[col] = 'Amount'
            elif 'description' in col_lower or col == df.columns[-1]:  # Last column often description
                column_mapping[col] = 'Description'
        
        # Copy mapped columns
        for old_col, new_col in column_mapping.items():
            converted_df[new_col] = df[old_col]
        
        # Wells Fargo amounts are typically positive for debits
        if 'Amount' in converted_df.columns:
            # Make spending negative
            converted_df['Amount'] = converted_df['Amount'].apply(
                lambda x: -abs(x) if x != 0 else 0
            )
        
        # Add missing columns
        converted_df['Post Date'] = converted_df.get('Transaction Date', '')
        converted_df['Category'] = ''
        converted_df['Type'] = 'Sale'
        converted_df['Memo'] = ''
        
        # Ensure all required columns exist
        required_columns = ['Transaction Date', 'Post Date', 'Description', 'Category', 'Type', 'Amount', 'Memo']
        return converted_df[required_columns]

    def _convert_capital_one_format(self, df):
        """Convert Capital One format to standard format."""
        converted_df = pd.DataFrame()
        
        # Map columns
        column_mapping = {}
        for col in df.columns:
            col_lower = col.lower()
            if 'transaction date' in col_lower:
                column_mapping[col] = 'Transaction Date'
            elif 'posted date' in col_lower:
                column_mapping[col] = 'Post Date'
            elif 'description' in col_lower or 'merchant' in col_lower:
                column_mapping[col] = 'Description'
            elif 'category' in col_lower:
                column_mapping[col] = 'Category'
            elif 'debit' in col_lower:
                # Capital One uses Debit for spending
                debit_col = col
            elif 'credit' in col_lower:
                credit_col = col
        
        # Copy mapped columns
        for old_col, new_col in column_mapping.items():
            converted_df[new_col] = df[old_col]
        
        # Handle Debit/Credit if present
        if 'debit_col' in locals() or 'credit_col' in locals():
            amounts = []
            for idx, row in df.iterrows():
                debit = row.get(debit_col, 0) if 'debit_col' in locals() else 0
                credit = row.get(credit_col, 0) if 'credit_col' in locals() else 0
                
                if pd.notna(debit) and debit != 0:
                    amounts.append(-abs(float(str(debit).replace('$', '').replace(',', ''))))
                elif pd.notna(credit) and credit != 0:
                    amounts.append(float(str(credit).replace('$', '').replace(',', '')))
                else:
                    amounts.append(0)
            
            converted_df['Amount'] = amounts
        
        # Add missing columns
        if 'Post Date' not in converted_df.columns:
            converted_df['Post Date'] = converted_df.get('Transaction Date', '')
        
        converted_df['Type'] = converted_df.get('Amount', pd.Series([0])).apply(
            lambda x: 'Payment' if x > 0 else 'Sale'
        )
        converted_df['Memo'] = ''
        
        if 'Category' not in converted_df.columns:
            converted_df['Category'] = ''
        
        # Ensure all required columns exist
        required_columns = ['Transaction Date', 'Post Date', 'Description', 'Category', 'Type', 'Amount', 'Memo']
        return converted_df[required_columns]

    def _convert_generic_format(self, df):
        """Generic format converter for unknown CSV formats."""
        converted_df = pd.DataFrame()
        
        # Try to find best matches for required columns
        columns_lower = {col: col.lower() for col in df.columns}
        
        # Find date column
        date_col = None
        for col, col_lower in columns_lower.items():
            if 'date' in col_lower or 'posted' in col_lower:
                date_col = col
                break
        
        # Find description column
        desc_col = None
        for col, col_lower in columns_lower.items():
            if 'description' in col_lower or 'merchant' in col_lower or 'payee' in col_lower:
                desc_col = col
                break
        
        # Find amount column(s)
        amount_col = None
        debit_col = None
        credit_col = None
        
        for col, col_lower in columns_lower.items():
            if 'amount' in col_lower:
                amount_col = col
            elif 'debit' in col_lower:
                debit_col = col
            elif 'credit' in col_lower:
                credit_col = col
        
        # Find category column
        category_col = None
        for col, col_lower in columns_lower.items():
            if 'category' in col_lower or 'type' in col_lower:
                category_col = col
                break
        
        # Build converted dataframe
        if date_col:
            converted_df['Transaction Date'] = df[date_col]
            converted_df['Post Date'] = df[date_col]
        else:
            converted_df['Transaction Date'] = ''
            converted_df['Post Date'] = ''
        
        if desc_col:
            converted_df['Description'] = df[desc_col]
        else:
            # Try to find any text column that might be description
            for col in df.columns:
                if df[col].dtype == 'object':
                    sample_val = df[col].dropna().iloc[0] if not df[col].dropna().empty else ''
                    if len(str(sample_val)) > 5 and not str(sample_val).replace('.', '').replace('-', '').isdigit():
                        converted_df['Description'] = df[col]
                        break
            
            if 'Description' not in converted_df.columns:
                converted_df['Description'] = 'Transaction'
        
        # Handle amount
        if amount_col:
            converted_df['Amount'] = pd.to_numeric(df[amount_col], errors='coerce')
        elif debit_col and credit_col:
            # Combine debit and credit
            amounts = []
            for idx, row in df.iterrows():
                debit = row[debit_col]
                credit = row[credit_col]
                
                if pd.notna(debit) and str(debit).strip():
                    amounts.append(-abs(float(str(debit).replace('$', '').replace(',', ''))))
                elif pd.notna(credit) and str(credit).strip():
                    amounts.append(float(str(credit).replace('$', '').replace(',', '')))
                else:
                    amounts.append(0)
            
            converted_df['Amount'] = amounts
        else:
            converted_df['Amount'] = 0
        
        if category_col:
            converted_df['Category'] = df[category_col]
        else:
            converted_df['Category'] = ''
        
        converted_df['Type'] = 'Sale'
        converted_df['Memo'] = ''
        
        # Ensure all required columns exist
        required_columns = ['Transaction Date', 'Post Date', 'Description', 'Category', 'Type', 'Amount', 'Memo']
        return converted_df[required_columns]
    
    def _extract_meaningful_text(self, description):
        """Extract meaningful text from potentially garbled descriptions."""
        if not description or len(description) < 3:
            return ""
        
        # Look for recognizable patterns even in garbled text
        import re
        
        # Try to find brand names or meaningful words
        meaningful_patterns = [
            r'(amazon|amzn)',
            r'(walmart|wal-mart)',
            r'(target)',
            r'(costco)',
            r'(starbucks)',
            r'(mcdonalds|mcdonald)',
            r'(kroger)',
            r'(whole foods|wholefoods)',
            r'(netflix)',
            r'(spotify)',
            r'(uber|lyft)',
            r'(chase|bank)',
            r'(chevron|shell|exxon|bp)',
            r'(home depot|lowes)',
            r'(cvs|walgreens)',
            r'(trader joe)',
            r'(chipotle)',
            r'(apple|itunes)'
        ]
        
        text_lower = description.lower()
        for pattern in meaningful_patterns:
            match = re.search(pattern, text_lower)
            if match:
                return match.group(1)
        
        return ""
    
    def _match_category_keywords(self, text, debug=False):
        """Enhanced keyword matching with better patterns."""
        
        # More comprehensive and specific keyword matching
        categories = {
            'Groceries': [
                # Major grocery chains - more specific patterns
                'whole foods', 'wholefoods', 'kroger', 'safeway', 'publix', 
                'trader joes', 'trader joe', 'aldi', 'food lion', 'giant', 
                'harris teeter', 'stop shop', 'jewel', 'meijer', 'heb', 
                'wegmans', 'fresh market', 'albertsons', 'vons', 'ralphs',
                'acme', 'shoprite', 'king soopers', 'smiths', 'frys', 
                'qfc', 'fred meyer', 'piggly wiggly', 'winn dixie',
                # International chains
                'tesco', 'sainsbury', 'asda', 'lidl',
                # Generic terms
                'grocery', 'supermarket', 'market', 'produce', 'deli', 'bakery',
                # Warehouse stores when clearly for groceries
                'costco wholesale', 'sams club', 'bjs wholesale'
            ],
            
            'Food & Drinks': [
                # Coffee shops
                'starbucks', 'dunkin', 'dunkin donuts', 'peets coffee', 
                'caribou coffee', 'coffee bean', 'tim hortons', 'panera bread',
                # Fast food - specific patterns
                'mcdonalds', 'mcdonald', 'burger king', 'subway sandwich',
                'kfc', 'taco bell', 'pizza hut', 'dominos', 'papa johns',
                'little caesars', 'chick-fil-a', 'chick fil a', 'popeyes',
                'wendys', 'wendy', 'arbys', 'arby', 'jack in the box',
                'in-n-out', 'whataburger', 'sonic drive', 'dairy queen',
                'five guys', 'shake shack', 'white castle',
                # Casual dining
                'chipotle', 'panera', 'olive garden', 'red lobster', 'applebees',
                'chilis', 'tgi fridays', 'outback', 'texas roadhouse', 
                'cheesecake factory', 'buffalo wild wings', 'hooters',
                # Delivery and food services
                'doordash', 'uber eats', 'grubhub', 'postmates', 'seamless',
                'instacart', 'fresh direct',
                # Generic food terms
                'restaurant', 'cafe', 'bar', 'pub', 'brewery', 'coffee',
                'pizza', 'takeout', 'delivery', 'dining', 'food', 'drink',
                'beverage', 'alcohol', 'wine', 'beer', 'bistro', 'grill', 'diner'
            ],
            
            'Shopping': [
                # Major retailers
                'amazon', 'amzn', 'walmart', 'target', 'best buy', 'home depot', 
                'lowes', 'macys', 'nordstrom', 'tjmaxx', 'tj maxx', 'marshalls', 
                'kohls', 'jcpenney', 'sears', 'old navy', 'gap', 'banana republic',
                # Department stores
                'bloomingdales', 'saks', 'neiman marcus', 'dillards',
                # Online retailers
                'ebay', 'etsy', 'wayfair', 'overstock', 'zappos',
                # Electronics
                'apple store', 'microsoft store', 'gamestop', 'radioshack',
                # Pharmacies when shopping
                'cvs pharmacy', 'walgreens', 'rite aid', 'duane reade',
                # Discount stores
                'dollar tree', 'dollar general', 'family dollar', 'five below',
                'big lots', '99 cent',
                # General retail
                'shopping', 'retail', 'store', 'mall', 'outlet', 'purchase'
            ],
            
            'Services': [
                # Utilities
                'electric', 'electricity', 'gas company', 'water', 'trash', 
                'sewer', 'utility', 'power company', 'energy',
                # Telecom
                'verizon', 'att', 'at&t', 't-mobile', 'sprint', 'comcast', 
                'xfinity', 'spectrum', 'cox communications', 'directv',
                'internet', 'phone', 'wireless', 'cable', 'satellite',
                # Subscriptions and streaming
                'netflix', 'spotify', 'hulu', 'disney plus', 'amazon prime',
                'apple music', 'youtube premium', 'subscription', 'monthly',
                # Professional services
                'insurance', 'medical', 'dental', 'doctor', 'hospital', 
                'clinic', 'pharmacy', 'lawyer', 'attorney', 'tax', 'accountant',
                # Personal services
                'haircut', 'salon', 'spa', 'gym', 'fitness', 'repair', 
                'maintenance', 'dry clean', 'car wash', 'oil change',
                # Financial services
                'bank fee', 'atm', 'service charge', 'maintenance fee',
                'paypal', 'venmo', 'zelle'
            ],
            
            'Entertainment': [
                # Movies and events
                'movie', 'theater', 'theatre', 'cinema', 'amc', 'regal', 
                'cinemark', 'fandango', 'concert', 'show', 'ticket', 'event',
                # Travel and transportation
                'uber', 'lyft', 'taxi', 'hotel', 'motel', 'resort', 'airbnb',
                'booking.com', 'expedia', 'flight', 'airline', 'airport', 
                'rental car', 'travel', 'vacation', 'trip',
                # Recreation
                'amusement', 'theme park', 'disneyland', 'disney world', 
                'six flags', 'zoo', 'museum', 'aquarium', 'sports', 'game', 
                'bowling', 'golf', 'mini golf',
                # Gaming and hobbies
                'steam', 'playstation', 'xbox', 'nintendo', 'twitch',
                # General entertainment
                'entertainment', 'recreation', 'fun', 'leisure', 'hobby'
            ]
        }
        
        # Check each category with enhanced matching
        for category, keywords in categories.items():
            for keyword in keywords:
                if keyword in text:
                    if debug:
                        print(f"   ✅ Keyword match: '{keyword}' -> {category}")
                    return category
        
        # Enhanced fallback - check for partial matches
        for category, keywords in categories.items():
            for keyword in keywords:
                # Split keyword and check if all parts are in text
                keyword_parts = keyword.split()
                if len(keyword_parts) > 1:
                    if all(part in text for part in keyword_parts):
                        if debug:
                            print(f"   ✅ Partial keyword match: '{keyword}' -> {category}")
                        return category
        
        if debug:
            print(f"   ❌ No match found -> Other")
        
        return 'Other'
    
    def _map_bank_category(self, bank_category):
        """Map bank-specific categories to our standard categories."""
        bank_category_lower = bank_category.lower()
        
        # Comprehensive mapping
        mappings = {
            # Groceries
            'supermarket': 'Groceries',
            'grocery': 'Groceries',
            'groceries': 'Groceries',
            
            # Food & Drinks  
            'restaurant': 'Food & Drinks',
            'dining': 'Food & Drinks',
            'food': 'Food & Drinks',
            'fast food': 'Food & Drinks',
            'coffee': 'Food & Drinks',
            
            # Shopping
            'shopping': 'Shopping',
            'merchandise': 'Shopping',
            'retail': 'Shopping',
            'clothing': 'Shopping',
            'department store': 'Shopping',
            
            # Services
            'gas': 'Services',
            'gasoline': 'Services',
            'automotive': 'Services',
            'utilities': 'Services',
            'bills': 'Services',
            'insurance': 'Services',
            'telecommunication': 'Services',
            'subscription': 'Services',
            
            # Entertainment
            'entertainment': 'Entertainment',
            'travel': 'Entertainment',
            'recreation': 'Entertainment',
            'hotel': 'Entertainment',
            'airline': 'Entertainment'
        }
        
        for pattern, category in mappings.items():
            if pattern in bank_category_lower:
                return category
        
        return 'Other'
    
    def _categorize_transaction(self, description, memo='', original_category=''):
        """Enhanced categorization with comprehensive merchant matching."""
        
        # Handle NaN values safely
        if pd.isna(description):
            description = ''
        if pd.isna(memo):
            memo = ''
        if pd.isna(original_category):
            original_category = ''
        
        description = str(description).strip()
        memo = str(memo).strip()
        original_category = str(original_category).strip()
        
        # Debug logging for troubleshooting
        debug_this = hasattr(self, '_debug_count') and self._debug_count < 5
        if not hasattr(self, '_debug_count'):
            self._debug_count = 0
        
        if debug_this:
            print(f"\n🔍 Categorizing transaction #{self._debug_count + 1}:")
            print(f"   Description: '{description}'")
            if description in ['Unknown Transaction', '', 'Sale', 'Purchase', 'Transaction']:
                print(f"   ⚠️  WARNING: Generic/missing description detected!")
        
        self._debug_count += 1
        
        # CRITICAL: Check if we have a real merchant description
        if not description or description in ['Unknown Transaction', 'Sale', 'Purchase', 'Payment', 'Transaction']:
            # Try to use original category as fallback
            if original_category:
                return self._map_bank_category(original_category)
            return 'Other'
        
        # Clean and prepare text for matching
        text = description.lower()
        
        # Remove common prefixes and suffixes but preserve merchant name
        text = self._clean_merchant_text(text)
        
        # Comprehensive merchant database with specific patterns
        merchant_categories = {
            'Groceries': {
                # Major chains
                'whole foods', 'wholefoods', 'whole fds', 'wholefds',
                'kroger', 'ralphs', 'fred meyer', 'qfc', 'smiths', 'king soopers',
                'safeway', 'vons', 'pavilions', 'albertsons', 'jewel osco',
                'publix', 'wegmans', 'harris teeter', 'heb', 'h-e-b',
                'trader joe', 'traderjoe', 'aldi', 'lidl',
                'sprouts', 'fresh market', 'food lion', 'giant eagle',
                'stop & shop', 'stop and shop', 'shoprite', 'acme',
                'meijer', 'winn dixie', 'piggly wiggly',
                # Warehouse stores for groceries
                'costco', 'sams club', 'sam\'s club', 'bjs wholesale', 'bj\'s',
                # Generic patterns
                'grocery', 'supermarket', 'market', 'foods', 'produce'
            },
            
            'Food & Drinks': {
                # Coffee shops
                'starbucks', 'sbux', 'dunkin', 'peets', 'peet\'s',
                'coffee bean', 'caribou', 'tim hortons', 'dutch bros',
                # Fast food
                'mcdonald', 'mcdonalds', 'mcd', 'burger king', 'wendys', 'wendy\'s',
                'subway', 'taco bell', 'kfc', 'popeyes', 'chick-fil-a', 'chickfila',
                'chipotle', 'qdoba', 'five guys', 'in-n-out', 'in n out',
                'shake shack', 'whataburger', 'sonic', 'arbys', 'arby\'s',
                'jack in the box', 'carl\'s jr', 'hardees', 'white castle',
                # Pizza
                'pizza hut', 'dominos', 'domino\'s', 'papa johns', 'papa john\'s',
                'little caesars', 'papa murphy', 'blaze pizza', 'mod pizza',
                # Casual dining
                'panera', 'olive garden', 'red lobster', 'applebees', 'applebee\'s',
                'chilis', 'chili\'s', 'outback', 'texas roadhouse', 'longhorn',
                'cheesecake factory', 'pf changs', 'pf chang\'s', 'buffalo wild wings',
                # Delivery services
                'doordash', 'door dash', 'uber eats', 'ubereats', 'grubhub',
                'postmates', 'seamless', 'caviar', 'delivery',
                # Generic patterns
                'restaurant', 'cafe', 'coffee', 'bar', 'grill', 'kitchen',
                'diner', 'bakery', 'pizzeria', 'sushi', 'thai', 'chinese',
                'mexican', 'indian', 'italian', 'bbq', 'barbecue', 'steakhouse'
            },
            
            'Shopping': {
                # Online retail
                'amazon', 'amzn', 'amazn', 'prime now',
                'ebay', 'etsy', 'alibaba', 'wish', 'wayfair',
                # Department stores
                'target', 'tgt', 'walmart', 'wal-mart', 'wmt',
                'macys', 'macy\'s', 'nordstrom', 'bloomingdales', 'saks',
                'jcpenney', 'jc penney', 'kohls', 'kohl\'s', 'dillards',
                # Electronics
                'best buy', 'bestbuy', 'apple store', 'apple.com', 'microsoft',
                'gamestop', 'game stop', 'newegg', 'b&h photo', 'b and h',
                # Clothing
                'gap', 'old navy', 'banana republic', 'h&m', 'h and m',
                'zara', 'forever 21', 'forever21', 'uniqlo', 'nike',
                'adidas', 'foot locker', 'footlocker', 'finish line',
                # Home improvement
                'home depot', 'homedepot', 'lowes', 'lowe\'s', 'menards',
                'ace hardware', 'true value', 'harbor freight',
                # Pharmacy/convenience
                'cvs', 'walgreens', 'rite aid', 'duane reade',
                # Discount stores
                'tjmaxx', 'tj maxx', 'marshalls', 'ross', 'burlington',
                'dollar tree', 'dollar general', 'family dollar', 'five below',
                # Generic patterns
                'store', 'shop', 'mart', 'retail', 'outlet', 'mall'
            },
            
            'Services': {
                # Streaming/subscriptions
                'netflix', 'hulu', 'disney+', 'disney plus', 'hbo',
                'spotify', 'apple music', 'youtube', 'amazon prime',
                'audible', 'kindle', 'xbox', 'playstation', 'nintendo',
                # Utilities
                'electric', 'gas company', 'water', 'utility', 'utilities',
                'comcast', 'xfinity', 'spectrum', 'cox', 'directv',
                'verizon', 'vzw', 'at&t', 'att', 't-mobile', 'tmobile', 'sprint',
                # Insurance/Financial
                'insurance', 'geico', 'progressive', 'allstate', 'state farm',
                'bank', 'credit union', 'chase', 'wells fargo', 'citi',
                # Health
                'pharmacy', 'medical', 'dental', 'doctor', 'hospital',
                'clinic', 'health', 'therapy', 'lab', 'radiology',
                # Auto
                'gas station', 'shell', 'chevron', 'exxon', 'mobil', 'bp',
                'valero', 'citgo', 'sunoco', '76', 'arco', 'speedway',
                'auto', 'car wash', 'jiffy lube', 'oil change', 'tire',
                # Personal services  
                'salon', 'barber', 'spa', 'massage', 'nail', 'hair',
                'gym', 'fitness', 'yoga', 'pilates', 'crossfit',
                'dry clean', 'laundry', 'cleaners',
                # Generic patterns
                'service', 'repair', 'maintenance', 'subscription'
            },
            
            'Entertainment': {
                # Movies/Events
                'amc', 'regal', 'cinemark', 'movie', 'theater', 'theatre',
                'cinema', 'imax', 'fandango', 'ticketmaster', 'stubhub',
                'concert', 'show', 'event', 'festival', 'fair',
                # Travel
                'uber', 'lyft', 'taxi', 'cab', 'airport', 'airline',
                'united', 'american air', 'delta', 'southwest', 'jetblue',
                'hotel', 'motel', 'hilton', 'marriott', 'hyatt', 'holiday inn',
                'airbnb', 'vrbo', 'booking.com', 'expedia', 'priceline',
                'rental car', 'hertz', 'enterprise', 'avis', 'budget',
                # Recreation
                'disney', 'universal', 'six flags', 'theme park', 'amusement',
                'zoo', 'aquarium', 'museum', 'park', 'recreation',
                'bowling', 'golf', 'mini golf', 'arcade', 'dave & busters',
                'sporting', 'stadium', 'arena', 'ticketmaster',
                # Gaming
                'steam', 'epic games', 'twitch', 'gaming', 'esports',
                # Generic patterns
                'entertainment', 'fun', 'leisure', 'hobby', 'sport'
            }
        }
        
        # Check each category for matches
        for category, keywords in merchant_categories.items():
            for keyword in keywords:
                if keyword in text:
                    if debug_this:
                        print(f"   ✅ Match found: '{keyword}' -> {category}")
                    return category
        
        # Check original bank category as secondary fallback
        if original_category:
            mapped = self._map_bank_category(original_category)
            if mapped != 'Other':
                if debug_this:
                    print(f"   ✅ Bank category mapped: '{original_category}' -> {mapped}")
                return mapped
        
        if debug_this:
            print(f"   ❌ No match found -> Other")
        
        return 'Other'
    
    def _clean_transaction_text(self, text):
        """Clean transaction text for better keyword matching."""
        import re
        
        # Remove common prefixes/suffixes that don't help categorization
        text = re.sub(r'^(tst\*|pos|pending|auth|)', text)
        text = re.sub(r'\s*#\d+.*$', '', text)  # Remove store numbers
        text = re.sub(r'\s*\*\d+.*$', '', text)  # Remove reference numbers
        text = re.sub(r'\s+', ' ', text)  # Normalize spaces
        
        return text.strip()
    
    def _clean_merchant_text(self, text):
        """Clean merchant text while preserving the actual merchant name."""
        import re
        
        # Remove common transaction prefixes
        prefixes_to_remove = [
            'tst\\*', 'sq \\*', 'pos ', 'pos\\*', 'pending ', 'auth ',
            'check card ', 'debit card ', 'credit card ', 'purchase ',
            'payment ', 'direct debit ', 'recurring ', 'subscription '
        ]
        
        for prefix in prefixes_to_remove:
            text = re.sub(f'^{prefix}', '', text, flags=re.IGNORECASE)
        
        # Remove store numbers and reference codes but keep merchant name
        text = re.sub(r'#\d{3,}.*$', '', text)  # Remove #123... at end
        text = re.sub(r'\s+\d{10,}$', '', text)  # Remove long numbers at end
        text = re.sub(r'\s+[A-Z]{2}\s*$', '', text)  # Remove state codes at end
        
        # Clean up extra spaces
        text = re.sub(r'\s+', ' ', text).strip()
        
        return text
    
    def _clean_merchant_name(self, description):
        """Clean merchant names by removing store numbers and extra data."""
        if not description:
            return description
        
        description = str(description).upper()
        
        # Common merchant cleaning patterns
        merchant_patterns = {
            # Amazon variants
            'AMAZON': ['AMAZON MKTPL', 'AMAZON.COM', 'AMAZON WEB', 'AMAZON PRIME', 'AMZN MKTP'],
            
            # Costco variants  
            'COSTCO': ['COSTCO WHSE', 'COSTCO GAS', 'COSTCO WHOLESALE'],
            
            # Walmart variants
            'WALMART': ['WALMART SUPERCENTER', 'WALMART STORE', 'WAL-MART'],
            
            # Target variants
            'TARGET': ['TARGET STORE', 'TARGET T-'],
            
            # Starbucks variants
            'STARBUCKS': ['STARBUCKS STORE', 'STARBUCKS COFFEE'],
            
            # McDonald's variants
            'MCDONALDS': ['MCDONALD\'S F', 'MCDONALDS F'],
            
            # CVS variants
            'CVS': ['CVS/PHARMACY', 'CVS PHARMACY'],
            
            # Home Depot variants
            'HOME DEPOT': ['HOME DEPOT #', 'THE HOME DEPOT'],
            
            # Chipotle variants
            'CHIPOTLE': ['CHIPOTLE MEXICAN', 'CHIPOTLE #'],
            
            # Shell variants
            'SHELL': ['SHELL OIL', 'SHELL SERVICE'],
            
            # Chase variants (for payments)
            'CHASE': ['CHASE CREDIT CRD', 'CHASE AUTO'],
        }
        
        # Check for merchant patterns first
        for clean_name, patterns in merchant_patterns.items():
            for pattern in patterns:
                if pattern in description:
                    return clean_name
        
        # Generic cleaning - remove everything after "*" or "#" 
        if '*' in description:
            description = description.split('*')[0].strip()
        if '#' in description:
            description = description.split('#')[0].strip()
        
        # Remove common suffixes
        suffixes_to_remove = [
            ' STORE', ' #', ' WHSE', ' GAS', ' SUPERCENTER', ' WHOLESALE',
            ' PHARMACY', ' COFFEE', ' MEXICAN GRILL', ' SERVICE STATION'
        ]
        
        for suffix in suffixes_to_remove:
            if description.endswith(suffix):
                description = description[:-len(suffix)].strip()
        
        # Remove trailing numbers and special characters
        description = re.sub(r'\s+\d+$', '', description)  # Remove trailing numbers
        description = re.sub(r'[^A-Za-z\s&\'-]', ' ', description)  # Keep only letters, spaces, &, ', -
        description = re.sub(r'\s+', ' ', description).strip()  # Clean up multiple spaces
        
        return description or "UNKNOWN MERCHANT"
    
    # NEW: Reset category spending functionality
    def reset_category_spending(self, target_month=None):
        """
        Reset category spending for a specific month or current month.
        
        Args:
            target_month: Month to reset in YYYY-MM format, or None for current month
        """
        if target_month is None:
            target_month = datetime.now().strftime('%Y-%m')
        
        # Validate month format
        try:
            datetime.strptime(target_month, '%Y-%m')
        except ValueError:
            print(f"Invalid month format: {target_month}. Use YYYY-MM format.")
            return False
        
        # Initialize month if not exists
        if target_month not in self.category_spending:
            self.category_spending[target_month] = {}
        
        # Reset all categories to 0
        categories = ['Shopping', 'Food & Drinks', 'Services', 'Entertainment', 'Groceries', 'Other']
        for category in categories:
            self.category_spending[target_month][category] = 0.0
        
        # Save changes
        self.save_category_spending()
        
        print(f"✅ Reset category spending for {target_month}")
        print("All categories set to $0.00:")
        for category in categories:
            print(f"  {category}: $0.00")
        
        return True
    
    # Additional helper method for testing categorization
    def test_categorization_debug(self, test_descriptions):
        """Enhanced test method with detailed output."""
        print(f"\n🧪 ENHANCED CATEGORIZATION TEST")
        print("=" * 60)
        
        # Reset debug counter
        self._debug_count = 0
        
        for i, desc in enumerate(test_descriptions, 1):
            print(f"\n{i}. Testing: '{desc}'")
            category = self._categorize_transaction(desc)
            print(f"   Result: {category}")
            
            # Show what the cleaned text looks like
            cleaned = self._clean_transaction_text(desc.lower())
            if cleaned != desc.lower():
                print(f"   Cleaned text: '{cleaned}'")
        
        print("=" * 60)
        
        # Test with some known problematic cases
        print(f"\n🔍 TESTING KNOWN PROBLEM CASES:")
        problem_cases = [
            "Unknown Transaction",
            "",
            "Sale",
            "Purchase",
            "WHOLE FOODS MARKET #123",
            "STARBUCKS STORE #456",
            "AMAZON.COM AMZN.COM/BILL"
        ]
        
        for case in problem_cases:
            category = self._categorize_transaction(case)
            status = "✅" if category != "Other" else "❌"
            print(f"   {status} '{case}' -> {category}")
    
    # Filter transactions to current month only
    def _filter_to_current_month(self, df):
        """
        Filter DataFrame to only include transactions from the current month.
        
        Args:
            df: DataFrame with transaction data
            
        Returns:
            DataFrame with only current month transactions
        """
        if df.empty:
            return df
        
        # Ensure we have a date column
        if 'Transaction Date' not in df.columns:
            print("⚠️  Warning: No 'Transaction Date' column found, cannot filter by month")
            return df
        
        try:
            # Parse transaction dates
            df = df.copy()
            df['parsed_date'] = pd.to_datetime(df['Transaction Date'], errors='coerce')
            
            # Remove rows where date parsing failed
            invalid_dates = df['parsed_date'].isna().sum()
            if invalid_dates > 0:
                print(f"⚠️  Warning: {invalid_dates} transactions had invalid dates")
            
            df = df.dropna(subset=['parsed_date'])
            
            if df.empty:
                print("⚠️  Warning: No valid dates found in transaction data")
                return df
            
            # Show date range of transactions
            min_date = df['parsed_date'].min()
            max_date = df['parsed_date'].max()
            print(f"📅 Transaction date range: {min_date.strftime('%Y-%m-%d')} to {max_date.strftime('%Y-%m-%d')}")
            
            # Get current month start and end
            now = datetime.now()
            month_start = datetime(now.year, now.month, 1)
            if now.month == 12:
                month_end = datetime(now.year + 1, 1, 1) - timedelta(days=1)
            else:
                month_end = datetime(now.year, now.month + 1, 1) - timedelta(days=1)
            
            print(f"📅 Current month filter: {month_start.strftime('%Y-%m-%d')} to {month_end.strftime('%Y-%m-%d')}")
            
            # Filter to current month
            current_month_df = df[
                (df['parsed_date'] >= month_start) & 
                (df['parsed_date'] <= month_end)
            ].copy()
            
            # Remove the helper column
            current_month_df = current_month_df.drop('parsed_date', axis=1)
            
            return current_month_df
            
        except Exception as e:
            print(f"❌ Error filtering to current month: {e}")
            print("Using all transactions without date filtering")
            return df
    
    # UPDATED: Modified to use current month filtering
    def _update_category_spending(self, df, use_current_month_only=True):
        """Update category spending based on transaction data with detailed logging."""
        if df.empty:
            print("⚠️  No transaction data to process for category spending")
            return
        
        current_month = datetime.now().strftime('%Y-%m')
        original_count = len(df)
        
        print(f"\n📊 PROCESSING CATEGORY SPENDING")
        print(f"   Total transactions: {original_count}")
        print(f"   Current month filter: {use_current_month_only}")
        print(f"   Target month: {current_month}")
        
        # Reset debug counter for categorization
        self._debug_count = 0
        
        # Filter to current month only if requested
        if use_current_month_only:
            df = self._filter_to_current_month(df)
            if df.empty:
                print(f"⚠️  No current month ({current_month}) transactions found")
                return
            filtered_count = len(df)
            print(f"   After filtering: {filtered_count} transactions")
        else:
            print(f"   Using all months: {original_count} transactions")
        
        # Initialize month if not exists
        if current_month not in self.category_spending:
            self.category_spending[current_month] = {
                'Shopping': 0.0,
                'Food & Drinks': 0.0,
                'Services': 0.0,
                'Entertainment': 0.0,
                'Groceries': 0.0,
                'Other': 0.0
            }
        
        # Process spending transactions only
        spending_df = df[df['Amount'] < 0].copy()
        if spending_df.empty:
            print("⚠️  No spending transactions found (no negative amounts)")
            return
        
        print(f"   Spending transactions: {len(spending_df)}")
        
        # Categorize transactions with debugging
        print(f"\n🏷️  CATEGORIZING TRANSACTIONS...")
        spending_df['custom_category'] = spending_df.apply(
            lambda row: self._categorize_transaction(
                row.get('Description', ''), 
                row.get('Memo', ''),
                row.get('Category', '')
            ), axis=1
        )
        
        # Calculate absolute amounts
        spending_df['amount_abs'] = spending_df['Amount'].abs()
        
        # Group by category
        category_totals = spending_df.groupby('custom_category')['amount_abs'].sum()
        
        print(f"\n📈 CATEGORY TOTALS:")
        total_spending = 0
        
        # Update and display category spending
        for category in self.category_spending[current_month].keys():
            amount = float(category_totals.get(category, 0.0))
            old_amount = self.category_spending[current_month][category]
            self.category_spending[current_month][category] = amount
            total_spending += amount
            
            if amount > 0:
                print(f"   {category}: ${amount:,.2f} ({category_totals.get(category, 0)} transactions)")
            else:
                print(f"   {category}: $0.00")
        
        print(f"   TOTAL: ${total_spending:,.2f}")
        
        # Save the updated category spending
        self.save_category_spending()
        print(f"✅ Category spending saved for {current_month}")

    # Add a method to manually test categorization
    def test_categorization_manual(self, test_descriptions):
        """Manual test method for categorization."""
        print(f"\n🧪 MANUAL CATEGORIZATION TEST")
        print("=" * 50)
        
        for i, desc in enumerate(test_descriptions, 1):
            category = self._categorize_transaction(desc)
            print(f"{i}. '{desc}' → {category}")
        
        print("=" * 50)
    
    # Time Period Analysis Methods
    def analyze_period(self, csv_files, start_date=None, end_date=None, group_by='month'):
        """Analyze spending over a time period using transaction files."""
        if not csv_files:
            print("No CSV files provided")
            return None, {}
        
        # Process all CSV files
        all_dfs = []
        for file_path in csv_files:
            df = self._process_csv_file(file_path)
            if not df.empty:
                all_dfs.append(df)
        
        if not all_dfs:
            print("No valid transaction data found")
            return None, {}
        
        # Combine all data
        combined_df = pd.concat(all_dfs, ignore_index=True) if len(all_dfs) > 1 else all_dfs[0]
        
        # Create analyzer and run analysis
        analyzer = TimePeriodAnalyzer(self)
        period_analysis = analyzer.analyze_time_period(
            combined_df, start_date, end_date, group_by
        )
        
        return analyzer, period_analysis
    
    def show_period_summary(self, csv_files, start_date=None, end_date=None, 
                           group_by='month', show_categories=True, compare=False, 
                           trend_category=None, store_as=None):
        """Show comprehensive period analysis summary."""
        analyzer, period_analysis = self.analyze_period(csv_files, start_date, end_date, group_by)
        
        if not period_analysis:
            return None, {}
        
        # Display main analysis
        analyzer.display_period_analysis(period_analysis, show_categories)
        
        # Show comparisons if requested
        if compare:
            analyzer.compare_periods(period_analysis, 'month_over_month')
        
        # Show trend analysis if requested
        if trend_category or trend_category is None:  # None means total spending trend
            analyzer.trend_analysis(period_analysis, trend_category)
        
        # Store analysis if name provided
        if store_as:
            metadata = {
                'start_date': start_date or 'All data',
                'end_date': end_date or 'All data',
                'group_by': group_by,
                'file_count': len(csv_files)
            }
            analyzer.store_period_analysis(store_as, period_analysis, metadata)
        
        return analyzer, period_analysis
    
    # Original CreditCardTracker methods continue here...
    def add_card(self, name, credit_limit, statement_date, due_date, description="", balance_due=0.0, current_balance=0.0):
        """Add a new credit card to track."""
        self.cards[name] = {
            'credit_limit': float(credit_limit),
            'statement_date': int(statement_date),  # Day of month (e.g., 15 for 15th)
            'due_date': int(due_date),  # Day of month (e.g., 12 for 12th)
            'description': description,
            'current_balance': float(current_balance),  # New spending since last statement
            'balance_due': float(balance_due),  # Balance from previous statement
            'last_updated': datetime.now().isoformat(),
            'last_statement_reset': datetime.now().isoformat()
        }
        self.save_cards()
        print(f"Added credit card: {name}")
        if current_balance > 0:
            print(f"  Current balance: ${current_balance:,.2f}")
        if balance_due > 0:
            print(f"  Balance due: ${balance_due:,.2f}")
    
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
        
        if 'current_balance' in kwargs:
            card['current_balance'] = float(kwargs['current_balance'])
            updated_fields.append(f"current balance: ${card['current_balance']:,.2f}")
        
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
    
    def set_category_budgets(self, **budgets):
        """Set monthly budgets for spending categories."""
        current_month = datetime.now().strftime('%Y-%m')
        valid_categories = ['Shopping', 'Food & Drinks', 'Services', 'Entertainment', 'Groceries', 'Other']
        
        if current_month not in self.category_budgets:
            self.category_budgets[current_month] = {}
        
        updated_budgets = []
        for category, budget in budgets.items():
            if category in valid_categories:
                self.category_budgets[current_month][category] = float(budget)
                updated_budgets.append(f"{category}: ${budget:,.2f}")
        
        if updated_budgets:
            self.save_category_budgets()
            print(f"Set category budgets for {current_month}:")
            for budget_info in updated_budgets:
                print(f"  {budget_info}")
        else:
            print("No valid categories provided. Valid categories:", valid_categories)
    
    def get_current_category_budgets(self):
        """Get category budgets for current month."""
        current_month = datetime.now().strftime('%Y-%m')
        return self.category_budgets.get(current_month, {})
    
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
    
    def process_transactions_auto(self, csv_files, card_patterns=None, use_current_month_only=False):
        """
        Automatically process transaction files and update card balances.
        
        Args:
            csv_files: List of CSV file paths
            card_patterns: Dictionary of card name patterns for auto-detection
            use_current_month_only: If True, only count current month for category budgets
        """
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
        
        total_transactions_processed = 0
        
        # Process each file and try to match to cards
        for file_path in csv_files:
            file_name = Path(file_path).name.lower()
            df = self._process_csv_file(file_path)
            
            if df.empty:
                print(f"No valid data in {file_path}")
                continue
            
            total_transactions_processed += len(df)
            
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
            
            # Calculate new spending since last statement (all transactions for card balance)
            new_spending = abs(df[df['Amount'] < 0]['Amount'].sum())
            
            # Update category spending based on transactions
            # Use the parameter to control month filtering
            self._update_category_spending(df, use_current_month_only=use_current_month_only)
            
            # Update the card's current balance
            old_balance = self.cards[matched_card]['current_balance']
            self.cards[matched_card]['current_balance'] = new_spending
            self.cards[matched_card]['last_updated'] = datetime.now().isoformat()
            
            print(f"Updated {matched_card}: ${old_balance:,.2f} → ${new_spending:,.2f} (from {len(df)} transactions)")
        
        print(f"\n📊 Processing Summary:")
        print(f"   Total transactions: {total_transactions_processed}")
        print(f"   Category filtering: {'Current month only' if use_current_month_only else 'All months'}")
        
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
    
    def _get_category_spending(self):
        """Get current spending by category across all cards."""
        current_month = datetime.now().strftime('%Y-%m')
        return self.category_spending.get(current_month, {
            'Shopping': 0.0,
            'Food & Drinks': 0.0,
            'Services': 0.0,
            'Entertainment': 0.0,
            'Groceries': 0.0,
            'Other': 0.0
        })
    
    def show_summary(self):
        """Display current spending summary for all cards."""
        if not self.cards:
            print("No credit cards configured")
            return
        
        limits = self.get_current_spending_limits()
        budgets = self.get_current_category_budgets()
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
        spending_status = ""
        
        if limits['soft_limit'] > 0:
            # Left to spend = soft limit - total new spending
            left_to_spend = limits['soft_limit'] - total_new_spending
            
            # Determine status indicators
            if limits['hard_limit'] > 0 and total_new_spending > limits['hard_limit']:
                spending_status = " 🚨 CRITICAL"
            elif total_new_spending > limits['soft_limit']:
                spending_status = " ⚠️ CAUTION"
        else:
            # No spending limits set, show available credit instead
            left_to_spend = total_available
        
        print(f"{'Left to Spend':<15} $ {left_to_spend:>10,.2f}{spending_status}")
        print("-" * 30)
        print(f"**New Spending  $ {total_new_spending:>10,.2f}**")
        
        if total_balance_due > 0:
            print(f"  Balance Due   $ {total_balance_due:>10,.2f}")
            print(f"  Total Owed    $ {(total_new_spending + total_balance_due):>10,.2f}")
        
        # Show category budget status if budgets are set
        if budgets:
            print("\n" + "="*50)
            print("CATEGORY BUDGET STATUS")
            print("="*50)
            
            # Get category spending from transaction analysis
            category_spending = self._get_category_spending()
            
            for category in ['Shopping', 'Food & Drinks', 'Services', 'Entertainment', 'Groceries', 'Other']:
                budget = budgets.get(category, 0)
                spent = category_spending.get(category, 0)
                
                if budget > 0:
                    remaining = budget - spent
                    status = ""
                    
                    if remaining < 0:
                        status = " 🚨 OVER"
                    elif remaining < budget * 0.1:  # Less than 10% remaining
                        status = " ⚠️ LOW"
                    
                    print(f"{category:<15} ${spent:>8,.2f} / ${budget:>8,.2f} (${remaining:>8,.2f}){status}")
        
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
                status = "⚠️ URGENT"
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
    
    def save_category_budgets(self):
        """Save category budgets to encrypted file."""
        try:
            json_data = json.dumps(self.category_budgets, indent=2)
            encrypted_data = self.cipher_suite.encrypt(json_data.encode())
            
            with open(self.budgets_file, 'wb') as f:
                f.write(encrypted_data)
        except Exception as e:
            print(f"Error saving category budgets: {e}")
    
    def load_category_budgets(self):
        """Load category budgets from encrypted file."""
        try:
            if not Path(self.budgets_file).exists():
                return
            
            with open(self.budgets_file, 'rb') as f:
                encrypted_data = f.read()
            
            decrypted_data = self.cipher_suite.decrypt(encrypted_data).decode()
            self.category_budgets = json.loads(decrypted_data)
        except Exception as e:
            print(f"Note: Could not load category budgets ({e}). Starting fresh.")
            self.category_budgets = {}
    
    def save_category_spending(self):
        """Save category spending to encrypted file."""
        try:
            json_data = json.dumps(self.category_spending, indent=2)
            encrypted_data = self.cipher_suite.encrypt(json_data.encode())
            
            with open(self.spending_file, 'wb') as f:
                f.write(encrypted_data)
        except Exception as e:
            print(f"Error saving category spending: {e}")
    
    def load_category_spending(self):
        """Load category spending from encrypted file."""
        try:
            if not Path(self.spending_file).exists():
                return
            
            with open(self.spending_file, 'rb') as f:
                encrypted_data = f.read()
            
            decrypted_data = self.cipher_suite.decrypt(encrypted_data).decode()
            self.category_spending = json.loads(decrypted_data)
        except Exception as e:
            print(f"Note: Could not load category spending ({e}). Starting fresh.")
            self.category_spending = {}

def handle_period_analysis_commands(args, tracker):
    """Handle time period analysis commands."""
    
    # Handle list stored analyses
    if args.list_analyses:
        analyzer = TimePeriodAnalyzer(tracker)
        analyzer.list_stored_analyses()
        return True
    
    # Handle load stored analysis
    if args.load_analysis:
        analyzer = TimePeriodAnalyzer(tracker)
        stored_analysis = analyzer.load_stored_analysis(args.load_analysis)
        if stored_analysis:
            print(f"\n=== STORED ANALYSIS: {args.load_analysis} ===")
            analyzer.display_period_analysis(stored_analysis, True)
            if args.compare:
                analyzer.compare_periods(stored_analysis)
            if args.trend:
                trend_cat = None if args.trend.lower() == 'total' else args.trend
                analyzer.trend_analysis(stored_analysis, trend_cat)
        return True
    
    # Handle compare analyses
    if args.compare_analyses:
        analyzer = TimePeriodAnalyzer(tracker)
        name1, name2 = args.compare_analyses
        
        analysis1 = analyzer.load_stored_analysis(name1)
        analysis2 = analyzer.load_stored_analysis(name2)
        
        if analysis1 and analysis2:
            print(f"\n=== COMPARISON: {name1} vs {name2} ===")
            periods1 = set(analysis1.keys())
            periods2 = set(analysis2.keys())
            common_periods = periods1.intersection(periods2)
            
            if common_periods:
                print(f"\nCommon periods found: {len(common_periods)}")
                for period in sorted(common_periods):
                    total1 = analysis1[period]['total_spending']
                    total2 = analysis2[period]['total_spending']
                    diff = total1 - total2
                    print(f"{period}: ${total1:,.2f} vs ${total2:,.2f} (${diff:+,.2f})")
            else:
                print("No overlapping periods found between analyses")
        return True
    
    # Handle period analysis
    if args.analyze_period:
        show_categories = args.show_categories and not args.no_categories
        trend_category = None if not args.trend else (None if args.trend.lower() == 'total' else args.trend)
        
        analyzer, period_analysis = tracker.show_period_summary(
            csv_files=args.analyze_period,
            start_date=args.start_date,
            end_date=args.end_date,
            group_by=args.group_by,
            show_categories=show_categories,
            compare=args.compare,
            trend_category=trend_category,
            store_as=args.store_analysis
        )
        return True
    
    return False

def main():
    """Enhanced main function with time period analysis support."""
    parser = argparse.ArgumentParser(description='Enhanced Credit Card Spending Tracker with Time Period Analysis')
    
    # Original card management arguments
    parser.add_argument('--add-card', nargs='+', 
                       help='Add new card: name credit_limit statement_date due_date [balance_due] [current_balance]')
    parser.add_argument('--add-card-desc', help='Description for the card being added')
    parser.add_argument('--update-card', nargs='+', 
                       help='Update card: name [--credit-limit X] [--statement-date X] [--due-date X] [--balance-due X] [--current-balance X]')
    parser.add_argument('--remove-card', help='Remove a credit card')
    parser.add_argument('--list-cards', action='store_true', help='List all configured cards')
    
    # Balance management
    parser.add_argument('--update-balance', nargs=3, metavar=('NAME', 'AMOUNT', 'TYPE'),
                       help='Update card balance: card_name amount type(current/due)')
    parser.add_argument('--reset', choices=['current', 'due', 'all'], 
                       help='Reset balances: current, due, or all')
    parser.add_argument('--reset-statement', nargs='?', const='all',
                       help='Reset statement period for card (or all cards)')
    
    # Category spending reset - use 'const' for default behavior
    parser.add_argument('--reset-category-spending', nargs='?', const='current', metavar='YYYY-MM',
                       help='Reset category spending for current month or specified month (YYYY-MM)')
    
    # Spending limits and budgets
    parser.add_argument('--set-limits', nargs=2, metavar=('SOFT', 'HARD'),
                       help='Set monthly spending limits: soft_limit hard_limit')
    parser.add_argument('--set-budgets', nargs='+', metavar='CATEGORY:AMOUNT',
                       help='Set category budgets: Shopping:500 "Food & Drinks":300 Services:200')
    
    # Transaction processing
    parser.add_argument('--process-auto', nargs='+', metavar='CSV_FILE',
                       help='Auto-process transaction files to update balances')
    parser.add_argument('--update-categories', nargs='+', metavar='CSV_FILE',
                       help='Update category spending from transaction files (for budget tracking)')
    
    # NEW: Option to disable current month filtering
    parser.add_argument('--all-months', action='store_true',
                       help='Include all months when updating categories (not just current month)')
    
    # Display
    parser.add_argument('--summary', action='store_true', help='Show spending summary')
    parser.add_argument('--due-dates', action='store_true', help='Show upcoming due dates')
    parser.add_argument('--category', help='Analyze specific category in detail')
    
    # Time period analysis commands
    period_group = parser.add_argument_group('Time Period Analysis')
    
    period_group.add_argument('--analyze-period', nargs='+', metavar='CSV_FILE',
                             help='Analyze transactions over time period from CSV files')
    
    period_group.add_argument('--start-date', metavar='YYYY-MM-DD',
                             help='Start date for period analysis (default: all data)')
    
    period_group.add_argument('--end-date', metavar='YYYY-MM-DD',
                             help='End date for period analysis (default: all data)')
    
    period_group.add_argument('--group-by', choices=['month', 'quarter', 'year'], 
                             default='month',
                             help='Group analysis by time period (default: month)')
    
    period_group.add_argument('--show-categories', action='store_true', default=True,
                             help='Show category breakdown (default: True)')
    
    period_group.add_argument('--no-categories', action='store_true',
                             help='Hide category breakdown')
    
    period_group.add_argument('--compare', action='store_true',
                             help='Show period-over-period comparison')
    
    period_group.add_argument('--trend', metavar='CATEGORY',
                             help='Show trend analysis for category (or "total" for all spending)')
    
    period_group.add_argument('--store-analysis', metavar='NAME',
                             help='Store this analysis with given name')
    
    # Historical data management
    hist_group = parser.add_argument_group('Historical Analysis')
    
    hist_group.add_argument('--list-analyses', action='store_true',
                           help='List stored historical analyses')
    
    hist_group.add_argument('--load-analysis', metavar='NAME',
                           help='Load and display stored analysis')
    
    hist_group.add_argument('--compare-analyses', nargs=2, metavar=('NAME1', 'NAME2'),
                           help='Compare two stored analyses')
    
    args = parser.parse_args()
    tracker = CreditCardTracker()
    
    # Handle time period analysis commands first
    if handle_period_analysis_commands(args, tracker):
        return
    
    # Handle original commands
    if args.add_card:
        name, limit, stmt_date, due_date = args.add_card[:4]
        balance_due = float(args.add_card[4]) if len(args.add_card) > 4 else 0.0
        current_balance = float(args.add_card[5]) if len(args.add_card) > 5 else 0.0
        description = args.add_card_desc or ""
        tracker.add_card(name, limit, stmt_date, due_date, description, balance_due, current_balance)
    
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
            elif update_args[i] == '--current-balance' and i + 1 < len(update_args):
                kwargs['current_balance'] = update_args[i + 1]
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
    
    # Handle category spending reset properly
    elif args.reset_category_spending is not None:
        if args.reset_category_spending == 'current':
            # Default behavior - reset current month
            tracker.reset_category_spending()
        else:
            # Specific month provided
            tracker.reset_category_spending(args.reset_category_spending)
    
    elif args.set_limits:
        soft_limit, hard_limit = args.set_limits
        tracker.set_spending_limits(float(soft_limit), float(hard_limit))
    
    elif args.set_budgets:
        budgets = {}
        for budget_str in args.set_budgets:
            if ':' in budget_str:
                category, amount = budget_str.split(':', 1)
                try:
                    budgets[category.strip()] = float(amount.strip())
                except ValueError:
                    print(f"Invalid budget amount for {category}: {amount}")
        
        if budgets:
            tracker.set_category_budgets(**budgets)
    
    elif args.process_auto:
        tracker.process_transactions_auto(args.process_auto)
    
    elif args.update_categories:
        # Process files to update category spending only
        all_dfs = []
        for file_path in args.update_categories:
            df = tracker._process_csv_file(file_path)
            if not df.empty:
                all_dfs.append(df)
        
        if all_dfs:
            combined_df = pd.concat(all_dfs, ignore_index=True) if len(all_dfs) > 1 else all_dfs[0]
            # FIXED: Use --all-months flag to control filtering
            use_current_month_only = not args.all_months
            tracker._update_category_spending(combined_df, use_current_month_only=use_current_month_only)
            
            filter_msg = " (current month only)" if use_current_month_only else " (all months)"
            print(f"Updated category spending from {len(combined_df)} transactions{filter_msg}")
        else:
            print("No transaction data found for category update")
    
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
    
    elif args.category:
        # This would need integration with transaction processor
        print(f"Category analysis for '{args.category}' - feature requires transaction data integration")
    
    elif args.summary:
        tracker.show_summary()
    
    else:
        # Default: show summary
        tracker.show_summary()

if __name__ == "__main__":
    main()