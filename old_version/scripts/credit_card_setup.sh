#!/bin/bash
# Example setup script for credit card tracker

echo "Setting up your credit cards..."

# Add your credit cards with their details
# Format: --add-card "Card Name" credit_limit statement_date due_date [balance_due] [current_balance] --add-card-desc "description"

python3 core/credit_card_tracker.py --add-card "Chase Sapphire" 24500 19 15 --add-card-desc "Primary rewards card"

python3 core/credit_card_tracker.py --add-card "Apple" 22000 28 17 --add-card-desc "Apple Card for Apple purchases"

python3 core/credit_card_tracker.py --add-card "Amex" 16600 3 17 --add-card-desc "Groceries & Gas expenses"

python3 core/credit_card_tracker.py --add-card "Citi" 42000 28 17 --add-card-desc "Backup card"

#python3 core/credit_card_tracker.py --add-card "Personal Chase" 3000 5 2 --add-card-desc "Personal card"

echo "Credit cards configured!"
echo "Run: python3 core/credit_card_tracker.py --list-cards to see your setup"
echo "Run: python3 core/credit_card_tracker.py --summary to see current spending"