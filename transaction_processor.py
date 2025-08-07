#!/usr/bin/env python3
"""
Credit Card Transaction Processor
- Processes transaction files from any credit card provider
- Categorizes transactions into 6 main categories
- Provides detailed analysis and category breakdowns
- Secure handling of financial data
"""
import pandas as pd
import argparse
import sys
import keyring
from pathlib import Path
from cryptography.fernet import Fernet

def categorize_transaction(description, memo='', original_category=''):
    """Categorize transaction based on original category first, then description/memo."""
    # Handle NaN values safely
    if pd.isna(description):
        description = ''
    if pd.isna(memo):
        memo = ''
    if pd.isna(original_category):
        original_category = ''
    
    description = str(description)
    memo = str(memo)
    original_category = str(original_category)
    
    target_categories = ['Shopping', 'Food & Drinks', 'Services', 'Entertainment', 'Groceries']
    
    # First, check if the original category matches one of our target categories
    if original_category and original_category.strip():
        original_cat_lower = original_category.lower()
        
        # Direct matches
        if original_category in target_categories:
            return original_category
        
        # Map common bank categories to our categories
        category_mapping = {
            'shopping': 'Shopping',
            'merchandise': 'Shopping',
            'retail': 'Shopping',
            'health & wellness': 'Services',
            'healthcare': 'Services',
            'professional services': 'Services',
            'bills & utilities': 'Services',
            'restaurants': 'Food & Drinks',
            'fast food': 'Food & Drinks',
            'coffee shops': 'Food & Drinks',
            'dining': 'Food & Drinks',
            'supermarkets': 'Groceries',
            'grocery stores': 'Groceries',
            'travel': 'Entertainment',
            'recreation': 'Entertainment',
            'entertainment': 'Entertainment'
        }
        
        for bank_variant, our_category in category_mapping.items():
            if bank_variant in original_cat_lower:
                return our_category
    
    # If original category doesn't match, fall back to description/memo analysis
    text = f"{description} {memo}".lower()
    
    # Define keywords for each category
    categories = {
        'Shopping': [
            'amazon', 'walmart', 'target', 'costco', 'home depot', 'lowes', 'best buy',
            'macys', 'nordstrom', 'tjmaxx', 'marshalls', 'kohls', 'jcpenney',
            'cvs', 'walgreens', 'rite aid', 'pharmacy', 'dollar tree', 'dollar general',
            'shopping', 'retail', 'store', 'mall', 'outlet'
        ],
        'Food & Drinks': [
            'mcdonalds', 'burger king', 'subway', 'kfc', 'pizza hut', 'dominos',
            'starbucks', 'dunkin', 'chipotle', 'panera', 'chick-fil-a', 'taco bell',
            'restaurant', 'cafe', 'bar', 'pub', 'brewery', 'coffee', 'pizza',
            'fast food', 'takeout', 'delivery', 'doordash', 'uber eats', 'grubhub',
            'dining', 'food', 'drink', 'beverage', 'alcohol', 'wine', 'beer'
        ],
        'Services': [
            'bank', 'atm', 'fee', 'service charge', 'maintenance', 'overdraft',
            'insurance', 'medical', 'dental', 'doctor', 'hospital', 'clinic',
            'chiropr', 'lawyer', 'attorney', 'repair', 'cleaning', 'dry clean',
            'haircut', 'salon', 'spa', 'gym', 'fitness', 'subscription',
            'netflix', 'spotify', 'hulu', 'disney', 'internet', 'phone', 'cable',
            'utility', 'electric', 'gas', 'water', 'trash', 'sewer'
        ],
        'Entertainment': [
            'movie', 'theater', 'cinema', 'concert', 'show', 'ticket', 'event',
            'amusement', 'theme park', 'zoo', 'museum', 'sports', 'game',
            'bowling', 'golf', 'tennis', 'recreation', 'hobby', 'book', 'magazine',
            'music', 'video game', 'gaming', 'entertainment', 'fun', 'leisure',
            'vacation', 'travel', 'hotel', 'flight', 'airline', 'rental car'
        ],
        'Groceries': [
            'grocery', 'supermarket', 'kroger', 'safeway', 'publix', 'whole foods',
            'trader joes', 'aldi', 'food lion', 'giant', 'harris teeter',
            'stop shop', 'jewel', 'meijer', 'heb', 'wegmans', 'fresh market',
            'market', 'produce', 'deli', 'bakery', 'butcher', 'organic'
        ]
    }
    
    # Check each category for keyword matches
    for category, keywords in categories.items():
        for keyword in keywords:
            if keyword in text:
                return category
    
    # If no match found, categorize as Other
    return 'Other'

def setup_encryption():
    """Set up encryption for local data storage."""
    encryption_key = keyring.get_password("transaction_processor", "encryption_key")
    
    if not encryption_key:
        key = Fernet.generate_key()
        keyring.set_password("transaction_processor", "encryption_key", key.decode())
        encryption_key = key.decode()
        
    return Fernet(encryption_key.encode())

def analyze_transactions(df):
    """Analyze transactions and return category breakdown."""
    if df.empty:
        return {
            'total_transactions': 0,
            'date_range': {'start': 'N/A', 'end': 'N/A'},
            'amount_summary': {'total_spent': 0, 'total_credits': 0, 'average_transaction': 0},
            'category_totals': {
                'Shopping': 0.0,
                'Food & Drinks': 0.0,
                'Services': 0.0,
                'Entertainment': 0.0,
                'Groceries': 0.0,
                'Other': 0.0
            }
        }
    
    # Create a copy to avoid modifying original data
    analysis_df = df.copy()
    
    # Add custom category column
    analysis_df['custom_category'] = analysis_df.apply(
        lambda row: categorize_transaction(
            row.get('Description', ''), 
            row.get('Memo', ''),
            row.get('Category', '')
        ), axis=1
    )
    
    # Calculate category totals (only spending - negative amounts)
    spending_df = analysis_df[analysis_df['Amount'] < 0].copy()
    spending_df['amount_abs'] = spending_df['Amount'].abs()
    
    category_totals = spending_df.groupby('custom_category')['amount_abs'].sum()
    
    # Ensure all required categories are present
    required_categories = ['Shopping', 'Food & Drinks', 'Services', 'Entertainment', 'Groceries', 'Other']
    for category in required_categories:
        if category not in category_totals:
            category_totals[category] = 0.0
    
    # Parse dates for date range
    try:
        df_copy = df.copy()
        df_copy['parsed_date'] = pd.to_datetime(df_copy['Transaction Date'])
        start_date = df_copy['parsed_date'].min().strftime('%Y-%m-%d')
        end_date = df_copy['parsed_date'].max().strftime('%Y-%m-%d')
    except:
        start_date = 'N/A'
        end_date = 'N/A'
    
    analysis = {
        'total_transactions': len(df),
        'date_range': {
            'start': start_date,
            'end': end_date
        },
        'amount_summary': {
            'total_spent': abs(df[df['Amount'] < 0]['Amount'].sum()),
            'total_credits': df[df['Amount'] > 0]['Amount'].sum(),
            'average_transaction': df['Amount'].mean()
        },
        'category_totals': {
            'Shopping': float(category_totals.get('Shopping', 0)),
            'Food & Drinks': float(category_totals.get('Food & Drinks', 0)),
            'Services': float(category_totals.get('Services', 0)),
            'Entertainment': float(category_totals.get('Entertainment', 0)),
            'Groceries': float(category_totals.get('Groceries', 0)),
            'Other': float(category_totals.get('Other', 0))
        }
    }
    
    return analysis

def analyze_category_detail(df, category_name):
    """Analyze transactions within a specific category."""
    if df.empty:
        return f"No transactions to analyze for category: {category_name}"
    
    # Create analysis DataFrame with custom categories
    analysis_df = df.copy()
    analysis_df['custom_category'] = analysis_df.apply(
        lambda row: categorize_transaction(
            row.get('Description', ''), 
            row.get('Memo', ''),
            row.get('Category', '')
        ), axis=1
    )
    
    # Filter to the requested category
    category_df = analysis_df[analysis_df['custom_category'] == category_name].copy()
    
    if category_df.empty:
        return f"No transactions found in category: {category_name}"
    
    # Calculate spending in this category (negative amounts)
    spending_df = category_df[category_df['Amount'] < 0].copy()
    spending_df['amount_abs'] = spending_df['Amount'].abs()
    
    # Group by merchant/description for detailed breakdown
    merchant_breakdown = spending_df.groupby('Description').agg({
        'amount_abs': ['sum', 'count'],
        'Transaction Date': ['min', 'max']
    }).round(2)
    
    # Flatten column names
    merchant_breakdown.columns = ['total_spent', 'transaction_count', 'first_transaction', 'last_transaction']
    merchant_breakdown = merchant_breakdown.sort_values('total_spent', ascending=False)
    
    # Show original bank categories in this bucket
    bank_categories_used = category_df['Category'].value_counts().to_dict()
    
    category_analysis = {
        'category': category_name,
        'total_transactions': len(category_df),
        'total_spending': float(spending_df['amount_abs'].sum()),
        'average_transaction': float(spending_df['amount_abs'].mean()) if len(spending_df) > 0 else 0,
        'date_range': {
            'start': category_df['Transaction Date'].min() if len(category_df) > 0 else 'N/A',
            'end': category_df['Transaction Date'].max() if len(category_df) > 0 else 'N/A'
        },
        'bank_categories_included': bank_categories_used,
        'top_merchants': merchant_breakdown.head(10).to_dict('index'),
        'recent_transactions': category_df[['Transaction Date', 'Description', 'Amount', 'Category']].tail(20).to_dict('records')
    }
    
    return category_analysis

def save_encrypted(df, filename):
    """Save processed transactions to encrypted file."""
    if df.empty:
        print("No data to save")
        return
    
    cipher_suite = setup_encryption()
    
    # Convert to JSON
    json_data = df.to_json(date_format='iso', orient='records')
    
    # Encrypt
    encrypted_data = cipher_suite.encrypt(json_data.encode())
    
    # Save
    with open(filename, 'wb') as f:
        f.write(encrypted_data)
    
    print(f"Data encrypted and saved to: {filename}")

def load_encrypted(filename):
    """Load encrypted transaction data."""
    try:
        cipher_suite = setup_encryption()
        
        with open(filename, 'rb') as f:
            encrypted_data = f.read()
        
        # Decrypt
        decrypted_data = cipher_suite.decrypt(encrypted_data).decode()
        
        # Convert back to DataFrame
        df = pd.read_json(decrypted_data)
        
        # Convert date column back to datetime
        if 'Transaction Date' in df.columns:
            df['Transaction Date'] = pd.to_datetime(df['Transaction Date'])
        
        return df
        
    except Exception as e:
        print(f"Error loading encrypted file: {e}")
        return pd.DataFrame()

def process_csv_file(file_path):
    """Process CSV files from credit card providers."""
    print(f"Processing CSV file: {file_path}")
    
    try:
        # Try different encodings
        encodings = ['utf-8', 'latin-1', 'cp1252']
        
        for encoding in encodings:
            try:
                df = pd.read_csv(file_path, encoding=encoding)
                break
            except UnicodeDecodeError:
                continue
        else:
            raise Exception("Could not decode file with any standard encoding")
        
        # Clean amount field
        if 'Amount' in df.columns:
            df['Amount'] = df['Amount'].astype(str).str.replace(r'[\$,]', '', regex=True)
            df['Amount'] = pd.to_numeric(df['Amount'], errors='coerce')
        
        # Remove empty rows
        df = df.dropna(subset=['Amount'])
        
        # Sort by date
        if 'Transaction Date' in df.columns:
            try:
                df['parsed_date'] = pd.to_datetime(df['Transaction Date'])
                df = df.sort_values('parsed_date', ascending=False)
                df = df.drop('parsed_date', axis=1)
            except:
                pass
        
        return df
        
    except Exception as e:
        print(f"Error processing CSV file: {e}")
        return pd.DataFrame()

def main():
    """Main function with command line interface."""
    parser = argparse.ArgumentParser(description='Process credit card transaction files')
    parser.add_argument('files', nargs='*', help='Transaction files to process (.csv)')
    parser.add_argument('--analyze', action='store_true', help='Show transaction analysis')
    parser.add_argument('--category', help='Analyze specific category in detail (Shopping, Food & Drinks, Services, Entertainment, Groceries, Other)')
    parser.add_argument('--save', help='Save processed data to encrypted file')
    parser.add_argument('--load', help='Load processed data from encrypted file')
    parser.add_argument('--export', help='Export to CSV/Excel/JSON')
    parser.add_argument('--format', default='csv', help='Export format (csv, excel, json)')
    
    args = parser.parse_args()
    
    # Load from encrypted file if requested
    if args.load:
        print(f"Loading encrypted data from {args.load}...")
        df = load_encrypted(args.load)
        if df.empty:
            print("No data loaded")
            return
        print(f"Loaded {len(df)} transactions")
    else:
        # Process files
        if not args.files:
            print("No files specified. Use --load to load encrypted data or provide CSV files.")
            return
            
        print(f"Processing {len(args.files)} file(s)...")
        all_dfs = []
        
        for file_path in args.files:
            df = process_csv_file(file_path)
            if not df.empty:
                all_dfs.append(df)
        
        if not all_dfs:
            print("No transaction data found")
            return
        
        # Combine all DataFrames
        df = pd.concat(all_dfs, ignore_index=True) if len(all_dfs) > 1 else all_dfs[0]
    
    print(f"Processed {len(df)} transactions")
    if 'Transaction Date' in df.columns:
        try:
            df_temp = df.copy()
            df_temp['parsed_date'] = pd.to_datetime(df_temp['Transaction Date'])
            print(f"Date range: {df_temp['parsed_date'].min().date()} to {df_temp['parsed_date'].max().date()}")
        except:
            print("Date range: Could not parse dates")
    
    # Save encrypted copy if requested
    if args.save:
        save_encrypted(df, args.save)
    
    # Export if requested
    if args.export:
        try:
            if args.format.lower() == 'csv':
                df.to_csv(args.export, index=False)
            elif args.format.lower() == 'excel':
                df.to_excel(args.export, index=False)
            elif args.format.lower() == 'json':
                df.to_json(args.export, date_format='iso', orient='records', indent=2)
            else:
                print(f"Unsupported export format: {args.format}")
                return
            
            print(f"Data exported to: {args.export}")
        except Exception as e:
            print(f"Error exporting data: {e}")
    
    # Show analysis if requested
    if args.analyze:
        analysis = analyze_transactions(df)
        
        print("\n=== Transaction Analysis ===")
        print(f"Total Transactions: {analysis['total_transactions']}")
        print(f"Date Range: {analysis['date_range']['start']} to {analysis['date_range']['end']}")
        print(f"Total Spent: ${analysis['amount_summary']['total_spent']:,.2f}")
        print(f"Total Credits: ${analysis['amount_summary']['total_credits']:,.2f}")
        print(f"Average Transaction: ${analysis['amount_summary']['average_transaction']:,.2f}")
        
        print("\n=== Category Totals ===")
        for category, total in analysis['category_totals'].items():
            print(f"{category:<15}: ${total:>8,.2f}")
        
        # Calculate percentages
        total_spending = sum(analysis['category_totals'].values())
        if total_spending > 0:
            print("\n=== Category Percentages ===")
            for category, total in analysis['category_totals'].items():
                percentage = (total / total_spending) * 100
                print(f"{category:<15}: {percentage:>6.1f}%")
    
    # Show detailed category analysis if requested
    if args.category:
        valid_categories = ['Shopping', 'Food & Drinks', 'Services', 'Entertainment', 'Groceries', 'Other']
        if args.category not in valid_categories:
            print(f"Invalid category. Choose from: {', '.join(valid_categories)}")
        else:
            category_detail = analyze_category_detail(df, args.category)
            
            print(f"\n=== Detailed Analysis: {args.category} ===")
            print(f"Total Transactions: {category_detail['total_transactions']}")
            print(f"Total Spending: ${category_detail['total_spending']:,.2f}")
            print(f"Average Transaction: ${category_detail['average_transaction']:,.2f}")
            print(f"Date Range: {category_detail['date_range']['start']} to {category_detail['date_range']['end']}")
            
            if category_detail['bank_categories_included']:
                print(f"\n=== Bank Categories Included ===")
                for bank_cat, count in category_detail['bank_categories_included'].items():
                    print(f"{bank_cat}: {count} transactions")
            
            print(f"\n=== Top Merchants in {args.category} ===")
            for merchant, details in list(category_detail['top_merchants'].items())[:10]:
                print(f"{merchant:<40}: ${details['total_spent']:>8,.2f} ({details['transaction_count']} transactions)")
            
            # Show recent transactions
            print(f"\n=== Recent {args.category} Transactions (Last 20) ===")
            for transaction in category_detail['recent_transactions']:
                date_str = str(transaction['Transaction Date'])[:10]  # Get just the date part
                print(f"{date_str} | ${abs(transaction['Amount']):>8,.2f} | {transaction['Description']:<40} | {transaction.get('Category', 'N/A')}")

if __name__ == "__main__":
    main()