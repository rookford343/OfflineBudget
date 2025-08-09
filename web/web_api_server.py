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
    """Get spending summary for dashboard."""
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
        
        # Get category budgets
        category_budgets = get_category_budgets_data()
        
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
                'category_budgets': category_budgets
            }
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/mobile-summary', methods=['GET'])
def get_mobile_summary():
    """Get simplified summary for mobile app."""
    try:
        total_spending = sum(card['current_balance'] for card in tracker.cards.values())
        balance_due = sum(card['balance_due'] for card in tracker.cards.values())
        
        # Get spending limits
        limits = tracker.get_current_spending_limits()
        
        # Calculate left to spend
        if limits['soft_limit'] > 0:
            left_to_spend = limits['soft_limit'] - total_spending
            budget_status = 'over' if total_spending > limits['soft_limit'] else 'good'
            budget_percentage = (total_spending / limits['soft_limit']) * 100 if limits['soft_limit'] > 0 else 0
        else:
            left_to_spend = 0
            budget_status = 'no_budget'
            budget_percentage = 0
        
        # Get top category spending
        category_spending = tracker._get_category_spending()
        top_categories = sorted(category_spending.items(), key=lambda x: x[1], reverse=True)[:3]
        
        # Get next due date
        today = datetime.now()
        next_due = None
        for name, card in tracker.cards.items():
            due_day = card['due_date']
            current_month = today.month
            current_year = today.year
            
            if due_day >= today.day:
                due_date = datetime(current_year, current_month, due_day)
            else:
                if current_month == 12:
                    due_date = datetime(current_year + 1, 1, due_day)
                else:
                    due_date = datetime(current_year, current_month + 1, due_day)
            
            days_until = (due_date - today).days
            balance = card['balance_due']
            
            if balance > 0 and (next_due is None or days_until < next_due['days']):
                next_due = {
                    'card_name': name,
                    'days': days_until,
                    'balance': balance,
                    'date': due_date.strftime('%Y-%m-%d')
                }
        
        return jsonify({
            'success': True,
            'data': {
                'total_spending': total_spending,
                'balance_due': balance_due,
                'left_to_spend': left_to_spend,
                'budget_status': budget_status,
                'budget_percentage': budget_percentage,
                'top_categories': [{'name': name, 'amount': amount} for name, amount in top_categories],
                'next_due': next_due,
                'cards_count': len(tracker.cards),
                'last_updated': datetime.now().isoformat()
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
    """Upload and process transaction CSV files."""
    try:
        if 'files' not in request.files:
            return jsonify({'success': False, 'error': 'No files provided'})
        
        files = request.files.getlist('files')
        auto_update = request.form.get('auto_update', 'true').lower() == 'true'
        update_categories = request.form.get('update_categories', 'true').lower() == 'true'
        
        if not files:
            return jsonify({'success': False, 'error': 'No files selected'})
        
        # Save uploaded files temporarily
        temp_files = []
        for file in files:
            if file.filename and file.filename.endswith('.csv'):
                filename = secure_filename(file.filename)
                filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                file.save(filepath)
                temp_files.append(filepath)
        
        if not temp_files:
            return jsonify({'success': False, 'error': 'No valid CSV files found'})
        
        # Process the files
        if auto_update:
            tracker.process_transactions_auto(temp_files)
            message = f'Processed {len(temp_files)} files and updated card balances'
        else:
            # Just update categories without updating balances
            all_dfs = []
            for file_path in temp_files:
                df = tracker._process_csv_file(file_path)
                if not df.empty:
                    all_dfs.append(df)
            
            if all_dfs and update_categories:
                combined_df = pd.concat(all_dfs, ignore_index=True) if len(all_dfs) > 1 else all_dfs[0]
                tracker._update_category_spending(combined_df)
                message = f'Processed {len(temp_files)} files and updated category spending'
            else:
                message = f'Analyzed {len(temp_files)} files'
        
        # Clean up temp files
        for filepath in temp_files:
            try:
                os.remove(filepath)
            except:
                pass
        
        return jsonify({'success': True, 'message': message, 'files_processed': len(temp_files)})
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

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
            '/api/reset-balances'
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