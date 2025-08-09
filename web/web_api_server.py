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

# Add parent directory to Python path
parent_dir = Path(__file__).parent.parent
sys.path.insert(0, str(parent_dir))

# Import from core module
from core import CreditCardTracker, TimePeriodAnalyzer

from flask import Flask, request, jsonify, render_template, send_file
from flask_cors import CORS
import json
import tempfile
import io
from datetime import datetime, timedelta
import pandas as pd
from werkzeug.utils import secure_filename

app = Flask(__name__)
CORS(app, origins=['http://localhost:*', 'http://127.0.0.1:*'])

# Configure upload settings
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size
UPLOAD_FOLDER = tempfile.mkdtemp()
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# Ensure data directory exists
os.makedirs('data', exist_ok=True)

# Global tracker instance
tracker = CreditCardTracker()

@app.route('/')
def index():
    """Serve the main web interface."""
    try:
        return render_template('index.html')
    except:
        return """
        <html>
        <head><title>Credit Card Tracker API</title></head>
        <body>
            <h1>💳 Credit Card Tracker API</h1>
            <p>✅ Server is running successfully!</p>
            <h3>Available Endpoints:</h3>
            <ul>
                <li><a href="/api/health">/api/health</a> - Health check</li>
                <li><a href="/api/debug">/api/debug</a> - Debug info</li>
                <li><a href="/api/routes">/api/routes</a> - List routes</li>
                <li><a href="/api/summary">/api/summary</a> - Dashboard summary</li>
                <li><a href="/api/cards">/api/cards</a> - Credit cards list</li>
                <li><a href="/api/mobile-summary">/api/mobile-summary</a> - Mobile summary</li>
            </ul>
        </body>
        </html>
        """

@app.route('/api/health')
def health_check():
    """Simple health check endpoint."""
    return jsonify({
        'success': True,
        'message': 'Credit Card Tracker API is running',
        'timestamp': datetime.now().isoformat(),
        'version': '1.0.0',
        'cards_count': len(tracker.cards)
    })

@app.route('/api/debug')
def debug_info():
    """Debug endpoint for troubleshooting."""
    try:
        return jsonify({
            'success': True,
            'data': {
                'cards_count': len(tracker.cards),
                'card_names': list(tracker.cards.keys()),
                'data_files_exist': {
                    'credit_cards.enc': os.path.exists('data/credit_cards.enc'),
                    'spending_limits.enc': os.path.exists('data/spending_limits.enc'),
                    'category_budgets.enc': os.path.exists('data/category_budgets.enc'),
                    'category_spending.enc': os.path.exists('data/category_spending.enc')
                },
                'tracker_initialized': hasattr(tracker, 'cipher_suite'),
                'current_directory': os.getcwd()
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

@app.route('/api/cards/<card_name>', methods=['DELETE'])
def remove_card(card_name):
    """Remove a credit card."""
    try:
        tracker.remove_card(card_name)
        return jsonify({'success': True, 'message': 'Card removed successfully'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

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

# Helper functions
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

# Error handlers
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
            '/api/mobile-summary'
        ]
    }), 404

@app.errorhandler(500)
def internal_error(e):
    return jsonify({'success': False, 'error': 'Internal server error'}), 500

# Check if port is available
def is_port_available(port):
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(('127.0.0.1', port))
            return True
    except OSError:
        return False

# Development server
if __name__ == '__main__':
    print("🚀 Starting Credit Card Tracker API Server...")
    print(f"📁 Upload folder: {UPLOAD_FOLDER}")
    
    # Create upload folder if it doesn't exist
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    
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
    print("💾 Data stored securely using existing encryption")
    print("🔒 Server accessible only from localhost for security")
    print("\n🍎 Note: Port 5000 avoided (used by macOS AirPlay)")
    print(f"✅ Using port {port} instead")
    print("\nPress Ctrl+C to stop the server")
    
    try:
        # Run development server
        app.run(
            debug=False,  # Disable debug mode for cleaner output
            host='127.0.0.1',  # Bind to localhost only for security
            port=port,
            threaded=True,
            use_reloader=False  # Disable reloader to prevent issues with testing
        )
    except KeyboardInterrupt:
        print("\n🛑 Server stopped by user")
    except Exception as e:
        print(f"❌ Server failed to start: {e}")
        sys.exit(1)