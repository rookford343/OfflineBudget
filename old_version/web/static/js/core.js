// Core functionality - Tab management and main app functions

// Enhanced Tab Management with proper event handling
function showTab(tabName, event) {
    console.log(`Core showTab called for: ${tabName}`);
    
    // Prevent default if called from event
    if (event) {
        event.preventDefault();
    }
    
    // Hide all tab content
    document.querySelectorAll('.tab-content').forEach(tab => {
        tab.classList.remove('active');
    });
    
    // Remove active class from all tab buttons
    document.querySelectorAll('.tab-button').forEach(button => {
        button.classList.remove('active');
    });
    
    // Show selected tab content
    const targetTab = document.getElementById(tabName + '-tab');
    if (targetTab) {
        targetTab.classList.add('active');
        console.log(`Activated tab: ${tabName}-tab`);
    } else {
        console.error(`Tab not found: ${tabName}-tab`);
    }
    
    // Add active class to clicked tab button
    if (event && event.target) {
        event.target.classList.add('active');
    } else {
        // Find and activate the correct button
        const buttons = document.querySelectorAll('.tab-button');
        buttons.forEach(button => {
            if (button.textContent.toLowerCase().includes(getTabDisplayName(tabName).toLowerCase())) {
                button.classList.add('active');
            }
        });
    }
    
    // Load data for specific tabs with proper error handling
    try {
        switch (tabName) {
            case 'dashboard':
                console.log('Loading dashboard data...');
                if (typeof loadDashboard === 'function') {
                    loadDashboard();
                } else {
                    console.warn('loadDashboard function not available');
                }
                break;
                
            case 'cards':
                console.log('Loading cards management...');
                if (typeof loadCardsManagement === 'function') {
                    setTimeout(loadCardsManagement, 100);
                } else {
                    console.warn('loadCardsManagement function not available');
                }
                break;
                
            case 'budgets':
                console.log('Loading budget settings...');
                if (typeof loadCurrentBudgetSettings === 'function') {
                    setTimeout(loadCurrentBudgetSettings, 100);
                } else {
                    console.warn('loadCurrentBudgetSettings function not available');
                }
                break;
                
            case 'transactions':
                console.log('Initializing transactions tab...');
                // Multiple attempts to ensure file upload is properly initialized
                setTimeout(() => {
                    initializeTransactionsTabSafely();
                }, 100);
                break;
                
            case 'historical':
                console.log('Loading stored analyses...');
                if (typeof loadStoredAnalyses === 'function') {
                    setTimeout(loadStoredAnalyses, 100);
                } else {
                    console.warn('loadStoredAnalyses function not available');
                }
                break;
                
            case 'analysis':
                console.log('Analysis tab activated');
                break;
                
            case 'settings':
                console.log('Settings tab activated');
                break;
                
            default:
                console.warn(`Unknown tab: ${tabName}`);
        }
    } catch (error) {
        console.error(`Error initializing tab ${tabName}:`, error);
    }
}

// Helper function to safely initialize transactions tab
function initializeTransactionsTabSafely() {
    console.log('Safely initializing transactions tab...');
    
    try {
        // Check if elements exist
        const fileInput = document.getElementById('csvFiles');
        const uploadArea = document.getElementById('fileUploadArea');
        
        if (!fileInput || !uploadArea) {
            console.error('Required elements not found for transactions tab');
            return;
        }
        
        // Initialize file upload if function exists
        if (typeof setupFileUpload === 'function') {
            setupFileUpload();
        } else if (typeof window.setupFileUpload === 'function') {
            window.setupFileUpload();
        } else {
            console.error('setupFileUpload function not available');
        }
        
        // Update button states if function exists
        if (typeof updateButtonStates === 'function') {
            updateButtonStates();
        } else if (typeof window.updateButtonStates === 'function') {
            window.updateButtonStates();
        }
        
        console.log('Transactions tab initialization complete');
        
    } catch (error) {
        console.error('Error in initializeTransactionsTabSafely:', error);
    }
}

// Helper function to get display name for tab
function getTabDisplayName(tabName) {
    const displayNames = {
        'dashboard': 'Dashboard',
        'cards': 'Manage Cards',
        'budgets': 'Budgets',
        'transactions': 'Import Transactions',
        'analysis': 'Time Period Analysis',
        'historical': 'Historical Data',
        'settings': 'Settings'
    };
    return displayNames[tabName] || tabName;
}

// Due dates helper
function get_due_dates_data() {
    // This would normally come from the API, but we'll return empty for now
    return [];
}

// Category budgets helper  
function get_category_budgets_data() {
    // This would normally come from the API, but we'll return empty for now
    return [];
}

// Settings Functions
async function resetStatementPeriod() {
    if (!confirm('Are you sure you want to reset the statement period? This will move current balances to balance due.')) {
        return;
    }

    try {
        const response = await fetch('/api/reset-statement', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({})
        });

        const result = await response.json();
        
        if (result.success) {
            showMessage('Statement period reset successfully!', 'success');
            if (document.getElementById('dashboard-tab')?.classList.contains('active')) {
                setTimeout(loadDashboard, 1000);
            }
        } else {
            showMessage('Error resetting statement period: ' + result.error, 'error');
        }
    } catch (err) {
        showMessage('Error resetting statement period: ' + err.message, 'error');
    }
}

async function resetBalances(type) {
    const typeNames = {
        'current': 'current balances',
        'due': 'due balances',
        'all': 'all balances'
    };

    if (!confirm(`Are you sure you want to reset ${typeNames[type]}? This action cannot be undone.`)) {
        return;
    }

    try {
        const response = await fetch('/api/reset-balances', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ type: type })
        });

        const result = await response.json();
        
        if (result.success) {
            showMessage(`Reset ${typeNames[type]} successfully!`, 'success');
            if (document.getElementById('dashboard-tab')?.classList.contains('active')) {
                setTimeout(loadDashboard, 1000);
            }
        } else {
            showMessage(`Error resetting ${typeNames[type]}: ` + result.error, 'error');
        }
    } catch (err) {
        showMessage(`Error resetting ${typeNames[type]}: ` + err.message, 'error');
    }
}

async function showDebugInfo() {
    try {
        const response = await fetch('/api/debug');
        const result = await response.json();
        
        const debugInfo = document.getElementById('debugInfo');
        debugInfo.innerHTML = `
            <div class="analysis-results">
                <h4>System Information</h4>
                <pre style="background: #f8f8f8; padding: 1rem; border-radius: 4px; overflow-x: auto; font-size: 0.85rem;">${JSON.stringify(result, null, 2)}</pre>
            </div>
        `;
    } catch (err) {
        showMessage('Error loading debug info: ' + err.message, 'error');
    }
}

async function exportData(type) {
    try {
        let endpoint = '';
        if (type === 'summary') endpoint = '/api/summary';
        else if (type === 'cards') endpoint = '/api/cards';
        
        const response = await fetch(endpoint);
        const result = await response.json();
        
        const dataStr = JSON.stringify(result, null, 2);
        const dataBlob = new Blob([dataStr], {type: 'application/json'});
        
        const link = document.createElement('a');
        link.href = URL.createObjectURL(dataBlob);
        link.download = `credit_card_tracker_${type}_${new Date().toISOString().split('T')[0]}.json`;
        link.click();
        
        showMessage(`${type} data exported successfully!`, 'success');
    } catch (err) {
        showMessage(`Error exporting ${type} data: ` + err.message, 'error');
    }
}

// Make showTab globally available
window.showTab = showTab;