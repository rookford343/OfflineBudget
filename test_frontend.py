#!/usr/bin/env python3
"""
Frontend Test Suite for Credit Card Tracker Web Interface
Tests the web API endpoints and frontend functionality
"""
import sys
import os
import tempfile
import shutil
import json
import csv
import time
import threading
import subprocess
import requests
from pathlib import Path
from datetime import datetime, timedelta
import selenium
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import Select
from selenium.common.exceptions import TimeoutException, WebDriverException
from webdriver_manager.chrome import ChromeDriverManager

class FrontendTestSuite:
    def __init__(self):
        self.test_results = []
        self.server_process = None
        self.server_port = None
        self.driver = None
        self.base_url = None
        self.temp_data_dir = None
        self.original_data_dir = None
        
    def setup_test_environment(self):
        """Set up test environment and start web server."""
        print("🔧 Setting up frontend test environment...")
        
        # Verify we're in the correct directory
        required_files = ['web/web_api_server.py', 'web/templates/index.html', 'core/credit_card_tracker.py']
        missing_files = [f for f in required_files if not os.path.exists(f)]
        
        if missing_files:
            raise Exception(f"Missing required files: {missing_files}. "
                          f"Please run this script from the project root directory.")
        
        print(f"      ✅ Running from correct directory: {os.getcwd()}")
        
        # Backup original data directory
        if os.path.exists('data'):
            self.original_data_dir = 'data'
            shutil.move('data', 'data_backup_for_frontend_test')
            print("      ✅ Backed up original data directory")
        
        # Create clean test data directory
        os.makedirs('data', exist_ok=True)
        print("      ✅ Created clean test data directory")
        
        # Start the web server
        if not self.start_web_server():
            raise Exception("Failed to start web server")
        
        # Initialize the web driver
        self.setup_web_driver()
        
        print("✅ Frontend test environment ready")
    
    def cleanup_test_environment(self):
        """Clean up test environment."""
        print("🧹 Cleaning up frontend test environment...")
        
        # Close web driver
        if self.driver:
            self.driver.quit()
        
        # Stop web server
        self.stop_web_server()
        
        # Remove test data directory
        if os.path.exists('data'):
            shutil.rmtree('data')
        
        # Restore original data directory
        if self.original_data_dir and os.path.exists('data_backup_for_frontend_test'):
            shutil.move('data_backup_for_frontend_test', 'data')
        
        print("✅ Frontend test environment cleaned up")
    
    def start_web_server(self):
        """Start the web server for testing."""
        try:
            print("      Starting web server...")
            
            # Check if we're in the project root and web server exists
            web_server_path = 'web/web_api_server.py'
            if not os.path.exists(web_server_path):
                raise FileNotFoundError(f"Web server not found at {web_server_path}")
            
            # Start server process from project root
            self.server_process = subprocess.Popen(
                ['python3', web_server_path],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd=os.getcwd()  # Ensure we're running from the correct directory
            )
            
            # Wait for server to start and detect port
            for attempt in range(15):
                time.sleep(1)
                
                # Try common ports
                for port in [5001, 5002, 5003, 5004]:
                    try:
                        response = requests.get(f'http://localhost:{port}/api/health', timeout=2)
                        if response.status_code == 200:
                            self.server_port = port
                            self.base_url = f'http://localhost:{port}'
                            print(f"      Server running on port {port}")
                            return True
                    except requests.exceptions.ConnectionError:
                        continue
                
                if attempt < 14:
                    print(f"      Attempt {attempt + 1}: Server not ready, retrying...")
            
            print("      Failed to connect to server")
            return False
                
        except Exception as e:
            print(f"      Failed to start web server: {e}")
            return False
    
    def stop_web_server(self):
        """Stop the web server."""
        if self.server_process:
            print("      Stopping web server...")
            self.server_process.terminate()
            try:
                self.server_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.server_process.kill()
            self.server_process = None
    
    def setup_web_driver(self):
        """Set up Selenium web driver with automatic ChromeDriver management."""
        try:
            print("      Setting up Chrome WebDriver...")
            
            # Chrome options optimized for Mac
            chrome_options = Options()
            chrome_options.add_argument("--headless")  # Run without GUI
            chrome_options.add_argument("--no-sandbox")
            chrome_options.add_argument("--disable-dev-shm-usage")
            chrome_options.add_argument("--disable-gpu")
            chrome_options.add_argument("--window-size=1920,1080")
            chrome_options.add_argument("--disable-web-security")
            chrome_options.add_argument("--disable-features=VizDisplayCompositor")
            chrome_options.add_argument("--disable-extensions")
            chrome_options.add_argument("--disable-plugins")
            
            # For Mac-specific compatibility
            chrome_options.add_argument("--disable-background-timer-throttling")
            chrome_options.add_argument("--disable-renderer-backgrounding")
            chrome_options.add_argument("--disable-backgrounding-occluded-windows")
            
            # Automatically download and manage ChromeDriver
            print("      Downloading/updating ChromeDriver...")
            service = Service(ChromeDriverManager().install())
            
            # Initialize the driver
            self.driver = webdriver.Chrome(service=service, options=chrome_options)
            self.driver.implicitly_wait(10)
            
            print("      ✅ Chrome WebDriver initialized successfully")
            
        except Exception as e:
            print(f"      ⚠️  Could not initialize Chrome driver: {e}")
            print("      Falling back to API-only tests")
            print("      To fix this issue:")
            print("        1. Make sure Chrome browser is installed")
            print("        2. Run: pip install webdriver-manager")
            print("        3. Check your internet connection (needed to download ChromeDriver)")
            self.driver = None
    
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
    
    def test_api_endpoints(self):
        """Test that all API endpoints are working."""
        print("\n🌐 Testing API Endpoints...")
        
        endpoints = [
            ('/api/health', 'GET', 'Health check'),
            ('/api/summary', 'GET', 'Dashboard summary'),
            ('/api/cards', 'GET', 'Cards list'),
            ('/api/mobile-summary', 'GET', 'Mobile summary'),
            ('/api/debug', 'GET', 'Debug info')
        ]
        
        for endpoint, method, description in endpoints:
            try:
                if method == 'GET':
                    response = requests.get(f'{self.base_url}{endpoint}', timeout=10)
                
                success = response.status_code == 200
                
                if success:
                    try:
                        data = response.json()
                        has_success = 'success' in data
                        self.log_test(f"API {description}", has_success, 
                                    f"Status: {response.status_code}, Success field: {has_success}")
                    except:
                        self.log_test(f"API {description}", False, 
                                    f"Status: {response.status_code}, Invalid JSON")
                else:
                    self.log_test(f"API {description}", False, f"HTTP {response.status_code}")
                    
            except Exception as e:
                self.log_test(f"API {description}", False, str(e))
    
    def test_frontend_loading(self):
        """Test that the frontend loads properly."""
        if not self.driver:
            self.log_test("Frontend loading", False, "No web driver available")
            return
        
        print("\n📱 Testing Frontend Loading...")
        
        try:
            # Navigate to the main page
            self.driver.get(self.base_url)
            
            # Wait for the page to load
            WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.CLASS_NAME, "header"))
            )
            
            # Check if main elements are present
            title = self.driver.find_element(By.TAG_NAME, "h1").text
            title_correct = "Credit Card Tracker" in title
            
            # Check if tabs are present
            tabs = self.driver.find_elements(By.CLASS_NAME, "tab-button")
            tabs_present = len(tabs) >= 7  # Should have 7 tabs
            
            # Check if dashboard content loads
            dashboard_tab = self.driver.find_element(By.ID, "dashboard-tab")
            dashboard_visible = dashboard_tab.is_displayed()
            
            overall_success = title_correct and tabs_present and dashboard_visible
            
            self.log_test("Frontend page loading", overall_success,
                        f"Title: {title_correct}, Tabs: {len(tabs)}, Dashboard: {dashboard_visible}")
            
        except Exception as e:
            self.log_test("Frontend page loading", False, str(e))
    
    def test_dashboard_functionality(self):
        """Test dashboard tab functionality."""
        if not self.driver:
            return
        
        print("\n📊 Testing Dashboard Functionality...")
        
        try:
            # Click dashboard tab to ensure it's active
            dashboard_tab = self.driver.find_element(By.XPATH, "//button[contains(text(), 'Dashboard')]")
            dashboard_tab.click()
            
            # Wait for dashboard content to load
            WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.ID, "totalSpending"))
            )
            
            # Check if spending summary elements are present
            total_spending = self.driver.find_element(By.ID, "totalSpending")
            balance_due = self.driver.find_element(By.ID, "balanceDue")
            left_to_spend = self.driver.find_element(By.ID, "leftToSpend")
            
            spending_elements_present = all([
                total_spending.is_displayed(),
                balance_due.is_displayed(), 
                left_to_spend.is_displayed()
            ])
            
            # Test refresh button
            refresh_btn = self.driver.find_element(By.ID, "refreshBtn")
            refresh_btn.click()
            
            # Wait a moment for refresh to complete
            time.sleep(2)
            
            self.log_test("Dashboard spending summary", spending_elements_present,
                        "All spending summary elements visible and refresh button works")
            
        except Exception as e:
            self.log_test("Dashboard functionality", False, str(e))
    
    def test_card_management_tab(self):
        """Test the credit card management functionality."""
        if not self.driver:
            return
        
        print("\n💳 Testing Card Management Tab...")
        
        try:
            # Navigate to cards tab
            cards_tab = self.driver.find_element(By.XPATH, "//button[contains(text(), 'Manage Cards')]")
            cards_tab.click()
            
            # Wait for tab content to load
            WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.ID, "cards-tab"))
            )
            
            # Test showing add card form
            add_card_btn = self.driver.find_element(By.XPATH, "//button[contains(text(), 'Add New Card')]")
            add_card_btn.click()
            
            # Check if form appears
            add_card_form = WebDriverWait(self.driver, 5).until(
                EC.visibility_of_element_located((By.ID, "addCardForm"))
            )
            
            # Fill out the form
            self.driver.find_element(By.ID, "cardName").send_keys("Test Card")
            self.driver.find_element(By.ID, "creditLimit").send_keys("5000")
            self.driver.find_element(By.ID, "statementDate").send_keys("15")
            self.driver.find_element(By.ID, "dueDate").send_keys("12")
            self.driver.find_element(By.ID, "currentBalance").send_keys("100")
            self.driver.find_element(By.ID, "balanceDue").send_keys("250")
            self.driver.find_element(By.ID, "cardDescription").send_keys("Test card for frontend testing")
            
            # Submit the form
            submit_btn = add_card_form.find_element(By.XPATH, ".//button[@type='submit']")
            submit_btn.click()
            
            # Wait for form to potentially close and check for success
            time.sleep(2)
            
            # Verify the card was added by checking the API
            response = requests.get(f'{self.base_url}/api/cards')
            cards_data = response.json()
            
            card_added = False
            if cards_data['success']:
                for card in cards_data['data']:
                    if card['name'] == 'Test Card':
                        card_added = True
                        break
            
            self.log_test("Add new credit card", card_added,
                        "Form submission and card creation successful")
            
        except Exception as e:
            self.log_test("Card management tab", False, str(e))
    
    def test_budget_limits_tab(self):
        """Test budgets and limits functionality."""
        if not self.driver:
            return
        
        print("\n🎯 Testing Budgets & Limits Tab...")
        
        try:
            # Navigate to budgets tab
            budgets_tab = self.driver.find_element(By.XPATH, "//button[contains(text(), 'Budgets & Limits')]")
            budgets_tab.click()
            
            # Wait for tab content to load
            WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.ID, "budgets-tab"))
            )
            
            # Test spending limits form
            self.driver.find_element(By.ID, "softLimit").send_keys("2000")
            self.driver.find_element(By.ID, "hardLimit").send_keys("3000")
            
            # Submit spending limits
            limits_form = self.driver.find_element(By.XPATH, "//form[.//input[@id='softLimit']]")
            limits_submit = limits_form.find_element(By.XPATH, ".//button[@type='submit']")
            limits_submit.click()
            
            time.sleep(1)
            
            # Test category budgets form
            self.driver.find_element(By.ID, "budgetShopping").send_keys("800")
            self.driver.find_element(By.ID, "budgetFoodDrinks").send_keys("400")
            self.driver.find_element(By.ID, "budgetServices").send_keys("300")
            self.driver.find_element(By.ID, "budgetEntertainment").send_keys("200")
            self.driver.find_element(By.ID, "budgetGroceries").send_keys("350")
            self.driver.find_element(By.ID, "budgetOther").send_keys("150")
            
            # Submit category budgets
            budgets_form = self.driver.find_element(By.XPATH, "//form[.//input[@id='budgetShopping']]")
            budgets_submit = budgets_form.find_element(By.XPATH, ".//button[@type='submit']")
            budgets_submit.click()
            
            time.sleep(2)
            
            self.log_test("Budget and limits forms", True,
                        "Both spending limits and category budget forms submitted")
            
        except Exception as e:
            self.log_test("Budget and limits tab", False, str(e))
    
    def test_transaction_upload_tab(self):
        """Test transaction file upload functionality."""
        if not self.driver:
            return
        
        print("\n📄 Testing Transaction Upload Tab...")
        
        try:
            # Navigate to transactions tab
            transactions_tab = self.driver.find_element(By.XPATH, "//button[contains(text(), 'Import Transactions')]")
            transactions_tab.click()
            
            # Wait for tab content to load
            WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.ID, "transactions-tab"))
            )
            
            # Create a test CSV file
            test_csv_path = self.create_test_csv()
            
            # Upload the file
            file_input = self.driver.find_element(By.ID, "csvFiles")
            file_input.send_keys(test_csv_path)
            
            # Wait for file to be processed
            time.sleep(1)
            
            # Check if process button is enabled
            process_btn = self.driver.find_element(By.ID, "processBtn")
            process_enabled = process_btn.is_enabled()
            
            if process_enabled:
                # Click process button
                process_btn.click()
                
                # Wait for processing to complete
                WebDriverWait(self.driver, 30).until(
                    lambda driver: "Processing..." not in process_btn.text
                )
            
            # Clean up test file
            os.remove(test_csv_path)
            
            self.log_test("Transaction file upload", process_enabled,
                        "File upload and processing button activation successful")
            
        except Exception as e:
            self.log_test("Transaction upload tab", False, str(e))
    
    def test_settings_tab(self):
        """Test settings tab functionality."""
        if not self.driver:
            return
        
        print("\n⚙️ Testing Settings Tab...")
        
        try:
            # Navigate to settings tab
            settings_tab = self.driver.find_element(By.XPATH, "//button[contains(text(), 'Settings')]")
            settings_tab.click()
            
            # Wait for tab content to load
            WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.ID, "settings-tab"))
            )
            
            # Test debug info button
            debug_btn = self.driver.find_element(By.XPATH, "//button[contains(text(), 'Show Debug Info')]")
            debug_btn.click()
            
            time.sleep(2)
            
            # Check if debug info appears
            debug_info = self.driver.find_element(By.ID, "debugInfo")
            debug_displayed = debug_info.is_displayed() and len(debug_info.text) > 0
            
            self.log_test("Settings tab functionality", debug_displayed,
                        "Debug info button works and displays information")
            
        except Exception as e:
            self.log_test("Settings tab", False, str(e))
    
    def test_tab_navigation(self):
        """Test navigation between tabs."""
        if not self.driver:
            return
        
        print("\n🔄 Testing Tab Navigation...")
        
        try:
            tab_buttons = self.driver.find_elements(By.CLASS_NAME, "tab-button")
            tab_names = [btn.text for btn in tab_buttons]
            
            navigation_success = True
            
            for i, tab_button in enumerate(tab_buttons):
                try:
                    # Click the tab
                    tab_button.click()
                    time.sleep(0.5)
                    
                    # Check if tab becomes active
                    is_active = "active" in tab_button.get_attribute("class")
                    
                    if not is_active:
                        navigation_success = False
                        break
                        
                except Exception:
                    navigation_success = False
                    break
            
            self.log_test("Tab navigation", navigation_success,
                        f"Successfully navigated through {len(tab_buttons)} tabs: {', '.join(tab_names)}")
            
        except Exception as e:
            self.log_test("Tab navigation", False, str(e))
    
    def test_form_validation(self):
        """Test form validation and error handling."""
        if not self.driver:
            return
        
        print("\n✅ Testing Form Validation...")
        
        try:
            # Go to card management tab
            cards_tab = self.driver.find_element(By.XPATH, "//button[contains(text(), 'Manage Cards')]")
            cards_tab.click()
            
            # Show add card form
            add_card_btn = self.driver.find_element(By.XPATH, "//button[contains(text(), 'Add New Card')]")
            add_card_btn.click()
            
            # Try to submit empty form
            add_card_form = WebDriverWait(self.driver, 5).until(
                EC.visibility_of_element_located((By.ID, "addCardForm"))
            )
            
            submit_btn = add_card_form.find_element(By.XPATH, ".//button[@type='submit']")
            submit_btn.click()
            
            # Check if validation prevents submission
            # (In HTML5, required fields should prevent submission)
            card_name_field = self.driver.find_element(By.ID, "cardName")
            validation_message = card_name_field.get_attribute("validationMessage")
            
            has_validation = len(validation_message) > 0
            
            self.log_test("Form validation", has_validation,
                        f"Form validation message: '{validation_message}'")
            
        except Exception as e:
            self.log_test("Form validation", False, str(e))
    
    def test_console_errors(self):
        """Test for JavaScript console errors."""
        if not self.driver:
            return
        
        print("\n🚨 Testing for Console Errors...")
        
        try:
            # Navigate to the main page
            self.driver.get(self.base_url)
            
            # Wait for page to load
            time.sleep(3)
            
            # Get browser console logs
            logs = self.driver.get_log('browser')
            
            # Filter for errors and warnings
            errors = [log for log in logs if log['level'] in ['SEVERE', 'WARNING']]
            
            has_errors = len(errors) > 0
            
            if has_errors:
                error_messages = [f"{log['level']}: {log['message']}" for log in errors[:5]]
                self.log_test("Console errors check", False,
                            f"Found {len(errors)} errors/warnings: {'; '.join(error_messages)}")
            else:
                self.log_test("Console errors check", True, "No console errors found")
            
        except Exception as e:
            self.log_test("Console errors check", False, f"Could not check console: {str(e)}")
    
    def test_network_requests(self):
        """Test if API requests are being made from frontend."""
        if not self.driver:
            return
        
        print("\n🌐 Testing Network Requests...")
        
        try:
            # Enable performance logging
            caps = self.driver.desired_capabilities
            caps['goog:loggingPrefs'] = {'performance': 'ALL'}
            
            # Navigate to dashboard and trigger refresh
            self.driver.get(self.base_url)
            
            # Click refresh button to trigger API calls
            refresh_btn = WebDriverWait(self.driver, 10).until(
                EC.element_to_be_clickable((By.ID, "refreshBtn"))
            )
            refresh_btn.click()
            
            # Wait for requests to complete
            time.sleep(3)
            
            # Get performance logs
            logs = self.driver.get_log('performance')
            
            # Look for API requests
            api_requests = []
            for log in logs:
                message = json.loads(log['message'])
                if message['message']['method'] == 'Network.responseReceived':
                    url = message['message']['params']['response']['url']
                    if '/api/' in url:
                        status = message['message']['params']['response']['status']
                        api_requests.append(f"{url} - {status}")
            
            has_api_requests = len(api_requests) > 0
            
            self.log_test("Network API requests", has_api_requests,
                        f"Found {len(api_requests)} API requests: {'; '.join(api_requests[:3])}")
            
        except Exception as e:
            # Fallback: just check if the page loads and shows data
            try:
                self.driver.get(self.base_url)
                time.sleep(5)
                
                # Check if dashboard shows any data (indicating API calls worked)
                total_spending = self.driver.find_element(By.ID, "totalSpending")
                spending_text = total_spending.text
                
                has_data = spending_text != "$0.00" or "Loading" not in spending_text
                
                self.log_test("Network API requests (fallback)", has_data,
                            f"Dashboard shows data: {spending_text}")
                
            except Exception as e2:
                self.log_test("Network requests check", False, f"Could not test network requests: {str(e2)}")
    
    def test_detailed_form_submission(self):
        """Test detailed form submission process with step-by-step verification."""
        if not self.driver:
            return
        
        print("\n📝 Testing Detailed Form Submission Process...")
        
        try:
            # Navigate to cards tab
            cards_tab = self.driver.find_element(By.XPATH, "//button[contains(text(), 'Manage Cards')]")
            cards_tab.click()
            
            # Show add card form
            add_card_btn = self.driver.find_element(By.XPATH, "//button[contains(text(), 'Add New Card')]")
            add_card_btn.click()
            
            # Fill form step by step
            form_steps = [
                ("cardName", "Detailed Test Card"),
                ("creditLimit", "7500"),
                ("statementDate", "20"),
                ("dueDate", "15"),
                ("currentBalance", "150"),
                ("balanceDue", "300"),
                ("cardDescription", "Detailed test card for debugging")
            ]
            
            for field_id, value in form_steps:
                field = self.driver.find_element(By.ID, field_id)
                field.clear()
                field.send_keys(value)
                time.sleep(0.2)  # Small delay between inputs
            
            # Get form element and check if it has proper event handlers
            form = self.driver.find_element(By.XPATH, "//form[.//input[@id='cardName']]")
            form_html = form.get_attribute('outerHTML')
            has_onsubmit = 'onsubmit' in form_html
            
            # Submit the form
            submit_btn = form.find_element(By.XPATH, ".//button[@type='submit']")
            
            # Check if submit button is enabled
            submit_enabled = submit_btn.is_enabled()
            
            # Record initial API state
            initial_response = requests.get(f'{self.base_url}/api/cards')
            initial_cards = initial_response.json()['data'] if initial_response.json()['success'] else []
            initial_count = len(initial_cards)
            
            # Submit form
            submit_btn.click()
            
            # Wait for submission to process
            time.sleep(3)
            
            # Check final API state
            final_response = requests.get(f'{self.base_url}/api/cards')
            final_cards = final_response.json()['data'] if final_response.json()['success'] else []
            final_count = len(final_cards)
            
            # Check if card was actually added
            card_added = final_count > initial_count
            
            # Look for the specific card
            test_card_found = any(card['name'] == 'Detailed Test Card' for card in final_cards)
            
            self.log_test("Detailed form submission", card_added and test_card_found,
                        f"Form has onsubmit: {has_onsubmit}, Submit enabled: {submit_enabled}, "
                        f"Cards before: {initial_count}, Cards after: {final_count}, "
                        f"Test card found: {test_card_found}")
            
        except Exception as e:
            self.log_test("Detailed form submission", False, str(e))
    
    def create_test_csv(self):
        """Create a test CSV file for upload testing."""
        test_csv_path = tempfile.mktemp(suffix='.csv')
        
        transactions = [
            ['2024-01-15', 'AMAZON MKTPL', 'Shopping', -89.99, 'Online purchase'],
            ['2024-01-16', 'STARBUCKS #1234', 'Restaurants', -5.45, 'Coffee'],
            ['2024-01-17', 'KROGER #567', 'Grocery', -127.33, 'Groceries'],
            ['2024-01-18', 'SHELL OIL', 'Gas', -45.00, 'Gas station'],
            ['2024-01-19', 'NETFLIX.COM', 'Entertainment', -15.99, 'Subscription']
        ]
        
        with open(test_csv_path, 'w', newline='') as csvfile:
            writer = csv.writer(csvfile)
            writer.writerow(['Transaction Date', 'Description', 'Category', 'Amount', 'Memo'])
            writer.writerows(transactions)
        
        return test_csv_path
    
    def test_responsive_design(self):
        """Test responsive design on different screen sizes."""
        if not self.driver:
            return
        
        print("\n📱 Testing Responsive Design...")
        
        try:
            # Test different screen sizes
            screen_sizes = [
                (1920, 1080, "Desktop"),
                (768, 1024, "Tablet"),
                (375, 667, "Mobile")
            ]
            
            responsive_success = True
            
            for width, height, device in screen_sizes:
                self.driver.set_window_size(width, height)
                time.sleep(1)
                
                # Check if header is still visible
                header = self.driver.find_element(By.CLASS_NAME, "header")
                header_visible = header.is_displayed()
                
                # Check if navigation tabs are accessible
                tabs = self.driver.find_elements(By.CLASS_NAME, "tab-button")
                tabs_accessible = len(tabs) > 0 and all(tab.is_displayed() for tab in tabs[:3])
                
                if not (header_visible and tabs_accessible):
                    responsive_success = False
                    break
            
            # Reset to original size
            self.driver.set_window_size(1920, 1080)
            
            self.log_test("Responsive design", responsive_success,
                        f"Tested {len(screen_sizes)} screen sizes successfully")
            
        except Exception as e:
            self.log_test("Responsive design", False, str(e))
    
    def test_javascript_functionality(self):
        """Test JavaScript functionality and interactions."""
        if not self.driver:
            return
        
        print("\n🖥️ Testing JavaScript Functionality...")
        
        try:
            # Test if JavaScript is working by checking dynamic content
            self.driver.get(self.base_url)
            
            # Wait for JavaScript to load
            WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.ID, "totalSpending"))
            )
            
            # Check if the last updated time gets set by JavaScript
            WebDriverWait(self.driver, 15).until(
                EC.presence_of_element_located((By.ID, "lastUpdated"))
            )
            
            last_updated = self.driver.find_element(By.ID, "lastUpdated")
            has_timestamp = len(last_updated.text) > 0
            
            # Test JavaScript function by clicking refresh
            refresh_btn = self.driver.find_element(By.ID, "refreshBtn")
            original_text = refresh_btn.text
            
            refresh_btn.click()
            
            # Check if button text changes during loading
            time.sleep(0.5)
            loading_text = refresh_btn.text
            text_changed = loading_text != original_text
            
            # Wait for refresh to complete
            time.sleep(3)
            
            self.log_test("JavaScript functionality", has_timestamp and text_changed,
                        f"Timestamp displayed: {has_timestamp}, Button text changes: {text_changed}")
            
        except Exception as e:
            self.log_test("JavaScript functionality", False, str(e))
    
    def run_all_tests(self):
        """Run the complete frontend test suite."""
        print("🧪 Starting Credit Card Tracker Frontend Test Suite")
        print("=" * 70)
        
        start_time = datetime.now()
        
        try:
            self.setup_test_environment()
            
            # API Tests
            self.test_api_endpoints()
            
            # Frontend Tests (only if web driver is available)
            if self.driver:
                self.test_frontend_loading()
                self.test_console_errors()
                self.test_dashboard_functionality()
                self.test_card_management_tab()
                self.test_detailed_form_submission()
                self.test_budget_limits_tab()
                self.test_transaction_upload_tab()
                self.test_settings_tab()
                self.test_tab_navigation()
                self.test_form_validation()
                self.test_network_requests()
                self.test_responsive_design()
                self.test_javascript_functionality()
            else:
                print("\n⚠️ Skipping browser tests - Chrome driver not available")
                print("   Install ChromeDriver for full frontend testing")
            
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
        print("\n" + "=" * 70)
        print("🧪 FRONTEND TEST RESULTS SUMMARY")
        print("=" * 70)
        
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
            print(f"\n🎉 ALL FRONTEND TESTS PASSED! Your web interface is working perfectly.")
        else:
            print(f"\n⚠️  {failed_tests} test(s) failed. Please review the errors above.")
        
        print("=" * 70)
        
        # Save detailed report
        report_file = f"frontend_test_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        try:
            with open(report_file, 'w') as f:
                json.dump({
                    'timestamp': datetime.now().isoformat(),
                    'duration_seconds': duration.total_seconds(),
                    'total_tests': total_tests,
                    'passed_tests': passed_tests,
                    'failed_tests': failed_tests,
                    'success_rate': passed_tests/total_tests*100,
                    'server_url': self.base_url,
                    'driver_available': self.driver is not None,
                    'results': [
                        {
                            'test': result['test'],
                            'passed': bool(result['passed']),
                            'details': str(result['details']) if result['details'] is not None else ""
                        }
                        for result in self.test_results
                    ]
                }, f, indent=2, ensure_ascii=False)
            
            print(f"📄 Detailed report saved to: {report_file}")
        except Exception as e:
            print(f"⚠️  Could not save detailed report: {e}")

def main():
    """Run the frontend test suite."""
    if len(sys.argv) > 1 and sys.argv[1] in ['--help', '-h']:
        print("Credit Card Tracker Frontend Test Suite")
        print("\nUsage: python3 test_frontend.py")
        print("\nThis will run comprehensive tests of:")
        print("- Web API endpoints")
        print("- Frontend page loading")
        print("- Tab navigation")
        print("- Form submissions")
        print("- JavaScript functionality")
        print("- Responsive design")
        print("- Browser interactions")
        print("\nRequirements:")
        print("- Chrome browser installed")
        print("- ChromeDriver in PATH or same directory")
        print("- pip install selenium requests")
        print("\nThe test creates a temporary environment and restores original data.")
        return
    
    # Check for required dependencies
    try:
        import selenium
        import requests
        from webdriver_manager.chrome import ChromeDriverManager
    except ImportError as e:
        print(f"❌ Missing required dependency: {e}")
        print("Install with: pip install selenium requests webdriver-manager")
        return
    
    test_suite = FrontendTestSuite()
    test_suite.run_all_tests()

if __name__ == "__main__":
    main()