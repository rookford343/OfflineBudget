# Credit Card Transaction Processor

A secure, offline tool for analyzing credit card transactions. Automatically categorizes spending into 6 main categories and provides detailed financial insights without storing credentials or requiring internet access.

## Features

- **Universal Compatibility**: Works with CSV files from any credit card provider (Chase, Amex, Capital One, etc.)
- **Smart Categorization**: Uses bank's existing categories when possible, falls back to intelligent keyword matching
- **6 Core Categories**: Shopping, Food & Drinks, Services, Entertainment, Groceries, Other
- **Detailed Analysis**: Category breakdowns, spending totals, merchant analysis
- **Secure Storage**: Encrypts local data using your system's secure keyring
- **Offline Processing**: Everything runs locally on your machine

## Installation

### Requirements
- Python 3.7 or higher
- Required packages:

```bash
pip install pandas keyring cryptography
```

### Setup
1. Download `transaction_processor.py`
2. Make it executable:
```bash
chmod +x transaction_processor.py
```

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

### Basic Analysis
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