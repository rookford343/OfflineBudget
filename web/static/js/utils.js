// Utility Functions for Credit Card Tracker

// Global variables
let isLoading = false;
let lastUpdateTime = null;
let selectedFiles = [];
let storedAnalyses = [];

// Utility Functions
function formatCurrency(amount) {
    return new Intl.NumberFormat('en-US', {
        style: 'currency',
        currency: 'USD',
        minimumFractionDigits: 2
    }).format(amount || 0);
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text || '';
    return div.innerHTML;
}

function formatFileSize(bytes) {
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
    return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
}

function updateLastUpdatedTime() {
    const lastUpdated = document.getElementById('lastUpdated');
    if (lastUpdated && lastUpdateTime) {
        // Format time without seconds (HH:MM AM/PM format)
        const timeOptions = { 
            hour: 'numeric', 
            minute: '2-digit',
            hour12: true 
        };
        
        const formattedTime = lastUpdateTime.toLocaleTimeString('en-US', timeOptions);
        lastUpdated.textContent = `Last updated: ${formattedTime}`;
    }
}

// Button state management
function setButtonLoading(buttonId, loadingText = 'Loading...') {
    // Handle both button elements and button IDs
    const button = typeof buttonId === 'string' ? document.getElementById(buttonId) : buttonId;
    if (!button) return null;
    
    const originalText = button.textContent || button.innerHTML;
    button.disabled = true;
    button.textContent = loadingText;
    
    return {
        restore: () => {
            button.disabled = false;
            button.textContent = originalText;
        }
    };
}

function restoreButton(button, originalText) {
    if (!button) return;
    button.disabled = false;
    button.classList.remove('loading');
    button.innerHTML = originalText || button.getAttribute('data-original-text') || button.innerHTML;
}

function setTransactionButtonLoading(button, loadingText) {
    if (!button) return;
    button.disabled = true;
    button.classList.add('loading');
    button.setAttribute('data-original-text', button.innerHTML);
    button.innerHTML = loadingText;
}

function restoreTransactionButton(button, originalText) {
    if (!button) return;
    button.disabled = false;
    button.classList.remove('loading');
    button.innerHTML = originalText || button.getAttribute('data-original-text') || button.innerHTML;
}

// Message display
function showError(message) {
    const error = document.getElementById('error');
    if (error) {
        error.textContent = message;
        error.style.display = 'block';
    }
}

function showMessage(message, type = 'info') {
    // Create a temporary message element
    const messageDiv = document.createElement('div');
    messageDiv.className = type;
    messageDiv.textContent = message;
    messageDiv.style.position = 'fixed';
    messageDiv.style.top = '20px';
    messageDiv.style.right = '20px';
    messageDiv.style.zIndex = '1000';
    messageDiv.style.maxWidth = '300px';
    
    document.body.appendChild(messageDiv);
    
    // Remove after 5 seconds
    setTimeout(() => {
        if (document.body.contains(messageDiv)) {
            document.body.removeChild(messageDiv);
        }
    }, 5000);
}

// Transaction results display
function showTransactionResults(config) {
    const resultsDiv = document.getElementById('transactionResults');
    if (!resultsDiv) return;
    
    resultsDiv.innerHTML = `
        <div class="results-card ${config.type}">
            <h4>${config.title}</h4>
            <p>${config.message}</p>
            ${config.details ? `
                <ul style="margin-top: 1rem; margin-left: 1rem;">
                    ${config.details.map(detail => `<li>${detail}</li>`).join('')}
                </ul>
            ` : ''}
        </div>
    `;
    
    resultsDiv.style.display = 'block';
    resultsDiv.scrollIntoView({ behavior: 'smooth' });
}

function hideTransactionResults() {
    const resultsDiv = document.getElementById('transactionResults');
    if (resultsDiv) {
        resultsDiv.style.display = 'none';
    }
}

// API helper functions
async function makeAPICall(url, options = {}) {
    try {
        const response = await fetch(url, options);
        
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }

        const result = await response.json();
        
        if (!result.success) {
            throw new Error(result.error || 'Unknown error occurred');
        }

        return result;
    } catch (error) {
        console.error(`API call failed for ${url}:`, error);
        throw error;
    }
}

// Debug helper
function debugBudgetData() {
    fetch('/api/summary')
        .then(response => response.json())
        .then(result => {
            console.log('=== DEBUG BUDGET DATA ===');
            console.log('Full API response:', result);
            if (result.success && result.data) {
                console.log('Summary data:', result.data);
                console.log('Spending message:', result.data.spending_message);
                console.log('Category budgets:', result.data.category_budgets);
                console.log('Total spending:', result.data.total_spending);
                console.log('Left to spend:', result.data.left_to_spend);
            }
            console.log('=== END DEBUG ===');
        })
        .catch(err => console.error('Debug error:', err));
}

// Initialize utilities when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    // Update time display every second
    setInterval(updateLastUpdatedTime, 1000);
    
    // Auto-refresh dashboard every 10 minutes
    setInterval(() => {
        if (!isLoading && document.getElementById('dashboard-tab')?.classList.contains('active')) {
            loadDashboard();
        }
    }, 600000);
});

// Handle keyboard shortcuts
document.addEventListener('keydown', (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === 'r') {
        e.preventDefault();
        if (typeof loadDashboard === 'function') {
            loadDashboard();
        }
    }
});