#!/bin/bash
echo "Setting up Credit Card Tracker..."

# Create directories
mkdir -p data/transaction_files
mkdir -p data/uploads
mkdir -p web/static/{css,js,images}
mkdir -p web/templates
mkdir -p mobile
mkdir -p docs

# Create .gitkeep files
touch data/transaction_files/.gitkeep
touch data/uploads/.gitkeep

# Install dependencies
pip install -r requirements.txt

echo "✅ Setup complete!"
echo "Run: python3 web/web_api_server.py"
echo "Access: http://localhost:5000"