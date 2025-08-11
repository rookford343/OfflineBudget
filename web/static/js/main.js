// Main initialization and event handlers

// Initialize application when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    console.log('Credit Card Tracker Frontend Initialized');
    
    // Load dashboard on page load
    loadDashboard();
    
    // Initialize file upload for transactions tab
    setupFileUploadOnLoad();
});

// Enhanced file upload initialization
function setupFileUploadOnLoad() {
    // Set up event listener for transactions tab button
    const transactionsTabButton = document.querySelector('button[onclick*="transactions"]');
    if (transactionsTabButton) {
        // Remove any existing onclick to replace with proper event handling
        transactionsTabButton.removeAttribute('onclick');
        transactionsTabButton.addEventListener('click', () => {
            showTab('transactions');
        });
    }
    
    // Initialize immediately if transactions tab is already active
    if (document.getElementById('transactions-tab')?.classList.contains('active')) {
        setTimeout(() => {
            console.log('Transactions tab is active, initializing file upload...');
            if (typeof setupFileUpload === 'function') {
                setupFileUpload();
            }
        }, 200);
    }
}

// Enhanced showTab function to handle initialization properly
function showTab(tabName) {
    console.log(`Switching to tab: ${tabName}`);
    
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
    const activeButton = document.querySelector(`button[onclick*="${tabName}"], .tab-button[data-tab="${tabName}"]`);
    if (activeButton) {
        activeButton.classList.add('active');
    }
    
    // Handle tab-specific initialization
    switch (tabName) {
        case 'dashboard':
            console.log('Loading dashboard...');
            if (typeof loadDashboard === 'function') {
                loadDashboard();
            }
            break;
            
        case 'cards':
            console.log('Loading cards management...');
            if (typeof loadCardsManagement === 'function') {
                setTimeout(loadCardsManagement, 100);
            }
            break;
            
        case 'budgets':
            console.log('Loading budget settings...');
            if (typeof loadCurrentBudgetSettings === 'function') {
                setTimeout(loadCurrentBudgetSettings, 100);
            }
            break;
            
        case 'transactions':
            console.log('Initializing transactions tab...');
            // Initialize file upload with a delay to ensure DOM is ready
            setTimeout(() => {
                if (typeof setupFileUpload === 'function') {
                    setupFileUpload();
                }
                if (typeof updateButtonStates === 'function') {
                    updateButtonStates();
                }
            }, 150);
            break;
            
        case 'historical':
            console.log('Loading stored analyses...');
            if (typeof loadStoredAnalyses === 'function') {
                setTimeout(loadStoredAnalyses, 100);
            }
            break;
            
        case 'analysis':
            console.log('Initializing analysis tab...');
            // Any analysis-specific initialization can go here
            break;
            
        case 'settings':
            console.log('Initializing settings tab...');
            // Any settings-specific initialization can go here
            break;
    }
}

// Override any existing showTab functions
window.showTab = showTab;

// Debugging helper
function debugTabState() {
    console.log('=== TAB DEBUG INFO ===');
    
    const activeTab = document.querySelector('.tab-content.active');
    const activeButton = document.querySelector('.tab-button.active');
    const transactionsTab = document.getElementById('transactions-tab');
    const fileInput = document.getElementById('csvFiles');
    const uploadArea = document.getElementById('fileUploadArea');
    
    console.log('Active tab:', activeTab?.id || 'none');
    console.log('Active button:', activeButton?.textContent?.trim() || 'none');
    console.log('Transactions tab active:', transactionsTab?.classList.contains('active'));
    console.log('File input exists:', !!fileInput);
    console.log('Upload area exists:', !!uploadArea);
    console.log('Upload area setup:', uploadArea?.hasAttribute('data-setup'));
    console.log('Selected files count:', typeof selectedFiles !== 'undefined' ? selectedFiles.length : 'undefined');
    
    if (fileInput) {
        console.log('File input value:', fileInput.value);
        console.log('File input files:', fileInput.files.length);
    }
    
    console.log('=== END DEBUG ===');
}

// Make debug function available globally
window.debugTabState = debugTabState;

// Enhanced error handling for common issues
window.addEventListener('error', function(e) {
    if (e.message.includes('setupFileUpload') || e.message.includes('selectedFiles')) {
        console.error('File upload error detected:', e.message);
        console.log('Attempting to reinitialize file upload...');
        
        // Attempt to reinitialize
        setTimeout(() => {
            if (document.getElementById('transactions-tab')?.classList.contains('active')) {
                setupFileUpload();
            }
        }, 500);
    }
});

// Additional safety check - ensure transactions tab initialization
setInterval(() => {
    const transactionsTabActive = document.getElementById('transactions-tab')?.classList.contains('active');
    const uploadAreaSetup = document.getElementById('fileUploadArea')?.hasAttribute('data-setup');
    
    if (transactionsTabActive && !uploadAreaSetup) {
        console.log('Detected uninitialized transactions tab, fixing...');
        if (typeof setupFileUpload === 'function') {
            setupFileUpload();
        }
    }
}, 2000); // Check every 2 seconds