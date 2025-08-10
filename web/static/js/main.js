// Main initialization and event handlers

// Initialize application when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    console.log('Credit Card Tracker Frontend Initialized');
    
    // Load dashboard on page load
    loadDashboard();
    
    // Initialize file upload functionality
    setupFileUpload();
    
    // Load current budget settings if budgets tab is active
    if (document.getElementById('budgets-tab')?.classList.contains('active')) {
        setTimeout(() => {
            loadCurrentBudgetSettings();
        }, 1000);
    }
});

// File upload initialization helper
function initializeFileUploadWhenNeeded() {
    // Set up file upload when transactions tab is clicked
    const transactionsTabButton = document.querySelector('button[onclick="showTab(\'transactions\')"]');
    if (transactionsTabButton) {
        transactionsTabButton.addEventListener('click', function() {
            // Delay to ensure tab content is visible
            setTimeout(setupFileUpload, 100);
        });
    }
    
    // Also initialize if transactions tab is already active
    if (document.getElementById('transactions-tab')?.classList.contains('active')) {
        setTimeout(setupFileUpload, 100);
    }
}