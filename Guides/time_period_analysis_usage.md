# Time Period Analysis - Usage Guide

## Integration

### Option 1: Add to existing files
1. Save `time_period_analysis.py` in the same directory as your tracker
2. Add the enhanced CLI commands to your `credit_card_tracker.py`

### Option 2: Use as separate module
1. Import the analyzer in your scripts
2. Use programmatically for custom analysis

## Command Line Examples

### Basic Time Period Analysis

**Analyze all transactions by month:**
```bash
python3 credit_card_tracker.py --analyze-period ~/Downloads/chase_*.csv
```

**Analyze specific date range:**
```bash
python3 credit_card_tracker.py --analyze-period ~/Downloads/chase_*.csv \
    --start-date 2024-01-01 --end-date 2024-06-30
```

**Group by quarter instead of month:**
```bash
python3 credit_card_tracker.py --analyze-period ~/Downloads/chase_*.csv \
    --group-by quarter --start-date 2024-01-01
```

### Advanced Analysis

**Monthly analysis with comparisons and trends:**
```bash
python3 credit_card_tracker.py --analyze-period ~/Downloads/chase_*.csv \
    --start-date 2024-01-01 --end-date 2024-12-31 \
    --compare --trend Food\ \&\ Drinks --store-analysis "2024_Full_Year"
```

**Analyze specific category trends:**
```bash
python3 credit_card_tracker.py --analyze-period ~/Downloads/chase_*.csv \
    --trend Shopping --compare --start-date 2024-01-01
```

**Hide category breakdown (show only totals):**
```bash
python3 credit_card_tracker.py --analyze-period ~/Downloads/chase_*.csv \
    --no-categories --trend total
```

### Historical Analysis Management

**Store analysis for future reference:**
```bash
python3 credit_card_tracker.py --analyze-period ~/Downloads/chase_*.csv \
    --start-date 2024-01-01 --end-date 2024-03-31 \
    --store-analysis "Q1_2024" --compare --trend total
```

**List all stored analyses:**
```bash
python3 credit_card_tracker.py --list-analyses
```

**Load and display stored analysis:**
```bash
python3 credit_card_tracker.py --load-analysis "Q1_2024" --compare --trend Shopping
```

**Compare two stored analyses:**
```bash
python3 credit_card_tracker.py --compare-analyses "Q1_2024" "Q2_2024"
```

## Sample Output

### Monthly Breakdown
```
================================================================================
TIME PERIOD SPENDING ANALYSIS
================================================================================
Period       Total Spent  Transactions Avg/Transaction
-------------------------------------------------------
2024-01      $2,845.67    89           $31.97        
2024-02      $3,234.89    95           $34.05        
2024-03      $2,667.45    82           $32.53        
2024-04      $3,445.23    101          $34.11        
2024-05      $2,998.76    88           $34.08        
2024-06      $3,123.55    93           $33.59        
-------------------------------------------------------
TOTAL        $18,315.55   548          $33.42        

================================================================================
MONTHLY CATEGORY BREAKDOWN
================================================================================
Period       Shopping    Food & DrinkServices    Entertainment Groceries   Other      
--------------------------------------------------------------------------------
2024-01      $845        $523        $234        $189         $467        $587       
2024-02      $967        $634        $345        $234         $523        $532       
2024-03      $723        $456        $267        $156         $445        $621       
2024-04      $1,034      $689        $389        $267         $589        $477       
2024-05      $834        $567        $312        $198         $534        $554       
2024-06      $889        $598        $334        $223         $556        $524       
--------------------------------------------------------------------------------
TOTALS       $5,292      $3,467      $1,881      $1,267       $3,114      $3,295     
```

### Trend Analysis
```
=== TREND ANALYSIS ===
Category: Food & Drinks
Overall Trend: 📈 INCREASING (+12.3%)

Period       Amount       Change      
------------------------------------
2024-01      $523.45      -           
2024-02      $634.21      +$110.76    
2024-03      $456.78      -$177.43    
2024-04      $689.32      +$232.54    
2024-05      $567.89      -$121.43    
2024-06      $598.45      +$30.56     
```

### Period Comparison
```
=== PERIOD COMPARISON (MONTH_OVER_MONTH) ===
2024-01 → 2024-02: +$389.22 (+13.7%) 📈
2024-02 → 2024-03: -$567.44 (-17.5%) 📉
2024-03 → 2024-04: +$777.78 (+29.2%) 📈
2024-04 → 2024-05: -$446.47 (-13.0%) 📉
2024-05 → 2024-06: +$124.79 (+4.2%) 📈
```

## Programmatic Usage

### Basic Integration
```python
from credit_card_tracker import CreditCardTracker
from time_period_analysis import TimePeriodAnalyzer, add_period_analysis_to_tracker

# Create tracker
tracker = CreditCardTracker()

# Add time period methods
analyze_period, show_period_summary = add_period_analysis_to_tracker()
tracker.analyze_period = analyze_period.__get__(tracker, CreditCardTracker)
tracker.show_period_summary = show_period_summary.__get__(tracker, CreditCardTracker)

# Run analysis
csv_files = ['jan_2024.csv', 'feb_2024.csv', 'mar_2024.csv']
analyzer, analysis = tracker.show_period_summary(
    csv_files=csv_files,
    start_date='2024-01-01',
    end_date='2024-03-31',
    show_categories=True,
    compare=True,
    trend_category='Food & Drinks'
)
```

### Advanced Custom Analysis
```python
# Create analyzer directly
analyzer = TimePeriodAnalyzer(tracker)

# Process transaction files
import pandas as pd
dfs = []
for file in csv_files:
    df = tracker._process_csv_file(file)
    if not df.empty:
        dfs.append(df)

combined_df = pd.concat(dfs, ignore_index=True)

# Run custom analysis
analysis = analyzer.analyze_time_period(
    combined_df, 
    start_date='2024-01-01',
    end_date='2024-06-30',
    group_by='month'
)

# Display results
analyzer.display_period_analysis(analysis, show_categories=True)

# Store for future use
analyzer.store_period_analysis('Q1_Q2_2024', analysis, {
    'description': 'First half 2024 analysis',
    'cards_included': ['Chase Sapphire', 'Apple Card'],
    'total_transactions': len(combined_df)
})
```

## Security Features

All time period analysis maintains the same security standards as your original tracker:

- **Encrypted Storage**: Historical analyses are stored using the same encryption as your card data
- **Local Processing**: All analysis happens offline on your machine
- **No External Dependencies**: Uses only standard Python libraries plus your existing requirements
- **Secure File Handling**: Transaction data is processed securely without storing sensitive info

## Use Cases

### Monthly Budget Review
```bash
# Analyze current month vs budget
python3 credit_card_tracker.py --analyze-period current_month.csv \
    --start-date $(date +%Y-%m-01) --compare --trend total
```

### Quarterly Business Review
```bash
# Compare quarters
python3 credit_card_tracker.py --analyze-period *.csv \
    --group-by quarter --compare --store-analysis "$(date +%Y)_Quarterly"
```

### Annual Spending Analysis
```bash
# Full year breakdown
python3 credit_card_tracker.py --analyze-period ~/transactions_2024/*.csv \
    --start-date 2024-01-01 --end-date 2024-12-31 \
    --compare --trend total --store-analysis "Annual_2024"
```

### Category Deep Dive
```bash
# Focus on specific spending category
python3 credit_card_tracker.py --analyze-period *.csv \
    --trend "Food & Drinks" --compare --start-date 2024-01-01
```

## Integration with Existing Workflow

The time period analysis integrates seamlessly with your existing workflow:

1. **Use with existing cards**: Analyzes the same transaction data you already process
2. **Maintains security**: Uses your existing encryption and security setup
3. **Extends current features**: Adds time-based analysis to your existing category system
4. **Preserves data**: Doesn't modify your existing card configurations or balances

## File Organization

Recommended file structure:
```
credit_tracker/
├── credit_card_tracker.py      # Your existing tracker
├── transaction_processor.py    # Your existing processor  
├── time_period_analysis.py     # New time period module
├── enhanced_cli.py             # Enhanced CLI (optional)
├── README.md                   # Your existing README
└── transaction_data/           # Your CSV files
    ├── 2024/
    │   ├── chase_jan_2024.csv
    │   ├── chase_feb_2024.csv
    │   └── ...
    └── 2023/
        └── ...
```

## Tips for Security Directors

- **Data Retention**: Historical analyses are encrypted and stored locally
- **Audit Trail**: Each stored analysis includes metadata about when it was created
- **Access Control**: Uses your system's keyring for encryption keys
- **No Network Access**: All processing remains offline
- **Minimal Dependencies**: Only adds standard data analysis capabilities

## Troubleshooting

**"No transaction data found"**
- Verify CSV files have the correct column headers
- Check date formats in your transaction files

**"Could not parse transaction dates"**
- Ensure your CSV has a 'Transaction Date' column
- Check that dates are in a recognizable format (MM/DD/YYYY, YYYY-MM-DD, etc.)

**"Analysis not stored"**
- Verify you have write permissions in the directory
- Check that encryption is working (same as your card data storage)

**Memory issues with large datasets**
- Process smaller date ranges
- Use `--no-categories` to reduce memory usage
- Consider splitting large CSV files by quarter or month