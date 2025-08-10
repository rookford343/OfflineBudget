// Budget Management Functions

async function loadCurrentBudgetSettings() {
    const loadingElement = document.getElementById('currentSettingsLoading');
    const contentElement = document.getElementById('currentSettingsContent');
    const refreshBtn = document.getElementById('refreshBudgetsBtn');
    
    // Show loading state
    if (loadingElement) loadingElement.style.display = 'block';
    if (contentElement) contentElement.style.display = 'none';
    
    // Simple button loading for refresh button
    let originalRefreshText = '';
    if (refreshBtn) {
        originalRefreshText = refreshBtn.textContent;
        refreshBtn.disabled = true;
        refreshBtn.textContent = '⏳';
    }
    
    try {
        console.log('Loading budget settings...');
        
        const summaryResponse = await fetch('/api/summary');
        
        if (!summaryResponse.ok) {
            throw new Error(`HTTP ${summaryResponse.status}: ${summaryResponse.statusText}`);
        }
        
        const summaryResult = await summaryResponse.json();
        console.log('Budget API response:', summaryResult);
        
        if (!summaryResult.success) {
            throw new Error(summaryResult.error || 'Failed to load budget data');
        }
        
        // Debug the data we received
        console.log('Processing budget data:', {
            spending_message: summaryResult.data.spending_message,
            category_budgets: summaryResult.data.category_budgets,
            total_spending: summaryResult.data.total_spending,
            left_to_spend: summaryResult.data.left_to_spend
        });
        
        displayCurrentSpendingLimits(summaryResult.data);
        displayCurrentCategoryBudgets(summaryResult.data.category_budgets || []);
        
        if (loadingElement) loadingElement.style.display = 'none';
        if (contentElement) contentElement.style.display = 'block';
        
    } catch (err) {
        console.error('Error loading current budget settings:', err);
        
        if (loadingElement) loadingElement.style.display = 'none';
        if (contentElement) {
            contentElement.innerHTML = `
                <div class="error" style="margin: 0.5rem 0; padding: 0.5rem; font-size: 0.9rem;">
                    Failed to load settings: ${err.message}
                    <br><button class="btn btn-small" onclick="loadCurrentBudgetSettings()" style="margin-top: 0.5rem;">Retry</button>
                    <button class="btn btn-small" onclick="debugBudgetData()" style="margin-top: 0.5rem;">Debug</button>
                </div>
            `;
            contentElement.style.display = 'block';
        }
    } finally {
        // Restore refresh button
        if (refreshBtn) {
            refreshBtn.disabled = false;
            refreshBtn.textContent = originalRefreshText || '🔄 Refresh';
        }
    }
}

// Display current spending limits
function displayCurrentSpendingLimits(summaryData) {
    const container = document.getElementById('currentSpendingLimits');
    if (!container) {
        console.log('currentSpendingLimits container not found');
        return;
    }
    
    console.log('Displaying spending limits with data:', summaryData);
    
    const totalSpending = summaryData.total_spending || 0;
    const leftToSpend = summaryData.left_to_spend || 0;
    const spendingMessage = summaryData.spending_message || '';
    
    // Check if limits are actually set by looking at the spending message
    const hasLimits = spendingMessage && 
                    !spendingMessage.includes('No Limits Set') && 
                    !spendingMessage.includes('No limits set');
    
    console.log('Has limits:', hasLimits, 'Message:', spendingMessage);
    
    if (!hasLimits) {
        container.innerHTML = `
            <div class="item-details" style="color: var(--text-secondary); font-style: italic;">
                No spending limits configured
            </div>
        `;
        return;
    }
    
    // Try to calculate limits based on spending and left to spend
    let softLimit = 0;
    let hardLimit = 0;
    
    if (leftToSpend !== 0) {
        softLimit = totalSpending + Math.abs(leftToSpend);
    }
    
    // Determine status
    const isOverBudget = leftToSpend < 0;
    const statusClass = isOverBudget ? 'status-warning' : 'status-good';
    const statusIcon = isOverBudget ? '⚠️' : '✅';
    
    container.innerHTML = `
        <div style="font-size: 0.9rem; line-height: 1.4;">
            <div style="display: flex; justify-content: space-between; margin-bottom: 0.25rem;">
                <span>Soft Limit:</span>
                <strong>${formatCurrency(softLimit)}</strong>
            </div>
            <div style="display: flex; justify-content: space-between; margin-bottom: 0.25rem;">
                <span>Current Spending:</span>
                <span class="${statusClass}">${formatCurrency(totalSpending)}</span>
            </div>
            <div style="display: flex; justify-content: space-between; margin-bottom: 0.25rem;">
                <span>Remaining:</span>
                <span class="${statusClass}">${formatCurrency(leftToSpend)}</span>
            </div>
            <div style="display: flex; justify-content: space-between; align-items: center;">
                <span>Status:</span>
                <span class="${statusClass}">${statusIcon}</span>
            </div>
        </div>
    `;
}

// UPDATED: Compact summary for category budgets
function displayCurrentCategoryBudgets(categoryBudgets) {
    const summaryContainer = document.getElementById('currentCategoryBudgetsSummary');
    const detailContainer = document.getElementById('currentCategoryBudgets');
    const toggleBtn = document.getElementById('toggleDetailsBtn');
    
    console.log('Displaying category budgets:', categoryBudgets);
    
    if (!summaryContainer) {
        console.log('currentCategoryBudgetsSummary container not found');
        return;
    }
    
    if (!categoryBudgets || categoryBudgets.length === 0) {
        summaryContainer.innerHTML = `
            <div class="item-details" style="color: var(--text-secondary); font-style: italic;">
                No category budgets configured
            </div>
        `;
        if (toggleBtn) toggleBtn.style.display = 'none';
        return;
    }
    
    // Show toggle button since we have budgets
    if (toggleBtn) toggleBtn.style.display = 'block';
    
    // Calculate totals
    const totalBudget = categoryBudgets.reduce((sum, cat) => sum + (cat.budget || 0), 0);
    const totalSpent = categoryBudgets.reduce((sum, cat) => sum + (cat.spent || 0), 0);
    const overBudgetCount = categoryBudgets.filter(cat => (cat.remaining || 0) < 0).length;
    
    // Create summary display
    summaryContainer.innerHTML = `
        <div style="font-size: 0.9rem; line-height: 1.4;">
            <div style="display: flex; justify-content: space-between; margin-bottom: 0.25rem;">
                <span>Total Budget:</span>
                <strong>${formatCurrency(totalBudget)}</strong>
            </div>
            <div style="display: flex; justify-content: space-between; margin-bottom: 0.25rem;">
                <span>Total Spent:</span>
                <span class="${totalSpent > totalBudget ? 'status-warning' : 'status-good'}">${formatCurrency(totalSpent)}</span>
            </div>
            <div style="display: flex; justify-content: space-between; align-items: center;">
                <span>Categories:</span>
                <span>${categoryBudgets.length} set${overBudgetCount > 0 ? `, ${overBudgetCount} over` : ''}</span>
            </div>
        </div>
    `;
    
    // Create detailed breakdown (for toggle)
    if (detailContainer) {
        const sortedBudgets = [...categoryBudgets].sort((a, b) => (b.budget || 0) - (a.budget || 0));
        
        const budgetHTML = sortedBudgets.map(cat => {
            const budget = cat.budget || 0;
            const spent = cat.spent || 0;
            const remaining = cat.remaining || (budget - spent);
            const progressWidth = budget > 0 ? Math.min((spent / budget) * 100, 100) : 0;
            
            // Determine status
            let statusClass = 'status-good';
            let progressClass = 'progress-good';
            
            if (remaining < 0) {
                statusClass = 'status-critical';
                progressClass = 'progress-critical';
            } else if (remaining < budget * 0.1) {
                statusClass = 'status-warning';
                progressClass = 'progress-warning';
            }
            
            return `
                <div style="margin-bottom: 0.75rem; padding-bottom: 0.5rem; border-bottom: 1px solid var(--border-color);">
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.25rem;">
                        <span style="font-weight: 500; font-size: 0.9rem;">${escapeHtml(cat.category)}</span>
                        <span class="item-amount ${statusClass}" style="font-size: 0.85rem;">
                            ${formatCurrency(spent)} / ${formatCurrency(budget)}
                        </span>
                    </div>
                    <div class="progress-bar" style="height: 4px; margin-bottom: 0.25rem;">
                        <div class="progress-fill ${progressClass}" style="width: ${progressWidth}%"></div>
                    </div>
                    <div style="display: flex; justify-content: space-between;">
                        <small class="item-details">${progressWidth.toFixed(0)}% used</small>
                        <small class="item-details ${statusClass}">
                            ${remaining >= 0 ? 
                            `${formatCurrency(remaining)} left` : 
                            `${formatCurrency(Math.abs(remaining))} over`}
                        </small>
                    </div>
                </div>
            `;
        }).join('');
        
        detailContainer.innerHTML = budgetHTML;
    }
}

// Set up current settings content structure
function setupCurrentSettingsContent() {
    const contentElement = document.getElementById('currentSettingsContent');
    if (!contentElement) return;
    
    contentElement.innerHTML = `
        <!-- Compact layout for current settings -->
        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 1rem;">
            <!-- Current spending limits -->
            <div class="compact-section">
                <h4 style="margin-bottom: 0.5rem; font-size: 1rem;">💰 Spending Limits</h4>
                <div id="currentSpendingLimits">
                    <div class="item-details">No limits set</div>
                </div>
            </div>
            
            <!-- Current category budgets summary -->
            <div class="compact-section">
                <h4 style="margin-bottom: 0.5rem; font-size: 1rem;">📈 Category Budgets</h4>
                <div id="currentCategoryBudgetsSummary">
                    <div class="item-details">No budgets set</div>
                </div>
            </div>
        </div>
        
        <!-- Detailed category breakdown (collapsible) -->
        <div id="categoryBudgetsDetail" style="margin-top: 1rem; padding-top: 1rem; border-top: 1px solid var(--border-color); display: none;">
            <div style="display: flex; justify-content: between; align-items: center; margin-bottom: 0.5rem;">
                <h4 style="margin: 0; font-size: 0.9rem; color: var(--text-secondary);">Category Details</h4>
            </div>
            <div id="currentCategoryBudgets"></div>
        </div>
        
        <!-- Toggle button for details -->
        <div id="toggleDetailsBtn" style="text-align: center; margin-top: 0.5rem; display: none;">
            <button class="btn btn-small btn-secondary" onclick="toggleCategoryDetails()" id="detailsToggleBtn">
                👁️ Show Details
            </button>
        </div>
    `;
}

async function setSpendingLimits(event) {
    event.preventDefault();
    
    const buttonState = setButtonLoading('spendingLimitsSubmitBtn', '⏳ Setting Limits...');
    
    try {
        const formData = new FormData(event.target);
        const softLimit = parseFloat(formData.get('softLimit')) || 0;
        const hardLimit = parseFloat(formData.get('hardLimit')) || 0;
        
        if (!softLimit && !hardLimit) {
            showMessage('Please enter at least one spending limit', 'error');
            return false;
        }

        console.log('Setting spending limits:', { softLimit, hardLimit });

        const response = await fetch('/api/spending-limits', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                soft_limit: softLimit,
                hard_limit: hardLimit
            })
        });

        const result = await response.json();
        
        if (result.success) {
            showMessage('Spending limits set successfully!', 'success');
            event.target.reset();
            
            // Auto-refresh current settings display
            console.log('Auto-refreshing budget settings...');
            setTimeout(() => {
                loadCurrentBudgetSettings();
                
                // Auto-hide edit forms after successful update (optional)
                const editSection = document.getElementById('editFormsSection');
                if (editSection && editSection.style.display !== 'none') {
                    setTimeout(() => {
                        toggleEditForms();
                    }, 1000);
                }
            }, 500);
        } else {
            showMessage('Error setting spending limits: ' + result.error, 'error');
        }
    } catch (err) {
        console.error('Error setting spending limits:', err);
        showMessage('Error setting spending limits: ' + err.message, 'error');
    } finally {
        if (buttonState) buttonState.restore();
    }
    
    return false;
}

async function setCategoryBudgets(event) {
    event.preventDefault();
    
    const buttonState = setButtonLoading('categoryBudgetsSubmitBtn', '⏳ Setting Budgets...');
    
    try {
        const formData = new FormData(event.target);
        const budgets = {
            Shopping: parseFloat(formData.get('budgetShopping')) || 0,
            'Food & Drinks': parseFloat(formData.get('budgetFoodDrinks')) || 0,
            Services: parseFloat(formData.get('budgetServices')) || 0,
            Entertainment: parseFloat(formData.get('budgetEntertainment')) || 0,
            Groceries: parseFloat(formData.get('budgetGroceries')) || 0,
            Other: parseFloat(formData.get('budgetOther')) || 0
        };

        console.log('Setting category budgets:', budgets);

        const response = await fetch('/api/category-budgets', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(budgets)
        });

        const result = await response.json();
        
        if (result.success) {
            showMessage('Category budgets set successfully!', 'success');
            event.target.reset();
            
            // Auto-refresh current settings display
            console.log('Auto-refreshing budget settings...');
            setTimeout(() => {
                loadCurrentBudgetSettings();
                
                // Auto-hide edit forms after successful update (optional)
                const editSection = document.getElementById('editFormsSection');
                if (editSection && editSection.style.display !== 'none') {
                    setTimeout(() => {
                        toggleEditForms();
                    }, 1000);
                }
            }, 500);
        } else {
            showMessage('Error setting category budgets: ' + result.error, 'error');
        }
    } catch (err) {
        console.error('Error setting category budgets:', err);
        showMessage('Error setting category budgets: ' + err.message, 'error');
    } finally {
        if (buttonState) buttonState.restore();
    }
    
    return false;
}

// NEW: Toggle edit forms visibility
function toggleEditForms() {
    const editSection = document.getElementById('editFormsSection');
    const toggleBtn = document.getElementById('toggleEditBtn');
    
    if (!editSection || !toggleBtn) return;
    
    const isVisible = editSection.style.display !== 'none';
    
    if (isVisible) {
        // Hide forms
        editSection.style.display = 'none';
        toggleBtn.innerHTML = '✏️ Edit Settings';
        toggleBtn.className = 'btn btn-secondary';
    } else {
        // Show forms
        editSection.style.display = 'block';
        toggleBtn.innerHTML = '👁️ View Only';
        toggleBtn.className = 'btn btn-warning';
        
        // Scroll to forms
        editSection.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
}

// NEW: Toggle category details visibility
function toggleCategoryDetails() {
    const detailsSection = document.getElementById('categoryBudgetsDetail');
    const toggleBtn = document.getElementById('detailsToggleBtn');
    
    if (!detailsSection || !toggleBtn) return;
    
    const isVisible = detailsSection.style.display !== 'none';
    
    if (isVisible) {
        detailsSection.style.display = 'none';
        toggleBtn.innerHTML = '👁️ Show Details';
    } else {
        detailsSection.style.display = 'block';
        toggleBtn.innerHTML = '👁️ Hide Details';
    }
}

// Initialize budget settings structure when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    // Set up the budget settings content structure
    setupCurrentSettingsContent();
});