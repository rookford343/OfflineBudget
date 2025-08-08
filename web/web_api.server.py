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

# Import your existing tracker
from core.credit_card_tracker import CreditCardTracker, TimePeriodAnalyzer

app = Flask(__name__)
CORS(app)  # Enable CORS for frontend

# Configure upload settings
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size
UPLOAD_FOLDER = tempfile.mkdtemp()
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# Global tracker instance
tracker = CreditCardTracker()

@app.route('/')
def index():
    """Serve the web frontend."""
    # In production, you'd serve the HTML file directly
    # For development, we can embed it here or serve from a templates folder
    return "Credit Card Tracker API Server is running. Use the web frontend to interact with it."

@app.route('/api/summary')
def get_summary():
    """Get spending summary for dashboard."""
    try:
        # Calculate summary data
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
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/cards')
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
        return jsonify({'success': False, 'error': str(e)})

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

@app.route('/api/limits', methods=['POST'])
def set_limits():
    """Set spending limits."""
    try:
        data = request.get_json()
        tracker.set_spending_limits(data['soft_limit'], data['hard_limit'])
        return jsonify({'success': True, 'message': 'Limits updated successfully'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/budgets', methods=['POST'])
def set_budgets():
    """Set category budgets."""
    try:
        data = request.get_json()
        
        # Filter out zero values
        budgets = {k: v for k, v in data.items() if v > 0}
        
        if budgets:
            tracker.set_category_budgets(**budgets)
            return jsonify({'success': True, 'message': 'Budgets updated successfully'})
        else:
            return jsonify({'success': False, 'error': 'No valid budget amounts provided'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/analyze', methods=['POST'])
def analyze_period():
    """Run time period analysis."""
    try:
        # Handle file upload
        uploaded_files = request.files.getlist('files[]')
        if not uploaded_files:
            return jsonify({'success': False, 'error': 'No files uploaded'})
        
        # Save uploaded files temporarily
        csv_files = []
        for file in uploaded_files:
            if file.filename and file.filename.endswith('.csv'):
                filename = secure_filename(file.filename)
                filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                file.save(filepath)
                csv_files.append(filepath)
        
        if not csv_files:
            return jsonify({'success': False, 'error': 'No valid CSV files found'})
        
        # Get form data
        form_data = request.form.to_dict()
        start_date = form_data.get('start_date') or None
        end_date = form_data.get('end_date') or None
        group_by = form_data.get('group_by', 'month')
        trend_category = form_data.get('trend_category') or None
        show_comparisons = form_data.get('show_comparisons') == 'true'
        analysis_name = form_data.get('analysis_name') or None
        
        # Run analysis
        analyzer, period_analysis = tracker.show_period_summary(
            csv_files=csv_files,
            start_date=start_date,
            end_date=end_date,
            group_by=group_by,
            show_categories=True,
            compare=show_comparisons,
            trend_category=trend_category,
            store_as=analysis_name
        )
        
        if not period_analysis:
            return jsonify({'success': False, 'error': 'No analysis data generated'})
        
        # Format response data
        response_data = format_analysis_response(period_analysis, show_comparisons, trend_category)
        
        # Clean up uploaded files
        for filepath in csv_files:
            try:
                os.remove(filepath)
            except:
                pass
        
        return jsonify({'success': True, 'data': response_data})
    
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/analyses')
def get_stored_analyses():
    """Get list of stored analyses."""
    try:
        analyzer = TimePeriodAnalyzer(tracker)
        
        analyses_data = []
        for name, data in analyzer.historical_data.items():
            analysis = data.get('analysis', {})
            metadata = data.get('metadata', {})
            created_date = data.get('created_date', 'Unknown')
            
            # Parse created date
            try:
                created_dt = datetime.fromisoformat(created_date.replace('Z', '+00:00'))
                created_str = created_dt.strftime('%Y-%m-%d %H:%M')
            except:
                created_str = created_date
            
            analyses_data.append({
                'name': name,
                'periods': len(analysis),
                'created_date': created_str,
                'description': metadata.get('description', f"{metadata.get('start_date', 'All')} to {metadata.get('end_date', 'All')}")
            })
        
        return jsonify({'success': True, 'data': analyses_data})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/analyses/<analysis_name>')
def load_stored_analysis(analysis_name):
    """Load a stored analysis."""
    try:
        analyzer = TimePeriodAnalyzer(tracker)
        stored_analysis = analyzer.load_stored_analysis(analysis_name)
        
        if stored_analysis:
            response_data = format_analysis_response(stored_analysis, True, None)
            return jsonify({'success': True, 'data': response_data})
        else:
            return jsonify({'success': False, 'error': 'Analysis not found'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/analyses/<analysis_name>', methods=['DELETE'])
def delete_stored_analysis(analysis_name):
    """Delete a stored analysis."""
    try:
        analyzer = TimePeriodAnalyzer(tracker)
        if analysis_name in analyzer.historical_data:
            del analyzer.historical_data[analysis_name]
            analyzer.save_historical_data()
            return jsonify({'success': True, 'message': 'Analysis deleted successfully'})
        else:
            return jsonify({'success': False, 'error': 'Analysis not found'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/export')
def export_data():
    """Export all tracker data."""
    try:
        export_data = {
            'cards': tracker.cards,
            'spending_limits': tracker.spending_limits,
            'category_budgets': tracker.category_budgets,
            'category_spending': tracker.category_spending,
            'export_date': datetime.now().isoformat()
        }
        
        # Create JSON string
        json_str = json.dumps(export_data, indent=2, default=str)
        
        # Create file-like object
        output = io.StringIO(json_str)
        
        return jsonify({'success': True, 'data': json_str})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/reset-statement', methods=['POST'])
def reset_statement():
    """Reset statement periods."""
    try:
        data = request.get_json()
        card_name = data.get('card_name') if data else None
        tracker.reset_statement_period(card_name)
        return jsonify({'success': True, 'message': 'Statement period reset successfully'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/process-auto', methods=['POST'])
def process_auto():
    """Auto-process transaction files."""
    try:
        uploaded_files = request.files.getlist('files[]')
        if not uploaded_files:
            return jsonify({'success': False, 'error': 'No files uploaded'})
        
        # Save uploaded files temporarily
        csv_files = []
        for file in uploaded_files:
            if file.filename and file.filename.endswith('.csv'):
                filename = secure_filename(file.filename)
                filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                file.save(filepath)
                csv_files.append(filepath)
        
        if not csv_files:
            return jsonify({'success': False, 'error': 'No valid CSV files found'})
        
        # Process files
        tracker.process_transactions_auto(csv_files)
        
        # Clean up uploaded files
        for filepath in csv_files:
            try:
                os.remove(filepath)
            except:
                pass
        
        return jsonify({'success': True, 'message': f'Processed {len(csv_files)} files successfully'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/mobile-summary')
def get_mobile_summary():
    """Get simplified summary for mobile app."""
    try:
        # Calculate key metrics for mobile
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
        return jsonify({'success': False, 'error': str(e)})

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

def format_analysis_response(period_analysis, show_comparisons=False, trend_category=None):
    """Format period analysis data for web response."""
    periods = sorted(period_analysis.keys())
    
    # Calculate summary
    total_spending = sum(data['total_spending'] for data in period_analysis.values())
    total_periods = len(periods)
    avg_per_period = total_spending / total_periods if total_periods > 0 else 0
    
    # Format periods data
    periods_data = []
    for i, period in enumerate(periods):
        data = period_analysis[period]
        
        period_data = {
            'period': period,
            'spending': data['total_spending'],
            'transactions': data['transaction_count'],
            'avg_transaction': data['average_transaction']
        }
        
        # Add change calculation if showing comparisons
        if show_comparisons and i > 0:
            prev_spending = period_analysis[periods[i-1]]['total_spending']
            change = data['total_spending'] - prev_spending
            change_pct = (change / prev_spending * 100) if prev_spending > 0 else 0
            
            period_data['change'] = change
            period_data['change_text'] = f"{change:+,.2f} ({change_pct:+.1f}%)"
        
        periods_data.append(period_data)
    
    # Trend analysis
    trend_data = None
    if trend_category is not None:
        if trend_category:
            values = [period_analysis[p]['categories'][trend_category] for p in periods]
            category_name = trend_category
        else:
            values = [period_analysis[p]['total_spending'] for p in periods]
            category_name = 'Total Spending'
        
        if len(values) >= 3:
            recent_avg = sum(values[-3:]) / 3
            older_avg = sum(values[:-3]) / len(values[:-3]) if len(values) > 3 else values[0]
            
            trend_change = recent_avg - older_avg
            trend_pct = (trend_change / older_avg * 100) if older_avg > 0 else 0
            
            if trend_pct > 10:
                indicator = "📈 INCREASING"
                direction = f"Up {trend_pct:.1f}%"
            elif trend_pct < -10:
                indicator = "📉 DECREASING"
                direction = f"Down {abs(trend_pct):.1f}%"
            else:
                indicator = "➡️ STABLE"
                direction = f"Stable ({trend_pct:+.1f}%)"
            
            trend_data = {
                'category': category_name,
                'indicator': indicator,
                'direction': direction,
                'description': f"Recent trend compared to earlier periods"
            }
    
    return {
        'summary': {
            'total_periods': total_periods,
            'total_spending': total_spending,
            'avg_per_period': avg_per_period,
            'date_range': f"{periods[0]} to {periods[-1]}" if periods else "No data"
        },
        'periods': periods_data,
        'trend': trend_data,
        'show_change': show_comparisons
    }

# Error handlers
@app.errorhandler(413)
def too_large(e):
    return jsonify({'success': False, 'error': 'File too large. Maximum size is 16MB.'}), 413

@app.errorhandler(404)
def not_found(e):
    return jsonify({'success': False, 'error': 'Endpoint not found'}), 404

@app.errorhandler(500)
def internal_error(e):
    return jsonify({'success': False, 'error': 'Internal server error'}), 500

# Development server
if __name__ == '__main__':
    print("🚀 Starting Credit Card Tracker API Server...")
    print(f"📁 Upload folder: {UPLOAD_FOLDER}")
    print("🌐 Web interface: http://localhost:5000")
    print("📱 Mobile API: http://localhost:5000/api/mobile-summary")
    print("💾 Data stored securely using existing encryption")
    
    # Run development server
    app.run(
        debug=True,
        host='0.0.0.0',  # Allow access from other devices on network
        port=5000,
        threaded=True
    )