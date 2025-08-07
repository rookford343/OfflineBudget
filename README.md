# Credit Card Transaction Processor & Tracker

A secure, offline tool for analyzing credit card transactions and tracking spending across multiple cards. Automatically categorizes spending into 6 main categories and provides detailed financial insights without storing credentials or requiring internet access.

## Features

### Transaction Analysis
- **Universal Compatibility**: Works with CSV files from any credit card provider (Chase, Amex, Capital One, etc.)
- **Smart Categorization**: Uses bank's existing categories when possible, falls back to intelligent keyword matching
- **6 Core Categories**: Shopping, Food & Drinks, Services, Entertainment, Groceries, Other
- **Detailed Analysis**: Category breakdowns, spending totals, merchant analysis

### Credit Card Tracking
- **Multi-Card Management**: Track spending across all your credit cards
- **Credit Limit Monitoring**: See available credit and spending limits
- **Due Date Tracking**: Never miss a payment with upcoming due date alerts
- **Spending Summary**: Quick overview of current balances and total spending

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
# Add each of your credit cards (with optional balance due)
python3 credit_card_tracker.py --add-card "Chase Sapphire" 10000 15 12 --add-card-desc "Primary rewards card"
python3 credit_card_tracker.py --add-card "Apple" 5000 28 25 --add-card-desc "Apple Card"
python3 credit_card_tracker.py --add-card "Amex" 15000 20 17 1200 --add-card-desc "Business expenses"
python3 credit_card_tracker.py --add-card "Citi" 8000 10 7 --add-card-desc "Backup card"
python3 credit_card_tracker.py --add-card "Personal Chase" 3000 5 2 --add-card-desc "Personal card"
```

**Format**: `--add-card "Card Name" credit_limit statement_date due_date [balance_due]`
- `credit_limit`: Your credit limit (e.g., 10000 for $10,000)
- `statement_date`: Day of month statement closes (e.g., 15 for 15th)
- `due_date`: Day of month payment is due (e.g., 12 for 12th)
- `balance_due`: Optional - existing balance from previous statement

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

**Show current spending summary:**
```bash
python3 credit_card_tracker.py --summary
```

**Output:**
```
==================================================
CREDIT CARD SPENDING SUMMARY
==================================================
Chase Sapphire  $   2,367.73
Apple           $       3.99
Amex            $          -
Citi            $          -
Areli Chase     $          -
------------------------------
Left to Spend   $   1,480.72
------------------------------
**Total Spent   $   2,371.72**
==================================================
```

**Update card balance manually:**
```bash
python3 credit_card_tracker.py --update-balance "Chase Sapphire" 2367.73
python3 credit_card_tracker.py --update-balance "Apple" 3.99
```

**Check upcoming due dates:**
```bash
python3 credit_card_tracker.py --due-dates
```

**Output:**
```
=== Upcoming Due Dates ===
Areli Chase     2024-04-02 ( 5 days) $    0.00
Citi            2024-04-07 (10 days) $    0.00 ⚡ SOON
Chase Sapphire  2024-04-12 (15 days) $2,367.73
Apple           2024-04-25 (28 days) $    3.99
```

**List all configured cards:**
```bash
python3 credit_card_tracker.py --list-cards
```

### Transaction Analysis
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

### Detailed Category Analysis
```bash
python3 transaction_processor.py transactions.csv --category "Food & Drinks"
```

**Output:**
```
=== Detailed Analysis: Food & Drinks ===
Total Transactions: 45
Total Spending: $1,523.89
Average Transaction: $33.86
Date Range: 2024-01-02 to 2024-03-30

=== Bank Categories Included ===
Restaurants: 23 transactions
Fast Food: 12 transactions
Coffee Shops: 8 transactions
Food & Drink: 2 transactions

=== Top Merchants in Food & Drinks ===
STARBUCKS #12345                        :   $234.56 (12 transactions)
CHIPOTLE MEXICAN GRILL                   :   $189.45 (8 transactions)
MCDONALD'S #4567                         :   $156.78 (11 transactions)
```

### Processing Multiple Files
```bash
python3 transaction_processor.py jan.csv feb.csv mar.csv --analyze
```

### Save and Load Encrypted Data
```bash
# Save processed data securely
python3 transaction_processor.py transactions.csv --save backup.enc

# Load and analyze saved data
python3 transaction_processor.py --load backup.enc --analyze
```

### Export Analysis
```bash
# Export to Excel for further analysis
python3 transaction_processor.py transactions.csv --export report.xlsx --format excel

# Export to CSV
python3 transaction_processor.py transactions.csv --export summary.csv --format csv
```

### Combined Operations
```bash
# Process, analyze, save, and export in one command
python3 transaction_processor.py transactions.csv --analyze --category "Shopping" --save backup.enc --export report.xlsx --format excel
```

## Command Line Options

### Credit Card Tracker (`credit_card_tracker.py`)

| Option | Description | Example |
|--------|-------------|---------|
| `--add-card` | Add new credit card | `--add-card "Chase" 10000 15 12 1200` |
| `--add-card-desc` | Description for new card | `--add-card-desc "Primary card"` |
| `--update-card` | Update existing card details | `--update-card "Chase" --credit-limit 15000` |
| `--remove-card` | Remove a credit card | `--remove-card "Old Card"` |
| `--list-cards` | List all configured cards | `--list-cards` |
| `--update-balance` | Update card balance | `--update-balance "Chase" 1234.56 current` |
| `--set-limits` | Set monthly spending limits | `--set-limits 2000 3000` |
| `--process-auto` | Auto-process transaction files | `--process-auto ~/Downloads/Chase*.csv` |
| `--reset-statement` | Reset for new statement period | `--reset-statement "Chase"` |
| `--reset` | Reset balances | `--reset current` |
| `--summary` | Show spending summary | `--summary` |
| `--due-dates` | Show upcoming due dates | `--due-dates` |

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

## How Categorization Works

1. **Bank Category First**: If your bank already categorized the transaction correctly (e.g., Chase labels it "Shopping"), we use that
2. **Smart Mapping**: Maps bank categories like "Health & Wellness" → Services
3. **Keyword Matching**: Analyzes transaction descriptions for merchants and keywords
4. **Fallback**: Uncategorized transactions go to "Other"

## Security Features

- **No Credentials Stored**: Never stores your bank login information
- **Local Processing**: Everything runs on your computer, no data sent online
- **Encrypted Storage**: Uses your system's secure keyring for encryption keys
- **Secure File Handling**: Encrypted backups protect your financial data

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
- **Encrypted Storage**: Backup files are encrypted using industry-standard encryption
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
- Use `--save` to backup your data before trying different analysis options