// Core functionality - Tab management and main app functions

// Tab Management
function showTab(tabName) {
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
    }
    
    // Add active class to clicked tab button
    if (event && event.target) {
        event.target.classList.add('active');
    }
    
    // Load data for specific tabs
    if (tabName === 'dashboard') {
        loadDashboard();
    } else if (tabName === 'cards') {
        loadCardsManagement();
    } else if (tabName === 'budgets') {
        // Load budget settings with a small delay
        setTimeout(() => {
            loadCurrentBudgetSettings();
        }, 100);
    } else if (tabName === 'transactions') {
        // Initialize file upload for transactions tab
        setTimeout(setupFileUpload, 100);
    } else if (tabName === 'historical') {
        loadStoredAnalyses();
    }
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