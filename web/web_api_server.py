#!/usr/bin/env python3
"""
Flask Web API Server for Credit Card Tracker
- Provides REST API endpoints for the web frontend
- Maintains security with encrypted local storage
- Handles file uploads for transaction processing
- Integrates with existing credit_card_tracker.py functionality
"""
import sys
import os
from pathlib import Path
import socket
import tempfile
import json
from datetime import datetime, timedelta

# Detect if we're running from web/ directory or project root
current_dir = Path(__file__).parent
if current_dir.name == 'web':
    # Running from web/ directory, so project root is parent
    project_root = current_dir.parent
    template_folder = 'templates'  # Relative to web/
    static_folder = 'static'       # Relative to web/
else:
    # Running from project root
    project_root = current_dir
    template_folder = 'web/templates'
    static_folder = 'web/static'

# Add project root to Python path for core imports
sys.path.insert(0, str(project_root))

print(f"🔍 Detected running from: {current_dir}")
print(f"📁 Project root: {project_root}")
print(f"📁 Template folder: {template_folder}")

# Import from core module
try:
    from core import CreditCardTracker, TimePeriodAnalyzer
    print("✅ Successfully imported core modules")
except ImportError as e:
    print(f"❌ Failed to import core modules: {e}")
    print(f"💡 Make sure you're running from the project root or web/ directory")
    sys.exit(1)

# Flask imports
from flask import Flask, request, jsonify, render_template, send_file, send_from_directory
from flask_cors import CORS
import pandas as pd
from werkzeug.utils import secure_filename

# Set up Flask app with correct template and static directories
app = Flask(__name__, 
            template_folder=template_folder,
            static_folder=static_folder)

CORS(app, origins=['http://localhost:*', 'http://127.0.0.1:*'])

# Configure upload settings
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size
UPLOAD_FOLDER = project_root / 'data' / 'uploads'
UPLOAD_FOLDER.mkdir(parents=True, exist_ok=True)
app.config['UPLOAD_FOLDER'] = str(UPLOAD_FOLDER)

# Ensure data directory exists
data_dir = project_root / 'data'
data_dir.mkdir(exist_ok=True)

# Global tracker instance
tracker = CreditCardTracker()

# =============================================================================
# MAIN ROUTES
# =============================================================================

@app.route('/')
def index():
    """Serve the main web interface."""
    try:
        return render_template('index.html')
    except Exception as e:
        print(f"❌ Error serving template: {e}")
        print(f"📁 Template folder: {os.path.abspath(app.template_folder)}")
        print(f"📄 Looking for: {os.path.join(os.path.abspath(app.template_folder), 'index.html')}")
        print(f"📄 File exists: {os.path.exists(os.path.join(app.template_folder, 'index.html'))}")
        
        # Fallback HTML with error details
        return f"""
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Credit Card Tracker - Template Error</title>
            <style>
                body {{ font-family: Arial, sans-serif; margin: 40px; background: #f5f5f5; }}
                .container {{ max-width: 800px; margin: 0 auto; background: white; padding: 30px; border-radius: 8px; }}
                .error {{ background: #fee; border: 1px solid #fcc; padding: 15px; border-radius: 5px; margin: 20px 0; }}
                .debug {{ background: #f0f8ff; border: 1px solid #cce; padding: 15px; border-radius: 5px; margin: 20px 0; }}
                code {{ background: #f8f8f8; padding: 2px 4px; border-radius: 3px; }}
            </style>
        </head>
        <body>
            <div class="container">
                <h1>💳 Credit Card Tracker</h1>
                <div class="error">
                    <h3>❌ Template Error</h3>
                    <p>Could not load index.html template: <code>{str(e)}</code></p>
                </div>
                <div class="debug">
                    <h3>🔍 Debug Information</h3>
                    <p><strong>Current directory:</strong> <code>{os.getcwd()}</code></p>
                    <p><strong>Template folder (relative):</strong> <code>{app.template_folder}</code></p>
                    <p><strong>Template folder (absolute):</strong> <code>{os.path.abspath(app.template_folder)}</code></p>
                    <p><strong>Looking for file:</strong> <code>{os.path.join(os.path.abspath(app.template_folder), 'index.html')}</code></p>
                    <p><strong>File exists:</strong> {os.path.exists(os.path.join(app.template_folder, 'index.html'))}</p>
                </div>
                <h3>✅ API Endpoints Available:</h3>
                <ul>
                    <li><a href="/api/health">/api/health</a> - Health check with debug info</li>
                    <li><a href="/api/debug">/api/debug</a> - Detailed debug information</li>
                    <li><a href="/api/summary">/api/summary</a> - Dashboard summary</li>
                    <li><a href="/api/cards">/api/cards</a> - Credit cards</li>
                    <li><a href="/api/mobile-summary">/api/mobile-summary</a> - Mobile summary</li>
                </ul>
            </div>
        </body>
        </html>
        """

@app.route('/favicon.ico')
def favicon():
    """Handle favicon requests."""
    try:
        return send_from_directory(app.static_folder, 'favicon.ico')
    except FileNotFoundError:
        return '', 204

# =============================================================================
# API ENDPOINTS - SYSTEM
# =============================================================================

@app.route('/api/health')
def health_check():
    """Simple health check endpoint."""
    return jsonify({
        'success': True,
        'message': 'Credit Card Tracker API is running',
        'timestamp': datetime.now().isoformat(),
        'version': '1.0.0',
        'cards_count': len(tracker.cards),
        'debug_info': {
            'current_directory': os.getcwd(),
            'project_root': str(project_root),
            'template_folder': app.template_folder,
            'template_folder_absolute': os.path.abspath(app.template_folder),
            'template_file_exists': os.path.exists(os.path.join(app.template_folder, 'index.html')),
            'static_folder': app.static_folder
        }
    })

@app.route('/api/debug')
def debug_info():
    """Debug endpoint for troubleshooting."""
    try:
        template_path = os.path.join(app.template_folder, 'index.html')
        return jsonify({
            'success': True,
            'data': {
                'cards_count': len(tracker.cards),
                'card_names': list(tracker.cards.keys()),
                'data_files_exist': {
                    'credit_cards.enc': (data_dir / 'credit_cards.enc').exists(),
                    'spending_limits.enc': (data_dir / 'spending_limits.enc').exists(),
                    'category_budgets.enc': (data_dir / 'category_budgets.enc').exists(),
                    'category_spending.enc': (data_dir / 'category_spending.enc').exists()
                },
                'tracker_initialized': hasattr(tracker, 'cipher_suite'),
                'paths': {
                    'current_directory': os.getcwd(),
                    'project_root': str(project_root),
                    'data_directory': str(data_dir),
                    'upload_folder': str(UPLOAD_FOLDER),
                    'template_folder_relative': app.template_folder,
                    'template_folder_absolute': os.path.abspath(app.template_folder),
                    'static_folder_relative': app.static_folder,
                    'static_folder_absolute': os.path.abspath(app.static_folder),
                },
                'files': {
                    'template_file_path': template_path,
                    'template_file_exists': os.path.exists(template_path),
                    'template_directory_exists': os.path.exists(app.template_folder),
                    'static_directory_exists': os.path.exists(app.static_folder),
                }
            }
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/routes')
def list_routes():
    """List all registered routes for debugging."""
    routes = []
    for rule in app.url_map.iter_rules():
        routes.append({
            'endpoint': rule.endpoint,
            'methods': list(rule.methods),
            'rule': str(rule)
        })
    return jsonify({
        'success': True,
        'routes': routes,
        'total_routes': len(routes)
    })

# =============================================================================
# API ENDPOINTS - DASHBOARD
# =============================================================================

@app.route('/api/summary', methods=['GET'])
def get_summary():
    """Get spending summary for dashboard with enhanced category information."""
    try:
        total_spending = 0.0
        balance_due = 0.0
        total_available = 0.0
        
        for name, card in tracker.cards.items():
            total_spending += card['current_balance']
            balance_due += card['balance_due']
            limit = card['credit_limit']
            total_balance = card['current_balance'] + card['balance_due']
            available = limit - total_balance
            total_available += available
        
        # Get spending limits
        limits = tracker.get_current_spending_limits()
        
        # Calculate left to spend
        if limits['soft_limit'] > 0:
            left_to_spend = limits['soft_limit'] - total_spending
            if limits['hard_limit'] > 0 and total_spending > limits['hard_limit']:
                spending_status = 'status-critical'
                spending_message = '🚨 CRITICAL - Over Hard Limit'
            elif total_spending > limits['soft_limit']:
                spending_status = 'status-warning'
                spending_message = '⚠️ CAUTION - Over Budget'
            else:
                spending_status = 'status-good'
                spending_message = '✅ Within Budget'
        else:
            left_to_spend = total_available
            spending_status = 'status-good'
            spending_message = '✅ No Limits Set'
        
        # Get due dates
        due_dates = get_due_dates_data()
        
        # Get category budgets with enhanced data
        category_budgets = get_category_budgets_data()
        
        # NEW: Get current month info for context
        current_month = datetime.now().strftime('%Y-%m')
        
        return jsonify({
            'success': True,
            'data': {
                'total_spending': total_spending,
                'balance_due': balance_due,
                'left_to_spend': left_to_spend,
                'available_credit': total_available,
                'spending_status': spending_status,
                'spending_message': spending_message,
                'due_dates': due_dates,
                'category_budgets': category_budgets,
                'current_month': current_month,
                'limits': limits  # Include raw limits for frontend
            }
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

# =============================================================================
# API ENDPOINTS - CREDIT CARDS
# =============================================================================

@app.route('/api/cards', methods=['GET'])
def get_cards():
    """Get all credit cards."""
    try:
        cards_data = []
        for name, card in tracker.cards.items():
            total_balance = card['current_balance'] + card['balance_due']
            available_credit = card['credit_limit'] - total_balance
            
            cards_data.append({
                'name': name,
                'credit_limit': card['credit_limit'],
                'current_balance': card['current_balance'],
                'balance_due': card['balance_due'],
                'available_credit': available_credit,
                'statement_date': card['statement_date'],
                'due_date': card['due_date'],
                'description': card.get('description', '')
            })
        
        return jsonify({'success': True, 'data': cards_data})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/cards', methods=['POST'])
def add_card():
    """Add a new credit card."""
    try:
        data = request.get_json()
        
        tracker.add_card(
            name=data['name'],
            credit_limit=data['credit_limit'],
            statement_date=data['statement_date'],
            due_date=data['due_date'],
            description=data.get('description', ''),
            balance_due=data.get('balance_due', 0.0),
            current_balance=data.get('current_balance', 0.0)
        )
        
        return jsonify({'success': True, 'message': 'Card added successfully'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/cards/<card_name>', methods=['PUT'])
def update_card(card_name):
    """Update an existing credit card."""
    try:
        data = request.get_json()
        
        # Build update kwargs from provided data
        update_kwargs = {}
        if 'credit_limit' in data:
            update_kwargs['credit_limit'] = data['credit_limit']
        if 'statement_date' in data:
            update_kwargs['statement_date'] = data['statement_date']
        if 'due_date' in data:
            update_kwargs['due_date'] = data['due_date']
        if 'description' in data:
            update_kwargs['description'] = data['description']
        if 'current_balance' in data:
            update_kwargs['current_balance'] = data['current_balance']
        if 'balance_due' in data:
            update_kwargs['balance_due'] = data['balance_due']
        
        tracker.update_card(card_name, **update_kwargs)
        return jsonify({'success': True, 'message': 'Card updated successfully'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/cards/<card_name>', methods=['DELETE'])
def remove_card(card_name):
    """Remove a credit card."""
    try:
        tracker.remove_card(card_name)
        return jsonify({'success': True, 'message': 'Card removed successfully'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/balance/<card_name>', methods=['PUT'])
def update_balance(card_name):
    """Update a specific card balance."""
    try:
        data = request.get_json()
        amount = float(data.get('amount', 0))
        balance_type = data.get('type', 'current')  # current or due
        
        if balance_type not in ['current', 'due']:
            return jsonify({'success': False, 'error': 'Invalid balance type'})
        
        tracker.update_balance(card_name, amount, balance_type)
        return jsonify({'success': True, 'message': f'Updated {card_name} {balance_type} balance'})
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

# =============================================================================
# API ENDPOINTS - BUDGETS AND LIMITS
# =============================================================================

@app.route('/api/spending-limits', methods=['POST'])
def set_spending_limits():
    """Set monthly spending limits."""
    try:
        data = request.get_json()
        soft_limit = data.get('soft_limit', 0)
        hard_limit = data.get('hard_limit', 0)
        
        tracker.set_spending_limits(soft_limit, hard_limit)
        return jsonify({'success': True, 'message': 'Spending limits set successfully'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/category-budgets', methods=['POST'])
def set_category_budgets():
    """Set category budgets."""
    try:
        data = request.get_json()
        
        # Filter out empty/zero budgets
        budgets = {}
        for category, amount in data.items():
            if amount and float(amount) > 0:
                budgets[category] = float(amount)
        
        if budgets:
            tracker.set_category_budgets(**budgets)
            return jsonify({'success': True, 'message': 'Category budgets set successfully'})
        else:
            return jsonify({'success': False, 'error': 'No valid budgets provided'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

# =============================================================================
# API ENDPOINTS - TRANSACTION PROCESSING
# =============================================================================

@app.route('/api/upload-transactions', methods=['POST'])
def upload_transactions():
    """Upload and process transaction CSV files with better error handling."""
    try:
        print("\n📁 UPLOAD TRANSACTIONS ENDPOINT CALLED")
        
        # Check if files were provided
        if 'files' not in request.files:
            print("❌ No 'files' field in request")
            return jsonify({'success': False, 'error': 'No files provided in request'}), 400
        
        files = request.files.getlist('files')
        print(f"📋 Received {len(files)} file(s)")
        
        if not files or len(files) == 0:
            print("❌ File list is empty")
            return jsonify({'success': False, 'error': 'No files selected'}), 400
        
        # Check first file to ensure it's not empty
        first_file = files[0]
        if first_file.filename == '':
            print("❌ First file has no filename")
            return jsonify({'success': False, 'error': 'No files selected'}), 400
        
        # Get processing options
        auto_update = request.form.get('auto_update', 'true').lower() == 'true'
        update_categories = request.form.get('update_categories', 'true').lower() == 'true'
        current_month_only = request.form.get('current_month_only', 'false').lower() == 'true'
        
        print(f"⚙️ Options: auto_update={auto_update}, update_categories={update_categories}, current_month_only={current_month_only}")
        
        # Save uploaded files temporarily
        temp_files = []
        for file in files:
            if file and file.filename:
                # Check file extension
                filename = file.filename.lower()
                if not (filename.endswith('.csv') or filename.endswith('.txt')):
                    print(f"⚠️ Skipping non-CSV file: {file.filename}")
                    continue
                
                # Save file
                safe_filename = secure_filename(file.filename)
                filepath = os.path.join(app.config['UPLOAD_FOLDER'], safe_filename)
                
                print(f"💾 Saving file: {safe_filename} to {filepath}")
                file.save(filepath)
                
                # Verify file was saved and has content
                if os.path.exists(filepath) and os.path.getsize(filepath) > 0:
                    temp_files.append(filepath)
                    print(f"✅ File saved successfully: {safe_filename} ({os.path.getsize(filepath)} bytes)")
                else:
                    print(f"❌ File save failed or empty: {safe_filename}")
        
        if not temp_files:
            print("❌ No valid CSV files were saved")
            return jsonify({'success': False, 'error': 'No valid CSV files found. Please ensure files are CSV format and not empty.'}), 400
        
        print(f"📊 Processing {len(temp_files)} CSV file(s)")
        
        # Enhanced categorization preview
        categorization_preview = {}
        
        if update_categories:
            print(f"\n🔍 ANALYZING CATEGORIZATION FOR {len(temp_files)} FILES")
            
            for file_path in temp_files:
                filename = os.path.basename(file_path)
                print(f"\n📄 Processing: {filename}")
                
                try:
                    # Process the CSV file
                    df = tracker._process_csv_file(file_path)
                    
                    if df.empty:
                        print(f"⚠️ Empty dataframe for {filename}")
                        continue
                    
                    print(f"📊 Loaded {len(df)} transactions from {filename}")
                    
                    # Check for required columns
                    required_cols = ['Amount', 'Description']
                    missing_cols = [col for col in required_cols if col not in df.columns]
                    if missing_cols:
                        print(f"⚠️ Missing columns in {filename}: {missing_cols}")
                        print(f"   Available columns: {list(df.columns)}")
                        continue
                    
                    # Filter to spending transactions (negative amounts)
                    spending_df = df[df['Amount'] < 0].copy()
                    
                    if spending_df.empty:
                        print(f"⚠️ No spending transactions in {filename}")
                        continue
                    
                    print(f"💰 Found {len(spending_df)} spending transactions")
                    
                    # Sample transactions for preview
                    sample_size = min(15, len(spending_df))
                    sample_df = spending_df.head(sample_size)
                    
                    preview_results = []
                    
                    for idx, row in sample_df.iterrows():
                        description = str(row.get('Description', ''))
                        original_category = str(row.get('Category', ''))
                        memo = str(row.get('Memo', ''))
                        
                        # Test categorization
                        category = tracker._categorize_transaction(description, memo, original_category)
                        amount = abs(float(row.get('Amount', 0)))
                        
                        preview_results.append({
                            'description': description[:50],  # Truncate for preview
                            'original_category': original_category,
                            'assigned_category': category,
                            'amount': amount
                        })
                        
                        # Debug first few
                        if len(preview_results) <= 3:
                            print(f"  '{description[:40]}' -> {category}")
                    
                    categorization_preview[filename] = preview_results
                    
                    # Summary statistics
                    category_counts = {}
                    for result in preview_results:
                        cat = result['assigned_category']
                        category_counts[cat] = category_counts.get(cat, 0) + 1
                    
                    print(f"📊 Category distribution for {filename}:")
                    for cat, count in sorted(category_counts.items()):
                        print(f"   {cat}: {count} transactions")
                    
                except Exception as e:
                    print(f"❌ Error processing {filename}: {str(e)}")
                    import traceback
                    traceback.print_exc()
        
        # Process the files for balance updates
        try:
            if auto_update:
                print("\n💳 Updating card balances...")
                tracker.process_transactions_auto(temp_files, use_current_month_only=current_month_only)
                message = f'Processed {len(temp_files)} file(s) and updated card balances'
            else:
                print("\n📊 Updating category spending only...")
                # Just update categories without updating balances
                all_dfs = []
                for file_path in temp_files:
                    df = tracker._process_csv_file(file_path)
                    if not df.empty:
                        all_dfs.append(df)
                
                if all_dfs and update_categories:
                    combined_df = pd.concat(all_dfs, ignore_index=True) if len(all_dfs) > 1 else all_dfs[0]
                    tracker._update_category_spending(combined_df, use_current_month_only=current_month_only)
                    
                    filter_msg = " (current month only)" if current_month_only else " (all months)"
                    message = f'Processed {len(temp_files)} file(s) and updated category spending{filter_msg}'
                else:
                    message = f'Analyzed {len(temp_files)} file(s)'
            
            print(f"✅ {message}")
            
        except Exception as e:
            print(f"❌ Error during processing: {str(e)}")
            import traceback
            traceback.print_exc()
            message = f"Partial processing completed with errors: {str(e)}"
        
        # Clean up temp files
        for filepath in temp_files:
            try:
                os.remove(filepath)
                print(f"🗑️ Cleaned up temp file: {os.path.basename(filepath)}")
            except:
                pass
        
        # Return success response
        return jsonify({
            'success': True,
            'message': message,
            'files_processed': len(temp_files),
            'current_month_filtering': current_month_only if update_categories else None,
            'categorization_preview': categorization_preview if categorization_preview else None
        })
        
    except Exception as e:
        print(f"❌ Upload transactions error: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

# NEW: Add categorization test endpoint
@app.route('/api/test-categorization', methods=['POST'])
def test_categorization():
    """Test categorization on sample transaction descriptions."""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': 'No JSON data provided'})
        
        test_transactions = data.get('transactions', [])
        if not test_transactions:
            return jsonify({'success': False, 'error': 'No transactions provided'})
        
        print(f"\n🧪 TESTING CATEGORIZATION FOR {len(test_transactions)} TRANSACTIONS")
        
        results = []
        for i, transaction in enumerate(test_transactions):
            description = transaction.get('description', '')
            memo = transaction.get('memo', '')
            original_category = transaction.get('original_category', '')
            
            print(f"\nTest {i+1}: '{description}' (orig: '{original_category}')")
            
            assigned_category = tracker._categorize_transaction(description, memo, original_category)
            
            print(f"  → Assigned: {assigned_category}")
            
            results.append({
                'input': {
                    'description': description,
                    'memo': memo,
                    'original_category': original_category
                },
                'assigned_category': assigned_category
            })
        
        print(f"\n✅ Categorization test completed")
        
        return jsonify({
            'success': True,
            'results': results,
            'test_count': len(results)
        })
        
    except Exception as e:
        print(f"❌ Test categorization error: {e}")
        return jsonify({'success': False, 'error': str(e)})
    
@app.route('/api/analyze-csv-structure', methods=['POST'])
def analyze_csv_structure():
    """Analyze CSV structure without processing transactions."""
    try:
        if 'file' not in request.files:
            return jsonify({'success': False, 'error': 'No file provided'})
        
        file = request.files['file']
        if not file.filename.endswith('.csv'):
            return jsonify({'success': False, 'error': 'File must be CSV'})
        
        # Read and analyze CSV structure
        content = file.read().decode('utf-8')
        lines = content.strip().split('\n')
        
        if len(lines) < 2:
            return jsonify({'success': False, 'error': 'CSV must have header and data'})
        
        # Parse header
        import csv
        import io
        csv_reader = csv.reader(io.StringIO(content))
        headers = next(csv_reader)
        
        # Analyze first few rows
        sample_rows = []
        row_count = 0
        for row in csv_reader:
            if row_count >= 5:  # Only sample first 5 rows
                break
            sample_rows.append(row)
            row_count += 1
        
        # Find key columns
        description_col = find_description_column(headers)
        amount_col = find_amount_column(headers)
        date_col = find_date_column(headers)
        category_col = find_category_column(headers)
        
        # Extract sample descriptions
        sample_descriptions = []
        if description_col != -1:
            sample_descriptions = [row[description_col] for row in sample_rows 
                                 if len(row) > description_col and row[description_col].strip()]
        
        analysis = {
            'filename': file.filename,
            'total_rows': len(lines) - 1,
            'headers': headers,
            'column_count': len(headers),
            'key_columns': {
                'description': description_col,
                'amount': amount_col,
                'date': date_col,
                'category': category_col
            },
            'sample_descriptions': sample_descriptions[:5],
            'sample_rows': sample_rows[:3],  # First 3 rows for structure analysis
            'quality_assessment': assess_csv_quality(headers, sample_rows, description_col)
        }
        
        return jsonify({'success': True, 'data': analysis})
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

def find_description_column(headers):
    """Find the column most likely to contain transaction descriptions."""
    description_patterns = ['description', 'merchant', 'payee', 'desc', 'vendor', 'details']
    
    for i, header in enumerate(headers):
        header_lower = header.lower().strip()
        for pattern in description_patterns:
            if pattern in header_lower:
                print(f"Found description column: '{header}' at index {i}")
                return i
    return -1

def find_amount_column(headers):
    """Find the amount column."""
    for i, header in enumerate(headers):
        header_lower = header.lower().strip()
        if header_lower == 'amount' or (header_lower.startswith('amount') and 'original' not in header_lower):
            return i
    return -1

def find_date_column(headers):
    """Find the transaction date column."""
    for i, header in enumerate(headers):
        header_lower = header.lower().strip()
        if 'transaction' in header_lower and 'date' in header_lower:
            return i
        elif header_lower == 'date':
            return i
    return -1

def find_category_column(headers):
    """Find the category column."""
    for i, header in enumerate(headers):
        header_lower = header.lower().strip()
        if header_lower == 'category' or header_lower == 'cat':
            return i
    return -1

def assess_csv_quality(headers, sample_rows, description_col):
    """Assess the quality of CSV data for categorization."""
    issues = []
    quality_score = 100
    
    # Check if description column exists
    if description_col == -1:
        issues.append("No description/merchant column found")
        quality_score -= 50
    else:
        # Check quality of descriptions
        if sample_rows:
            valid_descriptions = 0
            for row in sample_rows:
                if len(row) > description_col:
                    desc = row[description_col].strip()
                    if desc and len(desc) > 3 and desc not in ['Sale', 'Purchase', 'Transaction']:
                        valid_descriptions += 1
            
            description_quality = valid_descriptions / len(sample_rows) if sample_rows else 0
            if description_quality < 0.5:
                issues.append(f"Poor description quality: {valid_descriptions}/{len(sample_rows)} valid")
                quality_score -= 30
            elif description_quality < 0.8:
                issues.append(f"Moderate description quality: {valid_descriptions}/{len(sample_rows)} valid")
                quality_score -= 15
    
    # Determine overall quality
    if quality_score >= 85:
        quality_level = "Excellent"
    elif quality_score >= 70:
        quality_level = "Good"
    elif quality_score >= 50:
        quality_level = "Fair"
    else:
        quality_level = "Poor"
    
    return {
        'quality_level': quality_level,
        'quality_score': quality_score,
        'issues': issues,
        'description_column_found': description_col != -1,
        'estimated_categorization_success': max(0, quality_score - 20)  # Rough estimate
    }

@app.route('/api/test-categorization-enhanced', methods=['POST'])
def test_categorization_enhanced():
    """Enhanced categorization testing with detailed analysis."""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': 'No JSON data provided'})
        
        test_transactions = data.get('transactions', [])
        if not test_transactions:
            return jsonify({'success': False, 'error': 'No transactions provided'})
        
        print(f"\n🧪 ENHANCED CATEGORIZATION TEST FOR {len(test_transactions)} TRANSACTIONS")
        
        # Reset debug counter for clean output
        tracker._debug_count = 0
        
        results = []
        category_stats = {}
        unknown_descriptions = []
        
        for i, transaction in enumerate(test_transactions):
            description = transaction.get('description', '')
            memo = transaction.get('memo', '')
            original_category = transaction.get('original_category', '')
            
            print(f"\nTest {i+1}: '{description}' (orig: '{original_category}')")
            
            # Test categorization
            assigned_category = tracker._categorize_transaction(description, memo, original_category)
            
            # Collect statistics
            category_stats[assigned_category] = category_stats.get(assigned_category, 0) + 1
            
            # Track problematic descriptions
            if assigned_category == 'Other' and description.strip():
                unknown_descriptions.append(description)
            
            result = {
                'input': {
                    'description': description,
                    'memo': memo,
                    'original_category': original_category
                },
                'assigned_category': assigned_category,
                'is_problematic': assigned_category == 'Other' and len(description.strip()) > 0
            }
            
            results.append(result)
            print(f"  → Assigned: {assigned_category}")
        
        # Calculate quality metrics
        total_transactions = len(results)
        other_count = category_stats.get('Other', 0)
        success_rate = ((total_transactions - other_count) / total_transactions * 100) if total_transactions > 0 else 0
        
        # Generate recommendations
        recommendations = generate_categorization_recommendations(results, unknown_descriptions)
        
        print(f"\n✅ Enhanced categorization test completed")
        print(f"Success rate: {success_rate:.1f}% ({total_transactions - other_count}/{total_transactions})")
        
        return jsonify({
            'success': True,
            'results': results,
            'statistics': {
                'total_transactions': total_transactions,
                'category_distribution': category_stats,
                'success_rate': success_rate,
                'other_count': other_count,
                'problematic_descriptions': unknown_descriptions[:10]  # First 10 problematic ones
            },
            'recommendations': recommendations,
            'quality_assessment': assess_categorization_quality(success_rate, category_stats)
        })
        
    except Exception as e:
        print(f"❌ Enhanced categorization test error: {e}")
        return jsonify({'success': False, 'error': str(e)})

def generate_categorization_recommendations(results, unknown_descriptions):
    """Generate recommendations for improving categorization."""
    recommendations = []
    
    # Count problematic transactions
    problematic_count = len([r for r in results if r['is_problematic']])
    total_count = len(results)
    problematic_rate = problematic_count / total_count if total_count > 0 else 0
    
    if problematic_count == 0:
        recommendations.append({
            'type': 'success',
            'message': '✅ Excellent categorization! All transactions properly classified.',
            'action': 'Your CSV data is well-formatted for categorization.'
        })
    elif problematic_rate < 0.2:  # Less than 20% problematic
        recommendations.append({
            'type': 'good',
            'message': f'✅ Good categorization! Only {problematic_count}/{total_count} transactions need attention.',
            'action': 'Minor improvements possible but overall quality is good.'
        })
    elif problematic_rate < 0.5:  # Less than 50% problematic
        recommendations.append({
            'type': 'warning',
            'message': f'⚠️ Moderate categorization issues. {problematic_count}/{total_count} transactions going to "Other".',
            'action': 'Consider reviewing your CSV format or merchant descriptions.'
        })
    else:  # 50% or more problematic
        recommendations.append({
            'type': 'error',
            'message': f'❌ Poor categorization! {problematic_count}/{total_count} transactions going to "Other".',
            'action': 'Your CSV descriptions may be getting corrupted during conversion.'
        })
    
    # Analyze common issues
    if unknown_descriptions:
        # Check for generic descriptions
        generic_descriptions = [desc for desc in unknown_descriptions 
                              if desc.lower() in ['unknown transaction', 'sale', 'purchase', 'payment', 'transaction']]
        
        if len(generic_descriptions) > 0:
            recommendations.append({
                'type': 'critical',
                'message': '🚨 Generic descriptions detected!',
                'action': 'Your CSV conversion is replacing merchant names with generic terms. Try uploading the original CSV file without conversion.',
                'details': f'Found {len(generic_descriptions)} generic descriptions like "Unknown Transaction"'
            })
        
        # Check for missing merchant info
        short_descriptions = [desc for desc in unknown_descriptions if len(desc.strip()) < 5]
        if len(short_descriptions) > 0:
            recommendations.append({
                'type': 'warning',
                'message': '⚠️ Very short or empty descriptions found.',
                'action': 'Check if your CSV has a proper description/merchant column.',
                'details': f'Found {len(short_descriptions)} very short descriptions'
            })
        
        # Sample problematic descriptions for user review
        if len(unknown_descriptions) > 0:
            sample_unknown = unknown_descriptions[:5]
            quoted_descriptions = [f'"{desc}"' for desc in sample_unknown]
            recommendations.append({
                'type': 'info',
                'message': '🔍 Sample problematic descriptions:',
                'action': 'Review these to understand the pattern.',
                'details': f'Examples: {", ".join(quoted_descriptions)}'
            })
    
    return recommendations

def assess_categorization_quality(success_rate, category_stats):
    """Assess overall categorization quality."""
    total_categories = len([cat for cat in category_stats.keys() if cat != 'Other'])
    other_percentage = category_stats.get('Other', 0) / sum(category_stats.values()) * 100 if category_stats else 100
    
    if success_rate >= 90:
        quality = 'Excellent'
        color = '#16a34a'  # Green
    elif success_rate >= 75:
        quality = 'Good'
        color = '#22c55e'  # Light green
    elif success_rate >= 50:
        quality = 'Fair'
        color = '#f59e0b'  # Yellow
    else:
        quality = 'Poor'
        color = '#dc2626'  # Red
    
    return {
        'quality_level': quality,
        'quality_color': color,
        'success_rate': success_rate,
        'other_percentage': other_percentage,
        'categories_used': total_categories,
        'distribution_balance': 'Good' if total_categories >= 3 else 'Concentrated'
    }

@app.route('/api/reset-category-spending-enhanced', methods=['POST'])
def reset_category_spending_enhanced():
    """Enhanced category spending reset with validation."""
    try:
        data = request.get_json() or {}
        target_month = data.get('month')  # Optional YYYY-MM format
        
        # Validate month format if provided
        if target_month:
            try:
                from datetime import datetime
                datetime.strptime(target_month, '%Y-%m')
            except ValueError:
                return jsonify({
                    'success': False, 
                    'error': 'Invalid month format. Use YYYY-MM (e.g., 2025-08)'
                })
        
        # Get current state before reset
        current_month = target_month or datetime.now().strftime('%Y-%m')
        old_spending = tracker.category_spending.get(current_month, {})
        old_total = sum(old_spending.values()) if old_spending else 0
        
        # Perform reset
        success = tracker.reset_category_spending(target_month)
        
        if success:
            # Get new state after reset
            new_spending = tracker.category_spending.get(current_month, {})
            
            return jsonify({
                'success': True, 
                'message': f'Category spending reset for {current_month}',
                'data': {
                    'month': current_month,
                    'old_total': old_total,
                    'old_spending': old_spending,
                    'new_spending': new_spending,
                    'categories_reset': list(new_spending.keys())
                }
            })
        else:
            return jsonify({
                'success': False, 
                'error': 'Failed to reset category spending'
            })
            
    except Exception as e:
        print(f"❌ Enhanced category reset error: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/debug-categorization-detailed', methods=['GET'])
def debug_categorization_detailed():
    """Detailed categorization debugging endpoint."""
    try:
        current_month = datetime.now().strftime('%Y-%m')
        
        # Get comprehensive debug information
        debug_info = {
            'current_month': current_month,
            'tracker_state': {
                'cards_count': len(tracker.cards),
                'card_names': list(tracker.cards.keys()),
                'total_card_spending': sum(card['current_balance'] for card in tracker.cards.values()),
            },
            'category_data': {
                'current_month_spending': tracker.category_spending.get(current_month, {}),
                'all_months_data': tracker.category_spending,
                'available_months': list(tracker.category_spending.keys()),
                'total_months': len(tracker.category_spending)
            },
            'categorization_system': {
                'available_categories': ['Shopping', 'Food & Drinks', 'Services', 'Entertainment', 'Groceries', 'Other'],
                'keyword_examples': get_categorization_examples(),
                'debug_counter': getattr(tracker, '_debug_count', 0)
            },
            'budget_info': {
                'spending_limits': tracker.get_current_spending_limits(),
                'category_budgets': tracker.get_current_category_budgets(),
            },
            'system_info': {
                'timestamp': datetime.now().isoformat(),
                'encryption_active': hasattr(tracker, 'cipher_suite'),
                'data_files_exist': check_data_files_exist()
            }
        }
        
        # Calculate some summary statistics
        current_spending = debug_info['category_data']['current_month_spending']
        debug_info['summary_stats'] = {
            'current_month_total': sum(current_spending.values()) if current_spending else 0,
            'categories_with_spending': len([k for k, v in current_spending.items() if v > 0]) if current_spending else 0,
            'largest_category': max(current_spending.items(), key=lambda x: x[1]) if current_spending else ('None', 0),
            'spending_distribution': {k: f"{(v/sum(current_spending.values())*100):.1f}%" 
                                   for k, v in current_spending.items() if sum(current_spending.values()) > 0} if current_spending else {}
        }
        
        return jsonify({
            'success': True,
            'data': debug_info
        })
        
    except Exception as e:
        print(f"❌ Detailed debug error: {e}")
        return jsonify({'success': False, 'error': str(e)})

def get_categorization_examples():
    """Get examples of keywords for each category."""
    return {
        'Groceries': ['whole foods', 'kroger', 'safeway', 'trader joes', 'costco', 'grocery'],
        'Food & Drinks': ['starbucks', 'mcdonalds', 'chipotle', 'restaurant', 'coffee', 'pizza'],
        'Shopping': ['amazon', 'target', 'walmart', 'best buy', 'shopping', 'retail'],
        'Services': ['netflix', 'spotify', 'insurance', 'utility', 'subscription', 'phone'],
        'Entertainment': ['movie', 'uber', 'hotel', 'travel', 'concert', 'recreation'],
        'Other': ['transactions that don\'t match any keywords above']
    }

def check_data_files_exist():
    """Check if encrypted data files exist."""
    from pathlib import Path
    data_dir = Path(tracker._get_data_directory())
    
    return {
        'credit_cards.enc': (data_dir / 'credit_cards.enc').exists(),
        'spending_limits.enc': (data_dir / 'spending_limits.enc').exists(),
        'category_budgets.enc': (data_dir / 'category_budgets.enc').exists(),
        'category_spending.enc': (data_dir / 'category_spending.enc').exists(),
        'historical_spending.enc': (data_dir / 'historical_spending.enc').exists()
    }

@app.route('/api/validate-csv-upload', methods=['POST'])
def validate_csv_upload():
    """Validate CSV file before processing."""
    try:
        if 'file' not in request.files:
            return jsonify({'success': False, 'error': 'No file provided'})
        
        file = request.files['file']
        if not file.filename.lower().endswith('.csv'):
            return jsonify({'success': False, 'error': 'File must be a CSV'})
        
        # Read and validate CSV content
        content = file.read().decode('utf-8', errors='replace')
        lines = content.strip().split('\n')
        
        if len(lines) < 2:
            return jsonify({
                'success': False, 
                'error': 'CSV file must have at least a header row and one data row'
            })
        
        # Parse and analyze
        import csv
        import io
        
        try:
            csv_reader = csv.reader(io.StringIO(content))
            headers = next(csv_reader)
            sample_rows = [row for i, row in enumerate(csv_reader) if i < 5]  # First 5 data rows
        except Exception as e:
            return jsonify({
                'success': False, 
                'error': f'CSV parsing failed: {str(e)}'
            })
        
        # Analyze structure
        analysis = {
            'filename': file.filename,
            'total_rows': len(lines) - 1,
            'headers': headers,
            'sample_rows': sample_rows[:3],  # Only first 3 for security
            'structure_quality': analyze_csv_structure_quality(headers, sample_rows)
        }
        
        return jsonify({'success': True, 'data': analysis})
        
    except Exception as e:
        return jsonify({'success': False, 'error': f'Validation failed: {str(e)}'})

def analyze_csv_structure_quality(headers, sample_rows):
    """Analyze CSV structure quality for categorization."""
    issues = []
    score = 100
    
    # Check for essential columns
    has_description = any('description' in h.lower() or 'merchant' in h.lower() 
                         for h in headers)
    has_amount = any('amount' in h.lower() for h in headers)
    has_date = any('date' in h.lower() for h in headers)
    
    if not has_description:
        issues.append("No description/merchant column found")
        score -= 40
    if not has_amount:
        issues.append("No amount column found")
        score -= 30
    if not has_date:
        issues.append("No date column found")
        score -= 20
    
    # Check data quality in sample rows
    if has_description and sample_rows:
        desc_col = next((i for i, h in enumerate(headers) 
                        if 'description' in h.lower() or 'merchant' in h.lower()), -1)
        
        if desc_col != -1:
            valid_descriptions = 0
            for row in sample_rows:
                if len(row) > desc_col and row[desc_col].strip():
                    desc = row[desc_col].strip()
                    if len(desc) > 3 and desc.lower() not in ['sale', 'purchase', 'transaction']:
                        valid_descriptions += 1
            
            desc_quality = valid_descriptions / len(sample_rows) if sample_rows else 0
            if desc_quality < 0.5:
                issues.append(f"Poor description quality: only {valid_descriptions}/{len(sample_rows)} rows have meaningful descriptions")
                score -= 25
    
    # Determine quality level
    if score >= 90:
        quality_level = "Excellent"
        quality_color = "#16a34a"
    elif score >= 70:
        quality_level = "Good" 
        quality_color = "#22c55e"
    elif score >= 50:
        quality_level = "Fair"
        quality_color = "#f59e0b"
    else:
        quality_level = "Poor"
        quality_color = "#dc2626"
    
    return {
        'quality_level': quality_level,
        'quality_color': quality_color,
        'score': score,
        'issues': issues,
        'has_essential_columns': has_description and has_amount and has_date,
        'categorization_potential': max(0, score - 10)  # Rough estimate
    }

# =============================================================================
# API ENDPOINTS - HISTORICAL ANALYSIS
# =============================================================================

@app.route('/api/historical-analyses', methods=['GET'])
def get_historical_analyses():
    """Get list of stored historical analyses."""
    try:
        # Create analyzer to access historical data
        analyzer = TimePeriodAnalyzer(tracker)
        
        # Format the historical data for the frontend
        analyses = []
        for name, data in analyzer.historical_data.items():
            analyses.append({
                'name': name,
                'created_date': data.get('created_date', 'Unknown'),
                'period_count': len(data.get('analysis', {})),
                'metadata': data.get('metadata', {})
            })
        
        return jsonify({'success': True, 'data': analyses})
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/historical-analyses/<analysis_name>', methods=['GET'])
def get_historical_analysis(analysis_name):
    """Get a specific historical analysis."""
    try:
        analyzer = TimePeriodAnalyzer(tracker)
        analysis = analyzer.load_stored_analysis(analysis_name)
        
        if analysis:
            return jsonify({'success': True, 'data': analysis})
        else:
            return jsonify({'success': False, 'error': f'Analysis "{analysis_name}" not found'})
            
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/compare-analyses', methods=['POST'])
def compare_analyses():
    """Compare two historical analyses."""
    try:
        data = request.get_json()
        analysis1_name = data.get('analysis1')
        analysis2_name = data.get('analysis2')
        
        if not analysis1_name or not analysis2_name:
            return jsonify({'success': False, 'error': 'Both analysis names are required'})
        
        analyzer = TimePeriodAnalyzer(tracker)
        analysis1 = analyzer.load_stored_analysis(analysis1_name)
        analysis2 = analyzer.load_stored_analysis(analysis2_name)
        
        if not analysis1:
            return jsonify({'success': False, 'error': f'Analysis "{analysis1_name}" not found'})
        if not analysis2:
            return jsonify({'success': False, 'error': f'Analysis "{analysis2_name}" not found'})
        
        # Find common periods
        periods1 = set(analysis1.keys())
        periods2 = set(analysis2.keys())
        common_periods = periods1.intersection(periods2)
        
        comparison_data = []
        for period in sorted(common_periods):
            total1 = analysis1[period]['total_spending']
            total2 = analysis2[period]['total_spending']
            diff = total1 - total2
            
            comparison_data.append({
                'period': period,
                'analysis1_total': total1,
                'analysis2_total': total2,
                'difference': diff,
                'percent_change': (diff / total2 * 100) if total2 > 0 else 0
            })
        
        return jsonify({
            'success': True,
            'data': {
                'analysis1_name': analysis1_name,
                'analysis2_name': analysis2_name,
                'common_periods': len(common_periods),
                'comparisons': comparison_data
            }
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

# =============================================================================
# API ENDPOINTS - DATA MANAGEMENT
# =============================================================================

@app.route('/api/reset-statement', methods=['POST'])
def reset_statement_period():
    """Reset statement period for cards."""
    try:
        data = request.get_json()
        card_name = data.get('card_name')  # If None, resets all cards
        
        tracker.reset_statement_period(card_name)
        
        if card_name:
            message = f'Reset statement period for {card_name}'
        else:
            message = 'Reset statement period for all cards'
            
        return jsonify({'success': True, 'message': message})
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/reset-balances', methods=['POST'])
def reset_balances():
    """Reset card balances."""
    try:
        data = request.get_json()
        balance_type = data.get('type', 'current')  # current, due, or all
        
        if balance_type not in ['current', 'due', 'all']:
            return jsonify({'success': False, 'error': 'Invalid balance type'})
        
        tracker.reset_balances(balance_type)
        
        type_names = {
            'current': 'current balances',
            'due': 'due balances', 
            'all': 'all balances'
        }
        
        return jsonify({'success': True, 'message': f'Reset {type_names[balance_type]} successfully'})
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})
    
# =============================================================================
# NEW API ENDPOINTS - CATEGORY MANAGEMENT
# =============================================================================

@app.route('/api/reset-category-spending', methods=['POST'])
def reset_category_spending():
    """Reset category spending for current month or specified month."""
    try:
        data = request.get_json() or {}
        target_month = data.get('month')  # Optional YYYY-MM format
        
        success = tracker.reset_category_spending(target_month)
        
        if success:
            current_month = target_month or datetime.now().strftime('%Y-%m')
            return jsonify({
                'success': True, 
                'message': f'Category spending reset for {current_month}',
                'month': current_month
            })
        else:
            return jsonify({
                'success': False, 
                'error': 'Failed to reset category spending'
            })
            
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/category-spending', methods=['GET'])
def get_category_spending():
    """Get category spending for current or specified month with debugging info."""
    try:
        month = request.args.get('month')  # Optional YYYY-MM format
        
        if month:
            # Get spending for specific month
            spending = tracker.category_spending.get(month, {})
        else:
            # Get current month spending
            spending = tracker._get_category_spending()
            month = datetime.now().strftime('%Y-%m')
        
        # Calculate totals for debugging
        total_spending = sum(spending.values())
        non_zero_categories = {k: v for k, v in spending.items() if v > 0}
        
        return jsonify({
            'success': True,
            'data': {
                'month': month,
                'categories': spending,
                'total_spending': total_spending,
                'non_zero_categories': non_zero_categories,
                'categories_with_spending': len(non_zero_categories),
                'all_months_available': list(tracker.category_spending.keys())
            }
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})
    
@app.route('/api/debug-categories', methods=['GET'])
def debug_categories():
    """Debug endpoint to show all category spending data with categorization info."""
    try:
        current_month = datetime.now().strftime('%Y-%m')
        
        # Get sample categorization examples
        sample_categorization = {
            'Groceries': ['WHOLE FOODS', 'KROGER', 'SAFEWAY', 'TRADER JOES'],
            'Food & Drinks': ['STARBUCKS', 'MCDONALDS', 'CHIPOTLE', 'DOORDASH'],
            'Shopping': ['AMAZON', 'TARGET', 'WALMART', 'BEST BUY'],
            'Services': ['NETFLIX', 'SPOTIFY', 'VERIZON', 'INSURANCE'],
            'Entertainment': ['MOVIE THEATER', 'CONCERT', 'UBER', 'HOTEL'],
            'Other': ['UNKNOWN MERCHANT', 'MISC PURCHASE']
        }
        
        debug_info = {
            'current_month': current_month,
            'all_category_data': tracker.category_spending,
            'current_month_data': tracker.category_spending.get(current_month, {}),
            'total_cards': len(tracker.cards),
            'card_balances': {name: card['current_balance'] for name, card in tracker.cards.items()},
            'categorization_examples': sample_categorization,
            'timestamp': datetime.now().isoformat()
        }
        
        return jsonify({
            'success': True,
            'data': debug_info
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})
    
@app.route('/api/reprocess-categories', methods=['POST'])
def reprocess_categories():
    """Reprocess last uploaded file with different month filtering."""
    try:
        data = request.get_json() or {}
        use_all_months = data.get('use_all_months', False)
        
        # This would require storing the last processed file
        # For now, return instruction for user
        return jsonify({
            'success': False,
            'message': 'To reprocess with different settings, please re-upload your CSV file with the desired filtering option.',
            'instruction': 'Uncheck "Current month only for budgets" in the transactions tab and re-upload your file.'
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def get_due_dates_data():
    """Get formatted due dates data."""
    today = datetime.now()
    due_dates = []
    
    for name, card in tracker.cards.items():
        due_day = card['due_date']
        current_month = today.month
        current_year = today.year
        
        # Calculate next due date
        if due_day >= today.day:
            due_date = datetime(current_year, current_month, due_day)
        else:
            if current_month == 12:
                due_date = datetime(current_year + 1, 1, due_day)
            else:
                due_date = datetime(current_year, current_month + 1, due_day)
        
        days_until = (due_date - today).days
        balance = card['balance_due']
        
        # Determine urgency
        if days_until <= 3:
            urgency = 'budget-critical'
            status = f'{days_until} days - URGENT'
        elif days_until <= 7:
            urgency = 'budget-warning'
            status = f'{days_until} days - SOON'
        else:
            urgency = 'budget-good'
            status = f'{days_until} days'
        
        due_dates.append({
            'card_name': name,
            'due_date': due_date.strftime('%Y-%m-%d'),
            'balance': balance,
            'status': status,
            'urgency': urgency
        })
    
    # Sort by days until due
    due_dates.sort(key=lambda x: datetime.fromisoformat(x['due_date']))
    return due_dates

def get_category_budgets_data():
    """Get formatted category budgets data."""
    budgets = tracker.get_current_category_budgets()
    category_spending = tracker._get_category_spending()
    
    budget_data = []
    categories = ['Shopping', 'Food & Drinks', 'Services', 'Entertainment', 'Groceries', 'Other']
    
    for category in categories:
        budget = budgets.get(category, 0)
        spent = category_spending.get(category, 0)
        
        if budget > 0:
            remaining = budget - spent
            percentage = (spent / budget) * 100
            
            # Determine status
            if remaining < 0:
                status = 'budget-critical'
            elif remaining < budget * 0.1:
                status = 'budget-warning'
            else:
                status = 'budget-good'
            
            budget_data.append({
                'category': category,
                'spent': spent,
                'budget': budget,
                'remaining': remaining,
                'percentage': min(percentage, 100),
                'status': status
            })
    
    return budget_data

# =============================================================================
# ERROR HANDLERS
# =============================================================================

@app.errorhandler(413)
def too_large(e):
    return jsonify({'success': False, 'error': 'File too large. Maximum size is 16MB.'}), 413

@app.errorhandler(404)
def not_found(e):
    return jsonify({
        'success': False, 
        'error': 'Endpoint not found',
        'available_endpoints': [
            '/api/health',
            '/api/debug',
            '/api/routes',
            '/api/summary',
            '/api/cards',
            '/api/mobile-summary',
            '/api/spending-limits',
            '/api/category-budgets',
            '/api/upload-transactions',
            '/api/historical-analyses',
            '/api/compare-analyses',
            '/api/reset-statement',
            '/api/reset-balances',
            '/api/reset-category-spending',
            '/api/category-spending',
            '/api/debug-categories',
            '/api/reprocess-categories'
        ]
    }), 404

@app.errorhandler(500)
def internal_error(e):
    return jsonify({'success': False, 'error': 'Internal server error'}), 500

# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================

def is_port_available(port):
    """Check if a port is available."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(('127.0.0.1', port))
            return True
    except OSError:
        return False

# =============================================================================
# MAIN SERVER STARTUP
# =============================================================================

if __name__ == '__main__':
    print("🚀 Starting Credit Card Tracker API Server...")
    print(f"📁 Current directory: {os.getcwd()}")
    print(f"📁 Project root: {project_root}")
    print(f"📁 Data directory: {data_dir}")
    print(f"📁 Upload folder: {UPLOAD_FOLDER}")
    print(f"📁 Template folder: {app.template_folder}")
    print(f"📁 Template folder (absolute): {os.path.abspath(app.template_folder)}")
    
    # Check for required files
    template_path = os.path.join(app.template_folder, 'index.html')
    if os.path.exists(template_path):
        print("✅ Found index.html template")
    else:
        print(f"⚠️  Template not found: {template_path}")
        print(f"💡 Make sure index.html exists in: {os.path.abspath(app.template_folder)}")
    
    # Check for core module functionality
    try:
        print(f"📊 Loaded {len(tracker.cards)} credit cards")
        print(f"🔐 Encryption initialized: {hasattr(tracker, 'cipher_suite')}")
    except Exception as e:
        print(f"⚠️  Issue with tracker initialization: {e}")
    
    # Try ports 5001, 5002, 5003 (avoid 5000 which is used by macOS AirPlay)
    port = 5001
    while port <= 5010 and not is_port_available(port):
        print(f"⚠️  Port {port} is in use, trying {port + 1}...")
        port += 1
    
    if port > 5010:
        print("❌ Could not find available port between 5001-5010")
        sys.exit(1)
    
    print(f"🌐 Web interface: http://localhost:{port}")
    print(f"📱 Mobile API: http://localhost:{port}/api/mobile-summary")
    print(f"🔍 Debug info: http://localhost:{port}/api/debug")
    print("💾 Data stored securely using existing encryption")
    print("🔒 Server accessible only from localhost for security")
    print("\n🍎 Note: Port 5000 avoided (used by macOS AirPlay)")
    print(f"✅ Using port {port} instead")
    print("\n📋 Available API endpoints:")
    print("   • GET  /api/health - Health check")
    print("   • GET  /api/summary - Dashboard summary")
    print("   • GET  /api/cards - List credit cards")
    print("   • POST /api/cards - Add new card")
    print("   • PUT  /api/cards/<name> - Update card")
    print("   • DELETE /api/cards/<name> - Remove card")
    print("   • POST /api/spending-limits - Set spending limits")
    print("   • POST /api/category-budgets - Set category budgets")
    print("   • POST /api/upload-transactions - Upload CSV files")
    print("   • GET  /api/historical-analyses - List stored analyses")
    print("   • POST /api/compare-analyses - Compare analyses")
    print("   • POST /api/reset-statement - Reset statement period")
    print("   • POST /api/reset-balances - Reset balances")
    print("   • POST /api/reset-category-spending - Reset category spending")
    print("   • GET /api/category-spending - List category spending")
    print("\nPress Ctrl+C to stop the server")
    
    try:
        # Run development server
        app.run(
            debug=False,  # Enable debug mode for development
            host='127.0.0.1',  # Bind to localhost only for security
            port=port,
            threaded=True,
            use_reloader=False  # Disable reloader to prevent double startup messages
        )
    except KeyboardInterrupt:
        print("\n🛑 Server stopped by user")
    except Exception as e:
        print(f"❌ Server failed to start: {e}")
        sys.exit(1)