#!/usr/bin/env python3
"""
Simple test to verify the analysis function works
"""
import pandas as pd
import sys

def simple_categorize(description, memo='', original_category=''):
    """Simplified categorization for testing"""
    if pd.isna(description):
        description = ''
    if pd.isna(memo):
        memo = ''
    if pd.isna(original_category):
        original_category = ''
    
    # Convert to strings safely
    description = str(description)
    memo = str(memo)
    original_category = str(original_category)
    
    # Use original category if it matches our targets
    target_categories = ['Shopping', 'Food & Drinks', 'Services', 'Entertainment', 'Groceries']
    
    if original_category in target_categories:
        return original_category
    
    # Map some categories
    original_lower = original_category.lower()
    if 'health' in original_lower or 'wellness' in original_lower:
        return 'Services'
    if 'shopping' in original_lower:
        return 'Shopping'
    
    # Use description keywords
    text = f"{description} {memo}".lower()
    if 'amazon' in text or 'target' in text:
        return 'Shopping'
    elif 'starbucks' in text or 'restaurant' in text:
        return 'Food & Drinks'
    elif 'cvs' in text or 'chiropr' in text:
        return 'Services'
    
    return 'Other'

def simple_analyze(df):
    """Simplified analysis function"""
    print("=== Simple Analysis Debug ===")
    print(f"DataFrame shape: {df.shape}")
    print(f"Columns: {df.columns.tolist()}")
    
    if df.empty:
        print("DataFrame is empty!")
        return None
    
    # Show first few rows
    print("\nFirst 3 rows:")
    print(df[['Description', 'Category', 'Amount']].head(3))
    
    # Test categorization on first row
    first_row = df.iloc[0]
    print(f"\nTesting first row categorization:")
    print(f"Description: {first_row['Description']}")
    print(f"Category: {first_row['Category']}")
    print(f"Amount: {first_row['Amount']}")
    
    result = simple_categorize(
        first_row['Description'],
        first_row.get('Memo', ''),
        first_row['Category']
    )
    print(f"Categorized as: {result}")
    
    # Apply to all rows
    print("\nApplying to all rows...")
    df['custom_category'] = df.apply(
        lambda row: simple_categorize(
            row['Description'],
            row.get('Memo', ''),
            row['Category']
        ), axis=1
    )
    
    print("Categorization complete!")
    print("\nCategory counts:")
    print(df['custom_category'].value_counts())
    
    # Calculate spending by category
    spending_df = df[df['Amount'] < 0].copy()
    spending_df['amount_abs'] = spending_df['Amount'].abs()
    
    category_totals = spending_df.groupby('custom_category')['amount_abs'].sum()
    print("\nSpending by category:")
    for category, total in category_totals.items():
        print(f"{category}: ${total:.2f}")
    
    return {
        'total_transactions': len(df),
        'category_totals': category_totals.to_dict(),
        'spending_count': len(spending_df)
    }

def main():
    if len(sys.argv) != 2:
        print("Usage: python3 simple_test.py <csv_file>")
        sys.exit(1)
    
    csv_file = sys.argv[1]
    
    try:
        # Read CSV
        print(f"Reading {csv_file}...")
        df = pd.read_csv(csv_file)
        print(f"Read {len(df)} transactions")
        
        # Run analysis
        result = simple_analyze(df)
        
        if result:
            print(f"\n=== RESULTS ===")
            print(f"Total transactions: {result['total_transactions']}")
            print(f"Spending transactions: {result['spending_count']}")
            print("SUCCESS!")
        else:
            print("FAILED!")
            
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()