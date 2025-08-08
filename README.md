# Credit Card Transaction Processor & Tracker

A secure, offline tool for analyzing credit card transactions and tracking spending across multiple cards. Features intelligent merchant name cleaning, category budget tracking, time period analysis with monthly/quarterly/yearly breakdowns, and comprehensive financial insights without storing credentials or requiring internet access.

## Features

### Transaction Analysis
- **Universal Compatibility**: Works with CSV files from any credit card provider (Chase, Amex, Capital One, etc.)
- **Smart Categorization**: Uses bank's existing categories when possible, falls back to intelligent keyword matching
- **6 Core Categories**: Shopping, Food & Drinks, Services, Entertainment, Groceries, Other
- **Merchant Name Cleaning**: Automatically cleans messy transaction names (e.g., "AMAZON MKTPL*WC4V41N33" → "AMAZON")
- **Detailed Analysis**: Category breakdowns, spending totals, clean merchant summaries

### Credit Card Tracking
- **Multi-Card Management**: Track spending across all your credit cards
- **Dual Balance Tracking**: Separate current spending from previous statement balances
- **Credit Limit Monitoring**: See available credit and spending limits
- **Due Date Tracking**: Never miss a payment with upcoming due date alerts
- **Spending Limits**: Set soft (savings goals) and hard (emergency) spending limits
- **Category Budgets**: Set and monitor monthly budgets for each spending category
- **Spending Summary**: Quick overview with alerts for overspending

### Time Period Analysis (NEW)
- **Monthly/Quarterly/Yearly Breakdowns**: Analyze spending patterns over custom time periods
- **Trend Analysis**: Visual indicators (📈📉➡️) showing spending direction and percentage changes
- **Period Comparisons**: Month-over-month, quarter-over-quarter, and year-over-year analysis
- **Historical Storage**: Save and recall previous analyses for comparison
- **Category Trends**: Track specific category spending over time
- **Custom Date Ranges**: Analyze any date range from your transaction history

### Security
- **Secure Storage**: Encrypts local data using your system's secure keyring
- **Offline Processing**: Everything runs locally on your machine
- **No Credentials**: Never stores bank login information

## Installation

### Requirements
- Python 3.7 or higher
- Required packages:

```bash
pip install pandas keyring cryptography
```

### Setup
1. Download `transaction_processor.py` and `credit_card_tracker.py`
2. Make them executable:
```bash
chmod +x transaction_processor.py
chmod +x credit_card_tracker.py
```

## Credit Card Tracker Setup

### Initial Configuration

Set up your credit cards with their limits and dates:

```bash
# Add each of your credit cards (with optional balance due and current balance)
python3 credit_card_tracker.py --add-card "Chase Sapphire" 10000 15 12 --add-card-desc "Primary rewards card"
python3 credit_card_tracker.py --add-card "Apple" 5000 28 25 1200 567.89 --add-card-desc "Apple Card"
python3 credit_card_tracker.py --add-card "Amex" 15000 20 17 --add-card-desc "Business expenses"
python3 credit_card_tracker.py --add-card "Citi" 8000 10 7 --add-card-desc "Backup card"
python3 credit_card_tracker.py --add-card "Personal Chase" 3000 5 2 --add-card-desc "Personal card"
```

**Format**: `--add-card "Card Name" credit_limit statement_date due_date [balance_due] [current_balance]`
- `credit_limit`: Your credit limit (e.g., 10000 for $10,000)
- `statement_date`: Day of month statement closes (e.g., 15 for 15th)
- `due_date`: Day of month payment is due (e.g., 12 for 12th)
- `balance_due`: Optional - existing balance from previous statement
- `current_balance`: Optional - new spending since last statement

## Getting Transaction Data from Chase Bank

### Step-by-Step Download Process:

1. **Log into Chase Online Banking**
   - Go to [chase.com](https://www.chase.com) and sign in

2. **Navigate to Your Credit Card Account**
   - Click on the credit card you want to analyze

3. **Access Transaction History**
   - Look for "Account Activity" or "Statements & Activity"
   - Click "Download account activity" or "Download transactions"

4. **Configure Download Settings**
   - **Date Range**: Select your desired time period (up to 2 years)
   - **Format**: Choose **CSV** (not PDF or other formats)
   - **Account**: Ensure correct credit card is selected

5. **Download the File**
   - File will typically be named something like `Chase1234_Activity20240101_20240331_20240405.CSV`
   - Save to a folder you'll remember (e.g., `~/Downloads`)

### Other Credit Card Providers

The processor works with CSV files from other providers too:
- **American Express**: Download from "Statements & Activity"
- **Capital One**: Use "Download Transactions" feature
- **Discover**: Export from "Recent Activity"
- **Citi**: Download from "Account Activity"

## Usage Examples

### Credit Card Tracking

**Set category budgets for monthly spending goals:**
```bash
# Set budgets for specific categories
python3 credit_card_tracker.py --set-budgets Shopping:800 "Food & Drinks":400 Services:300 Entertainment:200 Groceries:350

# Set individual budgets
python3 credit_card_tracker.py --set-budgets Shopping:800
python3 credit_card_tracker.py --set-budgets "Food & Drinks":400
```

**Enhanced summary with budget tracking:**
```bash
python3 credit_card_tracker.py --summary
```

**Output:**
```
==================================================
CREDIT CARD SPENDING SUMMARY - January 2025
==================================================
Chase Sapphire  $   2,367.73
Apple           $       3.99
Amex            $          -
Citi            $          -
Personal Chase  $          -
------------------------------
Left to Spend   $    -371.72 ⚠️  CAUTION
------------------------------
**New Spending  $   2,371.72**
  Balance Due   $   1,200.00
  Total Owed    $   3,571.72

==================================================
CATEGORY BUDGET STATUS
==================================================
Shopping        $  845.67 /   $800.00 ($ -45.67) 🚨 OVER
Food & Drinks   $  234.56 /   $400.00 ($  165.44)
Services        $  156.78 /   $300.00 ($  143.22)
Entertainment   $   89.45 /   $200.00 ($  110.55)
Groceries       $  378.90 /   $350.00 ($  -28.90) ⚠️  LOW
Other           $   45.23 /        - (     -     )
==================================================
```

**Check upcoming due dates:**
```bash
python3 credit_card_tracker.py --due-dates
```

**Output:**
```
=== Upcoming Due Dates ===
Personal Chase  2024-04-02 ( 5 days) $    0.00
Citi            2024-04-07 (10 days) $    0.00 ⚡ SOON
Chase Sapphire  2024-04-12 (15 days) $2,367.73
Apple           2024-04-25 (28 days) $    3.99
```

### Time Period Analysis (NEW)

**Basic monthly spending analysis:**
```bash
# Analyze all transactions by month
python3 credit_card_tracker.py --analyze-period ~/Downloads/chase_*.csv
```

**Custom date range with comparisons:**
```bash
# Analyze specific date range with month-over-month comparison
python3 credit_card_tracker.py --analyze-period ~/Downloads/chase_*.csv \
    --start-date 2024-01-01 --end-date 2024-06-30 --compare
```

**Comprehensive analysis with trends and storage:**
```bash
# Full analysis with all features
python3 credit_card_tracker.py --analyze-period ~/Downloads/*.csv \
    --start-date 2024-01-01 --end-date 2024-12-31 \
    --group-by month --compare --trend "Food & Drinks" \
    --store-analysis "2024_Full_Year"
```

**Sample Time Period Output:**
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

=== PERIOD COMPARISON (MONTH_OVER_MONTH) ===
2024-01 → 2024-02: +$389.22 (+13.7%) 📈
2024-02 → 2024-03: -$567.44 (-17.5%) 📉
2024-03 → 2024-04: +$777.78 (+29.2%) 📈
2024-04 → 2024-05: -$446.47 (-13.0%) 📉
2024-05 → 2024-06: +$124.79 (+4.2%) 📈

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

**Historical Analysis Management:**
```bash
# Store current analysis for future reference
python3 credit_card_tracker.py --analyze-period *.csv \
    --start-date 2024-01-01 --end-date 2024-03-31 \
    --store-analysis "Q1_2024"

# List all stored analyses
python3 credit_card_tracker.py --list-analyses

# Load and display stored analysis
python3 credit_card_tracker.py --load-analysis "Q1_2024" --compare --trend total

# Compare two stored time periods
python3 credit_card_tracker.py --compare-analyses "Q1_2024" "Q2_2024"
```

**Quarterly and yearly analysis:**
```bash
# Group by quarters instead of months
python3 credit_card_tracker.py --analyze-period *.csv \
    --group-by quarter --start-date 2024-01-01

# Annual overview
python3 credit_card_tracker.py --analyze-period ~/transactions_2024/*.csv \
    --group-by year --compare --trend total
```

**Category-focused analysis:**
```bash
# Focus on specific spending category trends
python3 credit_card_tracker.py --analyze-period *.csv \
    --trend Shopping --compare --start-date 2024-01-01

# Hide category breakdown (totals only)
python3 credit_card_tracker.py --analyze-period *.csv \
    --no-categories --trend total
```

### Transaction Analysis

**Process single file:**
```bash
python3 transaction_processor.py transactions.csv --analyze
```

**Output:**
```
=== Transaction Analysis ===
Total Transactions: 247
Date Range: 2024-01-01 to 2024-03-31
Total Spent: $8,456.32
Total Credits: $125.00
Average Transaction: $34.25

=== Category Totals ===
Shopping        : $2,845.67
Food & Drinks   : $1,523.89
Services        : $1,245.33
Groceries       : $1,089.44
Other           : $1,456.78
Entertainment   :   $295.21

=== Category Percentages ===
Shopping        :   33.7%
Food & Drinks   :   18.0%
Services        :   14.7%
Groceries       :   12.9%
Other           :   17.2%
Entertainment   :    3.5%
```

**Detailed Category Analysis:**
```bash
python3 transaction_processor.py transactions.csv --category "Food & Drinks"
```

**Processing Multiple Files:**
```bash
python3 transaction_processor.py jan.csv feb.csv mar.csv --analyze
```

## Command Line Options

### Credit Card Tracker (`credit_card_tracker.py`)

#### Card Management
| Option | Description | Example |
|--------|-------------|---------|
| `--add-card` | Add new credit card | `--add-card "Chase" 10000 15 12 1200` |
| `--add-card-desc` | Description for new card | `--add-card-desc "Primary card"` |
| `--update-card` | Update existing card details | `--update-card "Chase" --credit-limit 15000 --current-balance 1234` |
| `--remove-card` | Remove a credit card | `--remove-card "Old Card"` |
| `--list-cards` | List all configured cards | `--list-cards` |
| `--update-balance` | Update card balance | `--update-balance "Chase" 1234.56 current` |

#### Budget Management
| Option | Description | Example |
|--------|-------------|---------|
| `--set-limits` | Set monthly spending limits | `--set-limits 2000 3000` |
| `--set-budgets` | Set category budgets | `--set-budgets Shopping:800 "Food & Drinks":400` |
| `--reset-statement` | Reset for new statement period | `--reset-statement "Chase"` |
| `--reset` | Reset balances | `--reset current` |

#### Transaction Processing
| Option | Description | Example |
|--------|-------------|---------|
| `--process-auto` | Auto-process transaction files | `--process-auto ~/Downloads/Chase*.csv` |
| `--update-categories` | Update category spending only | `--update-categories *.csv` |

#### Display
| Option | Description | Example |
|--------|-------------|---------|
| `--summary` | Show spending summary | `--summary` |
| `--due-dates` | Show upcoming due dates | `--due-dates` |

#### Time Period Analysis (NEW)
| Option | Description | Example |
|--------|-------------|---------|
| `--analyze-period` | Analyze transactions over time | `--analyze-period ~/Downloads/*.csv` |
| `--start-date` | Start date for analysis | `--start-date 2024-01-01` |
| `--end-date` | End date for analysis | `--end-date 2024-06-30` |
| `--group-by` | Group by time period | `--group-by quarter` |
| `--compare` | Show period comparisons | `--compare` |
| `--trend` | Show trend analysis | `--trend "Food & Drinks"` or `--trend total` |
| `--store-analysis` | Store analysis with name | `--store-analysis "Q1_2024"` |
| `--no-categories` | Hide category breakdown | `--no-categories` |

#### Historical Analysis
| Option | Description | Example |
|--------|-------------|---------|
| `--list-analyses` | List stored analyses | `--list-analyses` |
| `--load-analysis` | Load stored analysis | `--load-analysis "Q1_2024"` |
| `--compare-analyses` | Compare two analyses | `--compare-analyses "Q1_2024" "Q2_2024"` |

### Transaction Processor (`transaction_processor.py`)

| Option | Description | Example |
|--------|-------------|---------|
| `files` | CSV transaction files to process | `transactions.csv` |
| `--analyze` | Show category breakdown and spending analysis | `--analyze` |
| `--category` | Detailed analysis of specific category | `--category "Shopping"` |
| `--save` | Save encrypted backup | `--save backup.enc` |
| `--load` | Load from encrypted backup | `--load backup.enc` |
| `--export` | Export processed data | `--export report.xlsx` |
| `--format` | Export format (csv, excel, json) | `--format excel` |

## Category System

The processor automatically categorizes transactions into these 6 categories:

### 🛍️ Shopping
- Amazon, Walmart, Target, Costco
- Department stores, pharmacies, retail
- Online shopping, home improvement

### 🍕 Food & Drinks
- Restaurants, fast food, coffee shops
- Delivery services (DoorDash, Uber Eats)
- Bars, breweries, dining out

### 🔧 Services
- Healthcare, insurance, banking fees
- Utilities, internet, phone, subscriptions
- Professional services, repairs

### 🎬 Entertainment
- Movies, concerts, sports events
- Travel, hotels, flights
- Books, games, recreation

### 🥬 Groceries
- Supermarkets, grocery stores
- Whole Foods, Trader Joe's, local markets
- Organic stores, produce stands

### 📋 Other
- Any transaction that doesn't fit the above categories
- Transfers, unusual purchases

## Time Period Analysis Use Cases

### Monthly Budget Review
```bash
# Current month analysis with budget comparison
python3 credit_card_tracker.py --analyze-period current_month.csv \
    --start-date $(date +%Y-%m-01) --compare --trend total
```

### Quarterly Business Review
```bash
# Compare quarters with category trends
python3 credit_card_tracker.py --analyze-period *.csv \
    --group-by quarter --compare --trend Shopping --store-analysis "$(date +%Y)_Quarterly"
```

### Annual Spending Analysis
```bash
# Full year breakdown with comprehensive analysis
python3 credit_card_tracker.py --analyze-period ~/transactions_2024/*.csv \
    --start-date 2024-01-01 --end-date 2024-12-31 \
    --compare --trend total --store-analysis "Annual_2024"
```

### Category Deep Dive
```bash
# Analyze specific category over time
python3 credit_card_tracker.py --analyze-period *.csv \
    --trend "Food & Drinks" --compare --start-date 2024-01-01
```

### Spending Pattern Detection
```bash
# Identify spending patterns by month
python3 credit_card_tracker.py --analyze-period *.csv \
    --group-by month --compare --trend total --start-date 2023-01-01
```

## Security Features

- **No Credentials Stored**: Never stores your bank login information
- **Local Processing**: Everything runs on your computer, no data sent online
- **Encrypted Storage**: Uses your system's secure keyring for encryption keys
- **Secure File Handling**: Encrypted backups protect your financial data
- **Historical Data Protection**: Time period analyses stored with same encryption as card data

## Troubleshooting

### Common Issues

**"No transactions to analyze"**
- Check that your CSV file has data
- Ensure file is in correct format with columns: Transaction Date, Description, Category, Amount

**"Error processing CSV file"**
- Try different file encoding if special characters appear garbled
- Ensure file isn't corrupted during download

**"Module not found"**
- Install required packages: `pip install pandas keyring cryptography`

**"Could not parse transaction dates"**
- Ensure your CSV has a 'Transaction Date' column
- Check that dates are in a recognizable format (MM/DD/YYYY, YYYY-MM-DD, etc.)

**"No data found in specified date range"**
- Verify your start and end dates are correct
- Check that transaction dates fall within your specified range

### File Format Requirements

Your CSV should have these columns:
- `Transaction Date` - Date of transaction
- `Description` - Merchant name/description
- `Category` - Bank's original category (optional)
- `Amount` - Transaction amount (negative for spending)
- `Memo` - Additional details (optional)

## Privacy and Security

- **Offline Only**: No internet connection required or used
- **Local Processing**: All analysis happens on your machine
- **Encrypted Storage**: Backup files and historical analyses are encrypted using industry-standard encryption
- **No Tracking**: No analytics, telemetry, or data collection

## Contributing

This tool was built with security professionals in mind. If you find issues or want to contribute improvements:

1. Test thoroughly with sample data
2. Maintain security-first principles
3. Keep dependencies minimal
4. Document any changes clearly

## License

This tool is provided as-is for personal financial analysis. Use responsibly and in accordance with your bank's terms of service.

---

**Need Help?** 
- Check that your CSV has the required columns
- Ensure Python packages are installed correctly
- Try with a smaller date range if processing large files
- Use `--store-analysis` to backup your data before trying different analysis options

## Recent Updates

### Time Period Analysis Features
- **Monthly/Quarterly/Yearly Breakdowns**: Analyze spending patterns over any time period
- **Trend Analysis**: Visual indicators showing spending direction with percentage changes
- **Historical Storage**: Save and compare multiple time period analyses
- **Period Comparisons**: Month-over-month, quarter-over-quarter analysis
- **Custom Date Ranges**: Analyze any specific date range from your transaction history
- **Category Trends**: Track how specific spending categories change over time
- **Secure Storage**: All historical analyses encrypted using existing security system