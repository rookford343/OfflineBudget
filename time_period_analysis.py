#!/usr/bin/env python3
"""
Time Period Analysis Extension for Credit Card Tracker
- Analyzes spending across custom date ranges
- Monthly breakdown of spending by category
- Trend analysis and comparison between months
- Secure encrypted storage of historical data
"""
import pandas as pd
import json
from datetime import datetime, timedelta
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
            from pathlib import Path
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
                trend_indicator = "➡️  STABLE"
            
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

def add_period_analysis_to_tracker():
    """Add time period analysis methods to the main CreditCardTracker class."""
    
    def analyze_period(self, csv_files, start_date=None, end_date=None, group_by='month'):
        """Analyze spending over a time period using transaction files."""
        if not csv_files:
            print("No CSV files provided")
            return {}
        
        # Process all CSV files
        all_dfs = []
        for file_path in csv_files:
            df = self._process_csv_file(file_path)
            if not df.empty:
                all_dfs.append(df)
        
        if not all_dfs:
            print("No valid transaction data found")
            return {}
        
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
            return
        
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
    
    # Add methods to CreditCardTracker class
    return analyze_period, show_period_summary

# Example usage functions
def main_period_analysis():
    """Example of how to use the time period analysis."""
    from credit_card_tracker import CreditCardTracker
    
    # Create tracker instance
    tracker = CreditCardTracker()
    
    # Add the new methods
    analyze_period, show_period_summary = add_period_analysis_to_tracker()
    tracker.analyze_period = analyze_period.__get__(tracker, CreditCardTracker)
    tracker.show_period_summary = show_period_summary.__get__(tracker, CreditCardTracker)
    
    # Example: Analyze last 6 months by month
    csv_files = ['chase_jan_2024.csv', 'chase_feb_2024.csv', 'chase_mar_2024.csv']
    
    # Full analysis with all options
    analyzer, analysis = tracker.show_period_summary(
        csv_files=csv_files,
        start_date='2024-01-01',
        end_date='2024-03-31',
        group_by='month',
        show_categories=True,
        compare=True,
        trend_category='Food & Drinks',  # Or None for total spending
        store_as='Q1_2024_Analysis'
    )
    
    # List stored analyses
    analyzer.list_stored_analyses()

if __name__ == "__main__":
    main_period_analysis()