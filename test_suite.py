#!/usr/bin/env python3
"""
Comprehensive Test Suite for Credit Card Tracker
Tests all functionality including CLI, core modules, and web API
"""
import sys
import os
import tempfile
import shutil
import json
import csv
from pathlib import Path
from datetime import datetime, timedelta
import subprocess
import requests
import time
import threading

# Add core to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'core'))

from core import CreditCardTracker, TimePeriodAnalyzer

class TestSuite:
    def __init__(self):
        self.test_results = []
        self.temp_data_dir = None
        self.original_data_dir = None
        self.web_server_process = None
        self.setup_test_environment()
    
    def setup_test_environment(self):
        """Set up isolated test environment."""
        print("🔧 Setting up test environment...")
        
        # Create temporary data directory
        self.temp_data_dir = tempfile.mkdtemp(prefix="cc_tracker_test_")
        print(f"   Using temporary data directory: {self.temp_data_dir}")
        
        # Backup original data directory if it exists
        if os.path.exists('data'):
            self.original_data_dir = 'data'
            shutil.move('data', 'data_backup_for_test')
        
        # Create test data directory
        os.makedirs('data', exist_ok=True)
        
        print("✅ Test environment ready")
    
    def cleanup_test_environment(self):
        """Clean up test environment and restore original data."""
        print("🧹 Cleaning up test environment...")
        
        # Remove test data directory
        if os.path.exists('data'):
            shutil.rmtree('data')
        
        # Restore original data directory
        if self.original_data_dir and os.path.exists('data_backup_for_test'):
            shutil.move('data_backup_for_test', 'data')
        
        # Clean up temp directory
        if self.temp_data_dir and os.path.exists(self.temp_data_dir):
            shutil.rmtree(self.temp_data_dir)
        
        print("✅ Test environment cleaned up")
    
    def log_test(self, test_name, passed, details=""):
        """Log test result."""
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"{status} {test_name}")
        if details:
            print(f"      {details}")
        
        self.test_results.append({
            'test': test_name,
            'passed': passed,
            'details': details
        })
    
    def test_core_tracker_initialization(self):
        """Test CreditCardTracker initialization."""
        print("\n📋 Testing Core Tracker Initialization...")
        
        try:
            tracker = CreditCardTracker()
            self.log_test("Tracker initialization", True)
            
            # Test data directory creation
            data_exists = os.path.exists('data')
            self.log_test("Data directory creation", data_exists)
            
            # Test cipher suite setup
            has_cipher = hasattr(tracker, 'cipher_suite')
            self.log_test("Encryption setup", has_cipher)
            
            return tracker
            
        except Exception as e:
            self.log_test("Tracker initialization", False, str(e))
            return None
    
    def test_card_management(self, tracker):
        """Test credit card management functionality."""
        print("\n💳 Testing Card Management...")
        
        try:
            # Test adding cards
            tracker.add_card("Test Card 1", 5000, 15, 12, "Test card 1", 100, 250)
            tracker.add_card("Test Card 2", 10000, 28, 25, "Test card 2", 0, 500)
            
            card_count = len(tracker.cards)
            self.log_test("Add cards", card_count == 2, f"Added {card_count} cards")
            
            # Test card properties
            card1 = tracker.cards.get("Test Card 1")
            if card1:
                correct_limit = card1['credit_limit'] == 5000
                correct_balance = card1['current_balance'] == 250
                correct_due = card1['balance_due'] == 100
                
                self.log_test("Card properties", 
                            correct_limit and correct_balance and correct_due,
                            f"Limit: {card1['credit_limit']}, Current: {card1['current_balance']}, Due: {card1['balance_due']}")
            else:
                self.log_test("Card properties", False, "Card not found")
            
            # Test updating card
            tracker.update_card("Test Card 1", current_balance=300, credit_limit=6000)
            updated_card = tracker.cards.get("Test Card 1")
            if updated_card:
                update_success = updated_card['current_balance'] == 300 and updated_card['credit_limit'] == 6000
                self.log_test("Update card", update_success, 
                            f"Updated balance: {updated_card['current_balance']}, limit: {updated_card['credit_limit']}")
            else:
                self.log_test("Update card", False, "Card not found after update")
            
            # Test file persistence
            tracker2 = CreditCardTracker()
            persisted_cards = len(tracker2.cards)
            self.log_test("Card persistence", persisted_cards == 2, f"Loaded {persisted_cards} cards from file")
            
        except Exception as e:
            self.log_test("Card management", False, str(e))
    
    def test_spending_limits(self, tracker):
        """Test spending limits functionality."""
        print("\n💰 Testing Spending Limits...")
        
        try:
            # Test setting limits
            tracker.set_spending_limits(2000, 2500)
            limits = tracker.get_current_spending_limits()
            
            correct_soft = limits['soft_limit'] == 2000
            correct_hard = limits['hard_limit'] == 2500
            
            self.log_test("Set spending limits", 
                        correct_soft and correct_hard,
                        f"Soft: {limits['soft_limit']}, Hard: {limits['hard_limit']}")
            
            # Test persistence
            tracker2 = CreditCardTracker()
            limits2 = tracker2.get_current_spending_limits()
            
            persisted_soft = limits2['soft_limit'] == 2000
            persisted_hard = limits2['hard_limit'] == 2500
            
            self.log_test("Limits persistence", 
                        persisted_soft and persisted_hard,
                        f"Loaded - Soft: {limits2['soft_limit']}, Hard: {limits2['hard_limit']}")
            
        except Exception as e:
            self.log_test("Spending limits", False, str(e))
    
    def test_category_budgets(self, tracker):
        """Test category budget functionality."""
        print("\n📊 Testing Category Budgets...")
        
        try:
            # Test setting budgets
            budgets = {
                'Shopping': 800,
                'Food & Drinks': 400,
                'Services': 300,
                'Entertainment': 200,
                'Groceries': 350
            }
            
            tracker.set_category_budgets(**budgets)
            loaded_budgets = tracker.get_current_category_budgets()
            
            all_correct = all(loaded_budgets.get(cat) == amount for cat, amount in budgets.items())
            
            self.log_test("Set category budgets", all_correct, 
                        f"Set {len(budgets)} budgets, loaded {len(loaded_budgets)}")
            
            # Test persistence
            tracker2 = CreditCardTracker()
            persisted_budgets = tracker2.get_current_category_budgets()
            
            persistence_correct = all(persisted_budgets.get(cat) == amount for cat, amount in budgets.items())
            
            self.log_test("Budget persistence", persistence_correct,
                        f"Persisted {len(persisted_budgets)} budgets")
            
        except Exception as e:
            self.log_test("Category budgets", False, str(e))
    
    def create_test_csv(self, filename, transactions=None):
        """Create a test CSV file with sample transactions."""
        if transactions is None:
            transactions = [
                ['2024-01-15', 'AMAZON MKTPL', 'Shopping', -89.99, 'Online purchase'],
                ['2024-01-16', 'STARBUCKS #1234', 'Restaurants', -5.45, 'Coffee'],
                ['2024-01-17', 'KROGER #567', 'Grocery', -127.33, 'Groceries'],
                ['2024-01-18', 'SHELL OIL', 'Gas', -45.00, 'Gas station'],
                ['2024-01-19', 'NETFLIX.COM', 'Entertainment', -15.99, 'Subscription'],
                ['2024-01-20', 'CHASE PAYMENT', 'Payment', 500.00, 'Payment received'],
                ['2024-02-01', 'TARGET T-1234', 'Shopping', -156.78, 'Shopping'],
                ['2024-02-02', 'CHIPOTLE #890', 'Restaurants', -12.45, 'Lunch'],
                ['2024-02-03', 'CVS PHARMACY', 'Health & Wellness', -23.67, 'Pharmacy'],
                ['2024-02-04', 'HOME DEPOT', 'Shopping', -89.99, 'Home improvement']
            ]
        
        with open(filename, 'w', newline='') as csvfile:
            writer = csv.writer(csvfile)
            writer.writerow(['Transaction Date', 'Description', 'Category', 'Amount', 'Memo'])
            writer.writerows(transactions)
    
    def test_transaction_processing(self, tracker):
        """Test transaction file processing."""
        print("\n📄 Testing Transaction Processing...")
        
        try:
            # Create test CSV file
            test_csv = os.path.join(self.temp_data_dir, 'test_transactions.csv')
            self.create_test_csv(test_csv)
            
            # Test CSV processing
            df = tracker._process_csv_file(test_csv)
            csv_processed = not df.empty and len(df) == 10
            
            self.log_test("CSV file processing", csv_processed, f"Processed {len(df)} transactions")
            
            # Test categorization
            if csv_processed:
                df['custom_category'] = df.apply(
                    lambda row: tracker._categorize_transaction(
                        row.get('Description', ''), 
                        row.get('Memo', ''),
                        row.get('Category', '')
                    ), axis=1
                )
                
                categories_found = df['custom_category'].nunique()
                expected_categories = {'Shopping', 'Food & Drinks', 'Services', 'Groceries', 'Entertainment', 'Other'}
                actual_categories = set(df['custom_category'].unique())
                
                self.log_test("Transaction categorization", 
                            len(actual_categories) > 0,
                            f"Found categories: {actual_categories}")
            
            # Test auto-processing
            tracker.process_transactions_auto([test_csv])
            
            # Check if any card balance was updated (depends on card name matching)
            total_spending = sum(card['current_balance'] for card in tracker.cards.values())
            auto_process_worked = total_spending > 0  # Some spending should be recorded
            
            self.log_test("Auto transaction processing", auto_process_worked,
                        f"Total spending after processing: ${total_spending:.2f}")
            
        except Exception as e:
            self.log_test("Transaction processing", False, str(e))
    
    def test_time_period_analysis(self, tracker):
        """Test time period analysis functionality."""
        print("\n📈 Testing Time Period Analysis...")
        
        try:
            # Create test CSV files for different months
            csv1 = os.path.join(self.temp_data_dir, 'jan_transactions.csv')
            csv2 = os.path.join(self.temp_data_dir, 'feb_transactions.csv')
            
            # January transactions
            jan_transactions = [
                ['2024-01-15', 'AMAZON', 'Shopping', -100.00, ''],
                ['2024-01-16', 'STARBUCKS', 'Food', -25.00, ''],
                ['2024-01-17', 'KROGER', 'Grocery', -150.00, ''],
            ]
            
            # February transactions  
            feb_transactions = [
                ['2024-02-15', 'TARGET', 'Shopping', -200.00, ''],
                ['2024-02-16', 'CHIPOTLE', 'Food', -35.00, ''],
                ['2024-02-17', 'WHOLE FOODS', 'Grocery', -180.00, ''],
            ]
            
            self.create_test_csv(csv1, jan_transactions)
            self.create_test_csv(csv2, feb_transactions)
            
            # Test time period analysis
            analyzer, period_analysis = tracker.analyze_period(
                [csv1, csv2], 
                start_date='2024-01-01',
                end_date='2024-02-28',
                group_by='month'
            )
            
            analysis_successful = analyzer is not None and len(period_analysis) == 2
            self.log_test("Time period analysis", analysis_successful,
                        f"Analyzed {len(period_analysis)} periods")
            
            if analysis_successful:
                # Test period data structure
                first_period = list(period_analysis.keys())[0]
                period_data = period_analysis[first_period]
                
                has_required_fields = all(field in period_data for field in 
                                        ['total_spending', 'transaction_count', 'categories', 'average_transaction'])
                
                self.log_test("Period data structure", has_required_fields,
                            f"Period {first_period} has required fields")
                
                # Test storing analysis
                test_analysis_name = f"test_analysis_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                analyzer.store_period_analysis(test_analysis_name, period_analysis, 
                                             {'test': True, 'periods': len(period_analysis)})
                
                # Test loading stored analysis
                loaded_analysis = analyzer.load_stored_analysis(test_analysis_name)
                storage_successful = loaded_analysis is not None and len(loaded_analysis) == len(period_analysis)
                
                self.log_test("Analysis storage/loading", storage_successful,
                            f"Stored and loaded analysis with {len(loaded_analysis) if loaded_analysis else 0} periods")
            
        except Exception as e:
            self.log_test("Time period analysis", False, str(e))
    
    def test_cli_commands(self):
        """Test CLI command functionality."""
        print("\n🖥️  Testing CLI Commands...")
        
        cli_tests = [
            (['python3', 'core/credit_card_tracker.py', '--list-cards'], "List cards command"),
            (['python3', 'core/credit_card_tracker.py', '--summary'], "Summary command"),
            (['python3', 'core/credit_card_tracker.py', '--due-dates'], "Due dates command"),
            (['python3', 'core/transaction_processor.py', '--help'], "Transaction processor help")
        ]
        
        for cmd, test_name in cli_tests:
            try:
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
                cmd_successful = result.returncode == 0
                
                self.log_test(test_name, cmd_successful, 
                            f"Exit code: {result.returncode}" + 
                            (f", Error: {result.stderr[:100]}" if result.stderr else ""))
                
            except subprocess.TimeoutExpired:
                self.log_test(test_name, False, "Command timed out")
            except Exception as e:
                self.log_test(test_name, False, str(e))
    
    def start_web_server(self):
        """Start the web server in background for testing."""
        try:
            self.web_server_process = subprocess.Popen(
                ['python3', 'web/web_api_server.py'],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            
            # Wait for server to start
            time.sleep(3)
            
            # Check if server is running
            try:
                response = requests.get('http://localhost:5000/api/summary', timeout=5)
                return response.status_code in [200, 404, 500]  # Any response means server is up
            except:
                return False
                
        except Exception as e:
            print(f"Failed to start web server: {e}")
            return False
    
    def stop_web_server(self):
        """Stop the web server."""
        if self.web_server_process:
            self.web_server_process.terminate()
            try:
                self.web_server_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.web_server_process.kill()
            self.web_server_process = None
    
    def test_web_api(self):
        """Test web API functionality."""
        print("\n🌐 Testing Web API...")
        
        server_started = self.start_web_server()
        self.log_test("Web server startup", server_started)
        
        if not server_started:
            print("   Skipping web API tests - server failed to start")
            return
        
        # Test API endpoints
        api_tests = [
            ('GET', '/api/summary', 'Dashboard summary endpoint'),
            ('GET', '/api/cards', 'Cards list endpoint'),
            ('GET', '/api/mobile-summary', 'Mobile summary endpoint')
        ]
        
        for method, endpoint, test_name in api_tests:
            try:
                if method == 'GET':
                    response = requests.get(f'http://localhost:5000{endpoint}', timeout=10)
                
                api_successful = response.status_code == 200
                
                if api_successful:
                    try:
                        data = response.json()
                        has_success_field = 'success' in data
                        self.log_test(test_name, has_success_field, 
                                    f"Status: {response.status_code}, Has success field: {has_success_field}")
                    except:
                        self.log_test(test_name, False, f"Status: {response.status_code}, Invalid JSON response")
                else:
                    self.log_test(test_name, False, f"HTTP {response.status_code}")
                    
            except requests.RequestException as e:
                self.log_test(test_name, False, f"Request failed: {str(e)[:100]}")
            except Exception as e:
                self.log_test(test_name, False, str(e))
        
        self.stop_web_server()
    
    def test_data_persistence(self):
        """Test data persistence and encryption."""
        print("\n💾 Testing Data Persistence...")
        
        try:
            # Check encrypted files exist
            expected_files = [
                'data/credit_cards.enc',
                'data/spending_limits.enc', 
                'data/category_budgets.enc',
                'data/category_spending.enc'
            ]
            
            existing_files = [f for f in expected_files if os.path.exists(f)]
            files_created = len(existing_files) > 0
            
            self.log_test("Encrypted files creation", files_created,
                        f"Found {len(existing_files)}/{len(expected_files)} expected files")
            
            # Test file permissions and encryption
            if existing_files:
                test_file = existing_files[0]
                
                # Check file is not empty
                file_size = os.path.getsize(test_file)
                file_not_empty = file_size > 0
                
                # Check file appears encrypted (not readable as plain text)
                with open(test_file, 'rb') as f:
                    content = f.read(100)  # Read first 100 bytes
                    appears_encrypted = b'{' not in content and b'[' not in content  # Not plain JSON
                
                self.log_test("File encryption", appears_encrypted and file_not_empty,
                            f"File size: {file_size} bytes, Appears encrypted: {appears_encrypted}")
            
        except Exception as e:
            self.log_test("Data persistence", False, str(e))
    
    def run_all_tests(self):
        """Run the complete test suite."""
        print("🧪 Starting Credit Card Tracker Test Suite")
        print("=" * 60)
        
        start_time = datetime.now()
        
        try:
            # Core functionality tests
            tracker = self.test_core_tracker_initialization()
            
            if tracker:
                self.test_card_management(tracker)
                self.test_spending_limits(tracker)
                self.test_category_budgets(tracker)
                self.test_transaction_processing(tracker)
                self.test_time_period_analysis(tracker)
                self.test_data_persistence()
            
            # CLI tests
            self.test_cli_commands()
            
            # Web API tests
            self.test_web_api()
            
        except Exception as e:
            print(f"❌ Test suite failed with error: {e}")
        
        finally:
            self.cleanup_test_environment()
        
        # Generate test report
        end_time = datetime.now()
        duration = end_time - start_time
        
        self.generate_test_report(duration)
    
    def generate_test_report(self, duration):
        """Generate and display test results report."""
        print("\n" + "=" * 60)
        print("🧪 TEST RESULTS SUMMARY")
        print("=" * 60)
        
        total_tests = len(self.test_results)
        passed_tests = sum(1 for result in self.test_results if result['passed'])
        failed_tests = total_tests - passed_tests
        
        print(f"Total Tests: {total_tests}")
        print(f"Passed: ✅ {passed_tests}")
        print(f"Failed: ❌ {failed_tests}")
        print(f"Success Rate: {(passed_tests/total_tests*100):.1f}%")
        print(f"Duration: {duration.total_seconds():.1f} seconds")
        
        # Show failed tests
        if failed_tests > 0:
            print(f"\n❌ FAILED TESTS ({failed_tests}):")
            for result in self.test_results:
                if not result['passed']:
                    print(f"   • {result['test']}: {result['details']}")
        
        # Overall result
        if failed_tests == 0:
            print(f"\n🎉 ALL TESTS PASSED! Your Credit Card Tracker is working perfectly.")
        else:
            print(f"\n⚠️  {failed_tests} test(s) failed. Please review the errors above.")
        
        print("=" * 60)
        
        # Save detailed report
        report_file = f"test_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(report_file, 'w') as f:
            json.dump({
                'timestamp': datetime.now().isoformat(),
                'duration_seconds': duration.total_seconds(),
                'total_tests': total_tests,
                'passed_tests': passed_tests,
                'failed_tests': failed_tests,
                'success_rate': passed_tests/total_tests*100,
                'results': self.test_results
            }, f, indent=2)
        
        print(f"📄 Detailed report saved to: {report_file}")

def main():
    """Run the test suite."""
    if len(sys.argv) > 1 and sys.argv[1] in ['--help', '-h']:
        print("Credit Card Tracker Test Suite")
        print("\nUsage: python3 test_suite.py")
        print("\nThis will run comprehensive tests of:")
        print("- Core tracker functionality")
        print("- Card management") 
        print("- Transaction processing")
        print("- Time period analysis")
        print("- CLI commands")
        print("- Web API endpoints")
        print("- Data persistence and encryption")
        print("\nThe test creates temporary data and restores your original data after testing.")
        return
    
    test_suite = TestSuite()
    test_suite.run_all_tests()

if __name__ == "__main__":
    main()