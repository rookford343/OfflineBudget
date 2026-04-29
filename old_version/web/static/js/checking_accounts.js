// Enhanced Frontend - Checking Account Management & Forecasting
// This extends the existing frontend with new checking account features

// Global variables for checking account management
let currentForecast = null;
let recurringTransactions = [];
let checkingAccounts = [];

// =============================================================================
// CHECKING ACCOUNT MANAGEMENT
// =============================================================================

async function loadCheckingAccounts() {
    try {
        const response = await fetch('/api/checking-accounts');
        const result = await response.json();
        
        if (result.success) {
            checkingAccounts = result.data;
            displayCheckingAccounts(result.data);
            updateForecastAccountDropdowns();
            return result.data;
        } else {
            console.warn('Checking accounts not available:', result.error);
            showCheckingAccountsUnavailable();
            return [];
        }
    } catch (err) {
        console.error('Error loading checking accounts:', err);
        showMessage('Error loading checking accounts: ' + err.message, 'error');
        return [];
    }
}

function displayCheckingAccounts(accounts) {
    const container = document.getElementById('checkingAccountsList');
    if (!container) return;
    
    if (!accounts || accounts.length === 0) {
        container.innerHTML = `
            <div class="empty-state">
                <div class="empty-state-icon">🏦</div>
                <p>No checking accounts found</p>
                <button class="btn btn-success" onclick="showAddCheckingAccountForm()">
                    ➕ Add Your First Checking Account
                </button>
            </div>
        `;
        return;
    }
    
    let totalBalance = accounts.reduce((sum, acc) => sum + acc.current_balance, 0);
    
    container.innerHTML = `
        <div class="checking-accounts-summary" style="margin-bottom: 1.5rem; padding: 1rem; background: #f0f9ff; border-radius: 8px; border-left: 4px solid #0ea5e9;">
            <div style="display: flex; justify-content: space-between; align-items: center;">
                <div>
                    <h4 style="margin: 0; color: #0f172a;">Total Checking Balance</h4>
                    <div style="font-size: 1.5rem; font-weight: bold; color: ${totalBalance >= 0 ? '#16a34a' : '#dc2626'}">${formatCurrency(totalBalance)}</div>
                </div>
                <div style="text-align: right;">
                    <div style="font-size: 0.9rem; color: #64748b;">${accounts.length} account${accounts.length !== 1 ? 's' : ''}</div>
                    <button class="btn btn-success btn-small" onclick="showAddCheckingAccountForm()">
                        ➕ Add Account
                    </button>
                </div>
            </div>
        </div>
        
        <div class="checking-accounts-list">
            ${accounts.map(account => `
                <div class="list-item checking-account-item" style="border-left: 4px solid ${account.current_balance >= 0 ? '#16a34a' : '#dc2626'}">
                    <div class="item-info" style="flex-grow: 1;">
                        <div class="item-name" style="display: flex; justify-content: space-between; align-items: center;">
                            <span>${escapeHtml(account.name)}</span>
                            <span class="balance-amount" style="font-size: 1.2rem; font-weight: bold; color: ${account.current_balance >= 0 ? '#16a34a' : '#dc2626'}">
                                ${formatCurrency(account.current_balance)}
                            </span>
                        </div>
                        <div class="item-details">
                            ${account.bank_name ? `🏦 ${account.bank_name} • ` : ''}
                            📊 ${account.account_type || 'Checking'} Account
                            ${account.description ? ` • ${account.description}` : ''}
                        </div>
                        ${account.last_updated ? `
                            <div class="item-details" style="font-size: 0.8rem; color: #6b7280;">
                                Last updated: ${new Date(account.last_updated).toLocaleDateString()}
                            </div>
                        ` : ''}
                    </div>
                    <div class="item-actions">
                        <button class="btn btn-small btn-info" onclick="generateAccountForecast('${escapeHtml(account.name)}')">
                            📈 Forecast
                        </button>
                        <button class="btn btn-small" onclick="editCheckingAccount('${escapeHtml(account.name)}')">
                            ✏️ Edit
                        </button>
                        <button class="btn btn-small btn-secondary" onclick="uploadCheckingTransactions('${escapeHtml(account.name)}')">
                            📄 Import CSV
                        </button>
                    </div>
                </div>
            `).join('')}
        </div>
    `;
}

function showAddCheckingAccountForm() {
    const modal = createModal('Add Checking Account', `
        <form onsubmit="return addCheckingAccount(event)" id="addCheckingAccountForm">
            <div class="form-group">
                <label class="form-label">Account Name *</label>
                <input type="text" class="form-input" id="checkingAccountName" name="name" required 
                       placeholder="e.g., Main Checking, Chase Checking">
            </div>
            <div class="form-row">
                <div class="form-group">
                    <label class="form-label">Current Balance *</label>
                    <input type="number" class="form-input" id="currentBalance" name="current_balance" required 
                           placeholder="5000.00" step="0.01">
                </div>
                <div class="form-group">
                    <label class="form-label">Bank Name</label>
                    <input type="text" class="form-input" id="bankName" name="bank_name" 
                           placeholder="e.g., Chase, Wells Fargo">
                </div>
            </div>
            <div class="form-row">
                <div class="form-group">
                    <label class="form-label">Account Type</label>
                    <select class="form-select" id="accountType" name="account_type">
                        <option value="checking">Checking</option>
                        <option value="savings">Savings</option>
                        <option value="money_market">Money Market</option>
                    </select>
                </div>
                <div class="form-group">
                    <label class="form-label">Description</label>
                    <input type="text" class="form-input" id="description" name="description" 
                           placeholder="Optional description">
                </div>
            </div>
            <div class="form-group" style="margin-top: 1.5rem;">
                <button type="submit" class="btn btn-success">Add Checking Account</button>
                <button type="button" class="btn btn-secondary" onclick="closeModal()">Cancel</button>
            </div>
        </form>
    `);
}

async function addCheckingAccount(event) {
    event.preventDefault();
    
    const form = event.target;
    const formData = new FormData(form);
    
    const data = {
        name: formData.get('name'),
        current_balance: parseFloat(formData.get('current_balance')),
        bank_name: formData.get('bank_name') || '',
        account_type: formData.get('account_type'),
        description: formData.get('description') || ''
    };
    
    const submitButton = form.querySelector('button[type="submit"]');
    submitButton.disabled = true;
    submitButton.textContent = 'Adding...';
    
    try {
        const response = await fetch('/api/checking-accounts', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });
        
        const result = await response.json();
        
        if (result.success) {
            showMessage('✅ ' + result.message, 'success');
            closeModal();
            await loadCheckingAccounts(); // Refresh the list
        } else {
            throw new Error(result.error);
        }
    } catch (err) {
        showMessage('❌ Failed to add checking account: ' + err.message, 'error');
    } finally {
        submitButton.disabled = false;
        submitButton.textContent = 'Add Checking Account';
    }
}

// =============================================================================
// RECURRING TRANSACTION MANAGEMENT
// =============================================================================

async function loadRecurringTransactions() {
    try {
        const response = await fetch('/api/recurring-transactions');
        const result = await response.json();
        
        if (result.success) {
            recurringTransactions = result.data;
            displayRecurringTransactions(result.data);
            return result.data;
        } else {
            console.warn('Recurring transactions not available:', result.error);
            return [];
        }
    } catch (err) {
        console.error('Error loading recurring transactions:', err);
        return [];
    }
}

function displayRecurringTransactions(transactions) {
    const container = document.getElementById('recurringTransactionsList');
    if (!container) return;
    
    if (!transactions || transactions.length === 0) {
        container.innerHTML = `
            <div class="empty-state">
                <div class="empty-state-icon">🔄</div>
                <p>No recurring transactions found</p>
                <button class="btn btn-success" onclick="showAddRecurringTransactionForm()">
                    ➕ Add Recurring Transaction
                </button>
            </div>
        `;
        return;
    }
    
    // Group by type
    const groupedTransactions = transactions.reduce((groups, trans) => {
        const type = trans.transaction_type;
        if (!groups[type]) groups[type] = [];
        groups[type].push(trans);
        return groups;
    }, {});
    
    let html = `
        <div style="margin-bottom: 1rem; display: flex; justify-content: space-between; align-items: center;">
            <div style="font-weight: bold; color: #374151;">
                ${transactions.length} Active Recurring Transaction${transactions.length !== 1 ? 's' : ''}
            </div>
            <button class="btn btn-success btn-small" onclick="showAddRecurringTransactionForm()">
                ➕ Add Transaction
            </button>
        </div>
    `;
    
    // Display each group
    Object.entries(groupedTransactions).forEach(([type, typeTransactions]) => {
        const typeTitle = type.replace('_', ' ').split(' ').map(word => 
            word.charAt(0).toUpperCase() + word.slice(1)
        ).join(' ');
        
        html += `
            <div class="recurring-transaction-group" style="margin-bottom: 1.5rem;">
                <h4 style="margin: 0 0 0.5rem 0; color: #374151; font-size: 1rem;">
                    ${getTransactionTypeIcon(type)} ${typeTitle}
                </h4>
                <div class="recurring-transactions-list">
                    ${typeTransactions.map(trans => `
                        <div class="list-item recurring-transaction-item">
                            <div class="item-info">
                                <div class="item-name">${escapeHtml(trans.name)}</div>
                                <div class="item-details">
                                    ${formatTransactionAmount(trans.amount, trans.transaction_type)} • 
                                    ${formatRecurrencePattern(trans.recurrence_pattern)}
                                    ${trans.description ? ` • ${trans.description}` : ''}
                                </div>
                                <div class="item-details" style="font-size: 0.8rem; color: #6b7280;">
                                    Started: ${new Date(trans.start_date).toLocaleDateString()}
                                    ${trans.end_date ? ` • Ends: ${new Date(trans.end_date).toLocaleDateString()}` : ' • No end date'}
                                </div>
                            </div>
                            <div class="item-actions">
                                <button class="btn btn-small" onclick="editRecurringTransaction('${trans.id}')">
                                    ✏️ Edit
                                </button>
                                <button class="btn btn-small btn-warning" onclick="deactivateRecurringTransaction('${trans.id}')">
                                    ⏸️ Deactivate
                                </button>
                            </div>
                        </div>
                    `).join('')}
                </div>
            </div>
        `;
    });
    
    container.innerHTML = html;
}

function getTransactionTypeIcon(type) {
    const icons = {
        'income': '💰',
        'expense': '💸',
        'transfer_out': '📤',
        'transfer_in': '📥',
        'credit_card_payment': '💳'
    };
    return icons[type] || '📊';
}

function formatTransactionAmount(amount, type) {
    const isPositive = ['income', 'transfer_in'].includes(type);
    const color = isPositive ? '#16a34a' : '#dc2626';
    const sign = isPositive ? '+' : '-';
    
    return `<span style="color: ${color}; font-weight: 600;">${sign}${formatCurrency(Math.abs(amount))}</span>`;
}

function formatRecurrencePattern(pattern) {
    const patterns = {
        'weekly': 'Weekly',
        'biweekly': 'Bi-weekly',
        'monthly': 'Monthly',
        'quarterly': 'Quarterly',
        'annually': 'Annually',
        'custom': 'Custom'
    };
    return patterns[pattern] || pattern;
}

function showAddRecurringTransactionForm() {
    const modal = createModal('Add Recurring Transaction', `
        <form onsubmit="return addRecurringTransaction(event)" id="addRecurringTransactionForm">
            <div class="form-row">
                <div class="form-group">
                    <label class="form-label">Transaction Name *</label>
                    <input type="text" class="form-input" id="recurringTransactionName" name="name" required 
                           placeholder="e.g., Salary, Rent, Utilities">
                </div>
                <div class="form-group">
                    <label class="form-label">Amount *</label>
                    <input type="number" class="form-input" id="recurringAmount" name="amount" required 
                           placeholder="1000.00" step="0.01">
                </div>
            </div>
            <div class="form-row">
                <div class="form-group">
                    <label class="form-label">Transaction Type *</label>
                    <select class="form-select" id="recurringTransactionType" name="transaction_type" required>
                        <option value="">Select type...</option>
                        <option value="income">💰 Income (Salary, etc.)</option>
                        <option value="expense">💸 Expense (Rent, utilities, etc.)</option>
                        <option value="credit_card_payment">💳 Credit Card Payment</option>
                        <option value="transfer_out">📤 Transfer Out (to savings)</option>
                        <option value="transfer_in">📥 Transfer In</option>
                    </select>
                </div>
                <div class="form-group">
                    <label class="form-label">Frequency *</label>
                    <select class="form-select" id="recurrencePattern" name="recurrence_pattern" required>
                        <option value="">Select frequency...</option>
                        <option value="weekly">Weekly</option>
                        <option value="biweekly">Bi-weekly (every 2 weeks)</option>
                        <option value="monthly">Monthly</option>
                        <option value="quarterly">Quarterly</option>
                        <option value="annually">Annually</option>
                    </select>
                </div>
            </div>
            <div class="form-row">
                <div class="form-group">
                    <label class="form-label">Start Date *</label>
                    <input type="date" class="form-input" id="recurringStartDate" name="start_date" required>
                </div>
                <div class="form-group">
                    <label class="form-label">End Date (Optional)</label>
                    <input type="date" class="form-input" id="recurringEndDate" name="end_date">
                </div>
            </div>
            <div class="form-row">
                <div class="form-group">
                    <label class="form-label">Day of Month (for monthly)</label>
                    <input type="number" class="form-input" id="dayOfMonth" name="day_of_month" 
                           placeholder="1-31" min="1" max="31">
                    <small class="item-details">Leave blank to use start date's day</small>
                </div>
                <div class="form-group">
                    <label class="form-label">Category</label>
                    <input type="text" class="form-input" id="recurringCategory" name="category" 
                           placeholder="e.g., Salary, Rent, Utilities">
                </div>
            </div>
            <div class="form-group">
                <label class="form-label">Description</label>
                <textarea class="form-input" id="recurringDescription" name="description" rows="2" 
                          placeholder="Optional description"></textarea>
            </div>
            <div class="form-group" style="margin-top: 1.5rem;">
                <button type="submit" class="btn btn-success">Add Recurring Transaction</button>
                <button type="button" class="btn btn-secondary" onclick="closeModal()">Cancel</button>
            </div>
        </form>
    `);
    
    // Set default start date to today
    document.getElementById('recurringStartDate').valueAsDate = new Date();
}

async function addRecurringTransaction(event) {
    event.preventDefault();
    
    const form = event.target;
    const formData = new FormData(form);
    
    const data = {
        name: formData.get('name'),
        amount: parseFloat(formData.get('amount')),
        transaction_type: formData.get('transaction_type'),
        recurrence_pattern: formData.get('recurrence_pattern'),
        start_date: formData.get('start_date'),
        end_date: formData.get('end_date') || null,
        day_of_month: formData.get('day_of_month') ? parseInt(formData.get('day_of_month')) : null,
        category: formData.get('category') || '',
        description: formData.get('description') || ''
    };
    
    const submitButton = form.querySelector('button[type="submit"]');
    submitButton.disabled = true;
    submitButton.textContent = 'Adding...';
    
    try {
        const response = await fetch('/api/recurring-transactions', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });
        
        const result = await response.json();
        
        if (result.success) {
            showMessage('✅ ' + result.message, 'success');
            closeModal();
            await loadRecurringTransactions(); // Refresh the list
        } else {
            throw new Error(result.error);
        }
    } catch (err) {
        showMessage('❌ Failed to add recurring transaction: ' + err.message, 'error');
    } finally {
        submitButton.disabled = false;
        submitButton.textContent = 'Add Recurring Transaction';
    }
}

// =============================================================================
// 12-MONTH BALANCE FORECASTING
// =============================================================================

async function generateAccountForecast(accountName) {
    console.log(`Generating forecast for: ${accountName}`);
    
    // Show loading state
    const forecastContainer = document.getElementById('forecastResults');
    if (forecastContainer) {
        forecastContainer.innerHTML = `
            <div class="card">
                <div class="loading">
                    <div class="loading-spinner"></div>
                    <p>Generating 12-month forecast for ${accountName}...</p>
                </div>
            </div>
        `;
        forecastContainer.style.display = 'block';
        
        // Switch to checking accounts tab if not already there
        showTab('checking');
    }
    
    try {
        const response = await fetch(`/api/forecast/${encodeURIComponent(accountName)}`);
        const result = await response.json();
        
        if (result.success) {
            currentForecast = result.data;
            displayForecastResults(result.data);
            showMessage(`✅ Generated 12-month forecast for ${accountName}`, 'success');
        } else {
            throw new Error(result.error);
        }
    } catch (err) {
        console.error('Forecast error:', err);
        showMessage('❌ Failed to generate forecast: ' + err.message, 'error');
        
        if (forecastContainer) {
            forecastContainer.innerHTML = `
                <div class="card">
                    <h3>❌ Forecast Generation Failed</h3>
                    <p>${err.message}</p>
                    <button class="btn btn-secondary" onclick="hideForecastResults()">Close</button>
                </div>
            `;
        }
    }
}

function displayForecastResults(forecastData) {
    const container = document.getElementById('forecastResults');
    if (!container) return;
    
    const forecast = forecastData.forecast;
    const accountName = forecastData.account_name;
    
    if (!forecast || forecast.length === 0) {
        container.innerHTML = `
            <div class="card">
                <h3>No Forecast Data</h3>
                <p>Unable to generate forecast data.</p>
            </div>
        `;
        return;
    }
    
    // Analyze forecast for insights
    const risks = analyzeForecastRisks(forecast);
    const insights = generateForecastInsights(forecast);
    
    container.innerHTML = `
        <div class="card forecast-results">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 1.5rem;">
                <h3>📊 12-Month Balance Forecast - ${escapeHtml(accountName)}</h3>
                <div>
                    <button class="btn btn-secondary btn-small" onclick="exportForecast()">📄 Export</button>
                    <button class="btn btn-secondary btn-small" onclick="hideForecastResults()">✖️ Close</button>
                </div>
            </div>
            
            ${risks.length > 0 ? `
                <div class="forecast-alerts" style="margin-bottom: 1.5rem;">
                    <h4 style="margin: 0 0 0.5rem 0; color: #dc2626;">⚠️ Financial Alerts</h4>
                    ${risks.map(risk => `
                        <div class="alert alert-${risk.severity}" style="margin-bottom: 0.5rem; padding: 0.75rem; border-radius: 6px; border-left: 4px solid ${risk.severity === 'critical' ? '#dc2626' : '#f59e0b'};">
                            <strong>${risk.title}</strong><br>
                            ${risk.description}
                        </div>
                    `).join('')}
                </div>
            ` : ''}
            
            <div class="forecast-chart" style="margin-bottom: 2rem;">
                <canvas id="forecastChart" width="800" height="300"></canvas>
            </div>
            
            <div class="forecast-table" style="overflow-x: auto; margin-bottom: 2rem;">
                <table style="width: 100%; border-collapse: collapse; background: white; border-radius: 6px; overflow: hidden;">
                    <thead>
                        <tr style="background: #f8f9fa; border-bottom: 2px solid #dee2e6;">
                            <th style="padding: 1rem; text-align: left; font-weight: 600;">Month</th>
                            <th style="padding: 1rem; text-align: right; font-weight: 600;">Starting Balance</th>
                            <th style="padding: 1rem; text-align: right; font-weight: 600;">Income</th>
                            <th style="padding: 1rem; text-align: right; font-weight: 600;">Expenses</th>
                            <th style="padding: 1rem; text-align: right; font-weight: 600;">Net Change</th>
                            <th style="padding: 1rem; text-align: right; font-weight: 600;">Ending Balance</th>
                            <th style="padding: 1rem; text-align: center; font-weight: 600;">Status</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${forecast.map((month, index) => {
                            const isCurrentMonth = index === 0;
                            const balanceColor = month.ending_balance >= 0 ? '#16a34a' : '#dc2626';
                            const netChangeColor = month.net_change >= 0 ? '#16a34a' : '#dc2626';
                            
                            return `
                                <tr style="background: ${isCurrentMonth ? '#f0f9ff' : 'white'}; border-bottom: 1px solid #e5e7eb;">
                                    <td style="padding: 1rem; font-weight: ${isCurrentMonth ? '600' : '400'};">
                                        ${month.month_name}
                                        ${isCurrentMonth ? '<span style="color: #3b82f6; font-size: 0.75rem; margin-left: 0.5rem;">CURRENT</span>' : ''}
                                    </td>
                                    <td style="padding: 1rem; text-align: right;">${formatCurrency(month.starting_balance)}</td>
                                    <td style="padding: 1rem; text-align: right; color: #16a34a;">${formatCurrency(month.income)}</td>
                                    <td style="padding: 1rem; text-align: right; color: #dc2626;">${formatCurrency(month.expenses)}</td>
                                    <td style="padding: 1rem; text-align: right; color: ${netChangeColor}; font-weight: 600;">
                                        ${month.net_change >= 0 ? '+' : ''}${formatCurrency(month.net_change)}
                                    </td>
                                    <td style="padding: 1rem; text-align: right; color: ${balanceColor}; font-weight: 600;">
                                        ${formatCurrency(month.ending_balance)}
                                    </td>
                                    <td style="padding: 1rem; text-align: center;">
                                        ${month.issues.length > 0 ? month.issues.join(' ') : '✅'}
                                    </td>
                                </tr>
                            `;
                        }).join('')}
                    </tbody>
                </table>
            </div>
            
            ${insights.length > 0 ? `
                <div class="forecast-insights">
                    <h4 style="margin: 0 0 1rem 0; color: #374151;">💡 Financial Insights</h4>
                    ${insights.map(insight => `
                        <div style="margin-bottom: 1rem; padding: 1rem; background: #f0f9ff; border-radius: 6px; border-left: 4px solid #3b82f6;">
                            <div style="font-weight: 600; color: #1e40af; margin-bottom: 0.25rem;">${insight.title}</div>
                            <div style="color: #374151;">${insight.description}</div>
                            ${insight.recommendation ? `
                                <div style="margin-top: 0.5rem; font-style: italic; color: #6b7280;">
                                    💡 Recommendation: ${insight.recommendation}
                                </div>
                            ` : ''}
                        </div>
                    `).join('')}
                </div>
            ` : ''}
        </div>
    `;
    
    container.style.display = 'block';
    container.scrollIntoView({ behavior: 'smooth' });
    
    // Create the forecast chart
    setTimeout(() => {
        createForecastChart(forecast);
    }, 100);
}

function analyzeForecastRisks(forecast) {
    const risks = [];
    
    // Check for negative balances
    const negativeMonths = forecast.filter(month => month.ending_balance < 0);
    if (negativeMonths.length > 0) {
        risks.push({
            severity: 'critical',
            title: 'Negative Balance Alert',
            description: `Account will go negative in ${negativeMonths.length} month(s): ${negativeMonths.map(m => m.month_name).join(', ')}`
        });
    }
    
    // Check for consistently low balances
    const lowBalanceMonths = forecast.filter(month => month.ending_balance > 0 && month.ending_balance < 500);
    if (lowBalanceMonths.length > 3) {
        risks.push({
            severity: 'warning',
            title: 'Low Balance Warning',
            description: `Account balance will be below $500 in ${lowBalanceMonths.length} months. Consider building emergency fund.`
        });
    }
    
    // Check for declining trend
    if (forecast.length >= 6) {
        const recentBalances = forecast.slice(1, 7).map(m => m.ending_balance); // Skip current month, next 6 months
        const isDecliningSteadily = recentBalances.every((balance, index, arr) => 
            index === 0 || balance < arr[index - 1]
        );
        
        if (isDecliningSteadily) {
            risks.push({
                severity: 'warning',
                title: 'Declining Balance Trend',
                description: 'Account balance is projected to decline consistently. Review your spending and income.'
            });
        }
    }
    
    return risks;
}

function generateForecastInsights(forecast) {
    const insights = [];
    
    // Calculate average monthly income and expenses
    const avgIncome = forecast.reduce((sum, month) => sum + month.income, 0) / forecast.length;
    const avgExpenses = forecast.reduce((sum, month) => sum + month.expenses, 0) / forecast.length;
    const savingsRate = avgIncome > 0 ? ((avgIncome - avgExpenses) / avgIncome) * 100 : 0;
    
    // Savings rate insight
    if (savingsRate > 20) {
        insights.push({
            title: 'Excellent Savings Rate',
            description: `You're saving ${savingsRate.toFixed(1)}% of your income on average. This is excellent for long-term financial health.`,
            recommendation: 'Consider investing surplus funds for better returns.'
        });
    } else if (savingsRate > 10) {
        insights.push({
            title: 'Good Savings Rate',
            description: `You're saving ${savingsRate.toFixed(1)}% of your income. This is a healthy savings rate.`,
            recommendation: 'Try to gradually increase to 20% if possible.'
        });
    } else if (savingsRate > 0) {
        insights.push({
            title: 'Low Savings Rate',
            description: `You're saving only ${savingsRate.toFixed(1)}% of your income.`,
            recommendation: 'Look for opportunities to reduce expenses or increase income.'
        });
    } else {
        insights.push({
            title: 'Spending More Than Earning',
            description: 'Your expenses exceed your income on average.',
            recommendation: 'Urgent review of budget needed. Consider expense reduction or additional income sources.'
        });
    }
    
    // Cash flow stability insight
    const netChanges = forecast.map(month => month.net_change);
    const volatility = calculateVolatility(netChanges);
    
    if (volatility < 200) {
        insights.push({
            title: 'Stable Cash Flow',
            description: 'Your monthly cash flow is relatively stable and predictable.',
            recommendation: 'Maintain consistent spending and saving habits.'
        });
    } else {
        insights.push({
            title: 'Variable Cash Flow',
            description: 'Your monthly cash flow varies significantly.',
            recommendation: 'Consider building a larger emergency fund to handle fluctuations.'
        });
    }
    
    // Find the best and worst months
    const sortedByBalance = [...forecast].sort((a, b) => b.ending_balance - a.ending_balance);
    const bestMonth = sortedByBalance[0];
    const worstMonth = sortedByBalance[sortedByBalance.length - 1];
    
    if (bestMonth && worstMonth && bestMonth !== worstMonth) {
        const difference = bestMonth.ending_balance - worstMonth.ending_balance;
        insights.push({
            title: 'Balance Variation',
            description: `Your account balance varies by ${formatCurrency(difference)} throughout the year (highest in ${bestMonth.month_name}, lowest in ${worstMonth.month_name}).`
        });
    }
    
    return insights;
}

function calculateVolatility(values) {
    if (values.length === 0) return 0;
    
    const mean = values.reduce((sum, val) => sum + val, 0) / values.length;
    const variance = values.reduce((sum, val) => sum + Math.pow(val - mean, 2), 0) / values.length;
    return Math.sqrt(variance);
}

function createForecastChart(forecast) {
    const canvas = document.getElementById('forecastChart');
    if (!canvas) return;
    
    const ctx = canvas.getContext('2d');
    const width = canvas.width;
    const height = canvas.height;
    const padding = 80;
    
    // Clear canvas
    ctx.clearRect(0, 0, width, height);
    
    // Prepare data
    const months = forecast.map(month => month.month);
    const balances = forecast.map(month => month.ending_balance);
    
    // Calculate bounds
    const minBalance = Math.min(...balances);
    const maxBalance = Math.max(...balances);
    const balanceRange = maxBalance - minBalance || 1000; // Minimum range of $1000
    
    const chartWidth = width - 2 * padding;
    const chartHeight = height - 2 * padding;
    
    // Draw grid and axes
    ctx.strokeStyle = '#e5e7eb';
    ctx.lineWidth = 1;
    
    // Horizontal grid lines and Y-axis labels
    const gridLines = 6;
    for (let i = 0; i <= gridLines; i++) {
        const y = padding + (i * chartHeight / gridLines);
        const value = maxBalance - (i * balanceRange / gridLines);
        
        // Grid line
        ctx.beginPath();
        ctx.moveTo(padding, y);
        ctx.lineTo(width - padding, y);
        ctx.stroke();
        
        // Y-axis label
        ctx.fillStyle = '#6b7280';
        ctx.font = '12px Arial';
        ctx.textAlign = 'right';
        ctx.fillText(formatCurrencyShort(value), padding - 10, y + 4);
        
        // Zero line (if applicable)
        if (value <= 100 && value >= -100) {
            ctx.strokeStyle = '#dc2626';
            ctx.lineWidth = 2;
            ctx.beginPath();
            ctx.moveTo(padding, y);
            ctx.lineTo(width - padding, y);
            ctx.stroke();
            ctx.strokeStyle = '#e5e7eb';
            ctx.lineWidth = 1;
        }
    }
    
    // Draw balance line
    if (balances.length > 1) {
        ctx.strokeStyle = '#3b82f6';
        ctx.lineWidth = 3;
        ctx.beginPath();
        
        balances.forEach((balance, index) => {
            const x = padding + (index * chartWidth / (balances.length - 1));
            const y = padding + chartHeight - ((balance - minBalance) / balanceRange * chartHeight);
            
            if (index === 0) {
                ctx.moveTo(x, y);
            } else {
                ctx.lineTo(x, y);
            }
        });
        
        ctx.stroke();
        
        // Draw data points
        balances.forEach((balance, index) => {
            const x = padding + (index * chartWidth / (balances.length - 1));
            const y = padding + chartHeight - ((balance - minBalance) / balanceRange * chartHeight);
            
            // Color-code points based on balance
            ctx.fillStyle = balance >= 0 ? '#16a34a' : '#dc2626';
            ctx.beginPath();
            ctx.arc(x, y, 5, 0, 2 * Math.PI);
            ctx.fill();
            
            // Show balance on hover (simple version - just current and critical points)
            if (index === 0 || balance < 0) {
                ctx.fillStyle = '#374151';
                ctx.font = '10px Arial';
                ctx.textAlign = 'center';
                ctx.fillText(formatCurrencyShort(balance), x, y - 10);
            }
        });
    }
    
    // Draw X-axis labels
    ctx.fillStyle = '#6b7280';
    ctx.font = '11px Arial';
    ctx.textAlign = 'center';
    
    months.forEach((month, index) => {
        const x = padding + (index * chartWidth / (months.length - 1));
        const y = height - padding + 20;
        
        // Show every other month label to avoid crowding
        if (index % 2 === 0 || months.length <= 6) {
            ctx.save();
            ctx.translate(x, y);
            if (months.length > 8) {
                ctx.rotate(-Math.PI / 6); // 30 degree rotation for crowded labels
            }
            ctx.fillText(month, 0, 0);
            ctx.restore();
        }
    });
    
    // Chart title
    ctx.fillStyle = '#1f2937';
    ctx.font = 'bold 14px Arial';
    ctx.textAlign = 'center';
    ctx.fillText('12-Month Balance Projection', width / 2, 25);
}

function formatCurrencyShort(amount) {
    if (Math.abs(amount) >= 1000000) {
        return (amount / 1000000).toFixed(1) + 'M';
    } else if (Math.abs(amount) >= 1000) {
        return (amount / 1000).toFixed(0) + 'K';
    }
    return Math.round(amount).toString();
}

function hideForecastResults() {
    const container = document.getElementById('forecastResults');
    if (container) {
        container.style.display = 'none';
        container.innerHTML = '';
    }
    currentForecast = null;
}

// =============================================================================
// CREDIT CARD PAYMENT INTEGRATION
// =============================================================================

function showPayCreditCardForm() {
    if (checkingAccounts.length === 0) {
        showMessage('Please add a checking account first', 'warning');
        return;
    }
    
    // Get credit cards from existing tracker data
    const creditCards = window.cardsData || [];
    if (creditCards.length === 0) {
        showMessage('No credit cards found. Add credit cards first.', 'warning');
        return;
    }
    
    const modal = createModal('Pay Credit Card from Checking', `
        <form onsubmit="return payCredocardFromChecking(event)" id="payCreditCardForm">
            <div class="form-row">
                <div class="form-group">
                    <label class="form-label">Pay From (Checking Account) *</label>
                    <select class="form-select" id="fromCheckingAccount" name="checking_account" required>
                        <option value="">Select checking account...</option>
                        ${checkingAccounts.map(account => `
                            <option value="${escapeHtml(account.name)}">
                                ${escapeHtml(account.name)} - ${formatCurrency(account.current_balance)}
                            </option>
                        `).join('')}
                    </select>
                </div>
                <div class="form-group">
                    <label class="form-label">Pay To (Credit Card) *</label>
                    <select class="form-select" id="toCreditCard" name="credit_card" required onchange="updatePaymentSuggestion()">
                        <option value="">Select credit card...</option>
                        ${creditCards.map(card => {
                            const totalOwed = (card.balance_due || 0) + (card.current_balance || 0);
                            return `
                                <option value="${escapeHtml(card.name)}" data-owed="${totalOwed}">
                                    ${escapeHtml(card.name)} - Owed: ${formatCurrency(totalOwed)}
                                </option>
                            `;
                        }).join('')}
                    </select>
                </div>
            </div>
            <div class="form-group">
                <label class="form-label">Payment Amount *</label>
                <input type="number" class="form-input" id="paymentAmount" name="amount" required 
                       placeholder="0.00" step="0.01" min="0.01">
                <div id="paymentSuggestions" style="margin-top: 0.5rem; font-size: 0.9rem;"></div>
            </div>
            <div class="form-group">
                <div id="availableFundsCheck" style="padding: 0.75rem; border-radius: 4px; margin-top: 0.5rem;"></div>
            </div>
            <div class="form-group" style="margin-top: 1.5rem;">
                <button type="submit" class="btn btn-success">Process Payment</button>
                <button type="button" class="btn btn-secondary" onclick="closeModal()">Cancel</button>
            </div>
        </form>
    `);
    
    // Add event listeners for real-time validation
    document.getElementById('fromCheckingAccount').addEventListener('change', validatePaymentFunds);
    document.getElementById('paymentAmount').addEventListener('input', validatePaymentFunds);
}

function updatePaymentSuggestion() {
    const creditCardSelect = document.getElementById('toCreditCard');
    const paymentAmountInput = document.getElementById('paymentAmount');
    const suggestionsDiv = document.getElementById('paymentSuggestions');
    
    if (!creditCardSelect.value) {
        suggestionsDiv.innerHTML = '';
        return;
    }
    
    const selectedOption = creditCardSelect.selectedOptions[0];
    const totalOwed = parseFloat(selectedOption.dataset.owed) || 0;
    
    if (totalOwed > 0) {
        suggestionsDiv.innerHTML = `
            <div style="background: #f0f9ff; padding: 0.5rem; border-radius: 4px; border-left: 3px solid #3b82f6;">
                <strong>💡 Suggestions:</strong><br>
                • Pay full balance: <button type="button" class="btn btn-small btn-link" onclick="setPaymentAmount(${totalOwed})">${totalOwed.toFixed(2)}</button><br>
                • Minimum payment: <button type="button" class="btn btn-small btn-link" onclick="setPaymentAmount(${Math.max(25, totalOwed * 0.02)})">${Math.max(25, totalOwed * 0.02).toFixed(2)}</button>
            </div>
        `;
    } else {
        suggestionsDiv.innerHTML = '<div style="color: #16a34a;">✅ This card is paid off!</div>';
    }
}

function setPaymentAmount(amount) {
    document.getElementById('paymentAmount').value = amount.toFixed(2);
    validatePaymentFunds();
}

function validatePaymentFunds() {
    const checkingSelect = document.getElementById('fromCheckingAccount');
    const amountInput = document.getElementById('paymentAmount');
    const checkDiv = document.getElementById('availableFundsCheck');
    
    if (!checkingSelect.value || !amountInput.value) {
        checkDiv.innerHTML = '';
        return;
    }
    
    const selectedAccount = checkingAccounts.find(acc => acc.name === checkingSelect.value);
    const paymentAmount = parseFloat(amountInput.value) || 0;
    
    if (!selectedAccount) {
        checkDiv.innerHTML = '';
        return;
    }
    
    const availableBalance = selectedAccount.current_balance;
    const remainingBalance = availableBalance - paymentAmount;
    
    if (remainingBalance >= 0) {
        const warningClass = remainingBalance < 500 ? 'warning' : 'success';
        const warningIcon = remainingBalance < 500 ? '⚠️' : '✅';
        
        checkDiv.className = `alert alert-${warningClass}`;
        checkDiv.innerHTML = `
            ${warningIcon} Available: ${formatCurrency(availableBalance)} 
            → Remaining after payment: ${formatCurrency(remainingBalance)}
            ${remainingBalance < 500 ? '<br><small>⚠️ Low balance warning</small>' : ''}
        `;
    } else {
        checkDiv.className = 'alert alert-error';
        checkDiv.innerHTML = `
            ❌ Insufficient funds. Available: ${formatCurrency(availableBalance)}, 
            Need: ${formatCurrency(paymentAmount)} 
            (Short: ${formatCurrency(Math.abs(remainingBalance))})
        `;
    }
}

async function payCredocardFromChecking(event) {
    event.preventDefault();
    
    const form = event.target;
    const formData = new FormData(form);
    
    const data = {
        checking_account: formData.get('checking_account'),
        credit_card: formData.get('credit_card'),
        amount: parseFloat(formData.get('amount'))
    };
    
    // Validate sufficient funds
    const selectedAccount = checkingAccounts.find(acc => acc.name === data.checking_account);
    if (!selectedAccount || selectedAccount.current_balance < data.amount) {
        showMessage('❌ Insufficient funds for this payment', 'error');
        return false;
    }
    
    const submitButton = form.querySelector('button[type="submit"]');
    submitButton.disabled = true;
    submitButton.textContent = 'Processing Payment...';
    
    try {
        const response = await fetch('/api/pay-credit-card', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });
        
        const result = await response.json();
        
        if (result.success) {
            showMessage('✅ ' + result.message, 'success');
            closeModal();
            
            // Refresh both checking accounts and credit cards
            await loadCheckingAccounts();
            if (typeof loadDashboard === 'function') {
                loadDashboard();
            }
        } else {
            throw new Error(result.error);
        }
    } catch (err) {
        showMessage('❌ Payment failed: ' + err.message, 'error');
    } finally {
        submitButton.disabled = false;
        submitButton.textContent = 'Process Payment';
    }
    
    return false;
}

// =============================================================================
// UTILITY FUNCTIONS
// =============================================================================

function updateForecastAccountDropdowns() {
    // Update any dropdowns that need checking account list
    const dropdowns = document.querySelectorAll('.forecast-account-dropdown');
    dropdowns.forEach(dropdown => {
        dropdown.innerHTML = '<option value="">Select account...</option>';
        checkingAccounts.forEach(account => {
            dropdown.innerHTML += `<option value="${escapeHtml(account.name)}">${escapeHtml(account.name)}</option>`;
        });
    });
}

function showCheckingAccountsUnavailable() {
    const container = document.getElementById('checkingAccountsList');
    if (container) {
        container.innerHTML = `
            <div class="alert alert-warning">
                <h4>⚠️ Checking Account Features Unavailable</h4>
                <p>Enhanced checking account features are not available in this version.</p>
                <p>The server may be running in compatibility mode with the original credit card tracker.</p>
            </div>
        `;
    }
}

function createModal(title, content) {
    // Remove existing modal if any
    const existing = document.getElementById('modal');
    if (existing) {
        existing.remove();
    }
    
    const modal = document.createElement('div');
    modal.id = 'modal';
    modal.className = 'modal';
    modal.innerHTML = `
        <div class="modal-content">
            <div class="modal-header">
                <h3>${escapeHtml(title)}</h3>
                <button class="modal-close" onclick="closeModal()">×</button>
            </div>
            <div class="modal-body">
                ${content}
            </div>
        </div>
    `;
    
    document.body.appendChild(modal);
    modal.style.display = 'flex';
    
    return modal;
}

function closeModal() {
    const modal = document.getElementById('modal');
    if (modal) {
        modal.remove();
    }
}

function exportForecast() {
    if (!currentForecast) {
        showMessage('No forecast data to export', 'warning');
        return;
    }
    
    try {
        const exportData = {
            account_name: currentForecast.account_name,
            generated_at: currentForecast.generated_at,
            forecast: currentForecast.forecast.map(month => ({
                month: month.month,
                month_name: month.month_name,
                starting_balance: month.starting_balance,
                income: month.income,
                expenses: month.expenses,
                net_change: month.net_change,
                ending_balance: month.ending_balance,
                issues: month.issues,
                transaction_count: month.transactions ? month.transactions.length : 0
            }))
        };
        
        const dataStr = JSON.stringify(exportData, null, 2);
        const dataBlob = new Blob([dataStr], { type: 'application/json' });
        
        const link = document.createElement('a');
        link.href = URL.createObjectURL(dataBlob);
        link.download = `forecast_${currentForecast.account_name.replace(/\s+/g, '_')}_${new Date().toISOString().split('T')[0]}.json`;
        link.click();
        
        showMessage('✅ Forecast exported successfully!', 'success');
    } catch (err) {
        showMessage('❌ Export failed: ' + err.message, 'error');
    }
}

// =============================================================================
// INITIALIZATION
// =============================================================================

// Initialize checking account features when DOM is ready
document.addEventListener('DOMContentLoaded', function() {
    console.log('🏦 Initializing enhanced checking account features...');
    
    // Load checking accounts and recurring transactions
    loadCheckingAccounts().then(() => {
        console.log('✅ Checking accounts loaded');
    });
    
    loadRecurringTransactions().then(() => {
        console.log('✅ Recurring transactions loaded');
    });
    
    // Add checking account tab content to existing tabs
    initializeCheckingAccountTab();
});

function initializeCheckingAccountTab() {
    // Check if checking account tab exists, if not create it
    const existingTab = document.getElementById('checking-tab');
    if (existingTab) {
        console.log('✅ Checking account tab already exists');
        return;
    }
    
    // Add checking account tab to existing navigation
    const tabNavigation = document.querySelector('.tab-list');
    if (tabNavigation) {
        const checkingTabItem = document.createElement('li');
        checkingTabItem.className = 'tab-item';
        checkingTabItem.innerHTML = `
            <button class="tab-button" onclick="showTab('checking')">
                🏦 Checking Accounts
            </button>
        `;
        
        // Insert before settings tab
        const settingsTab = tabNavigation.querySelector('button[onclick="showTab(\'settings\')"]')?.parentElement;
        if (settingsTab) {
            tabNavigation.insertBefore(checkingTabItem, settingsTab);
        } else {
            tabNavigation.appendChild(checkingTabItem);
        }
    }
    
    // Add checking account tab content
    const container = document.querySelector('.container');
    if (container) {
        const checkingTabDiv = document.createElement('div');
        checkingTabDiv.id = 'checking-tab';
        checkingTabDiv.className = 'tab-content';
        checkingTabDiv.innerHTML = `
            <div class="controls">
                <h2>🏦 Checking Account Management</h2>
                <div style="display: flex; gap: 0.5rem;">
                    <button class="btn btn-success" onclick="showAddCheckingAccountForm()">
                        ➕ Add Account
                    </button>
                    <button class="btn btn-secondary" onclick="showAddRecurringTransactionForm()">
                        🔄 Add Recurring Transaction
                    </button>
                    <button class="btn btn-info" onclick="showPayCreditCardForm()">
                        💳 Pay Credit Card
                    </button>
                </div>
            </div>

            <!-- Checking Accounts List -->
            <div class="card">
                <h3>💰 Your Checking Accounts</h3>
                <div id="checkingAccountsList">
                    <div class="loading">
                        <div class="loading-spinner"></div>
                        <p>Loading checking accounts...</p>
                    </div>
                </div>
            </div>

            <!-- Recurring Transactions -->
            <div class="card">
                <h3>🔄 Recurring Transactions</h3>
                <div id="recurringTransactionsList">
                    <div class="loading">
                        <div class="loading-spinner"></div>
                        <p>Loading recurring transactions...</p>
                    </div>
                </div>
            </div>

            <!-- Forecast Results -->
            <div id="forecastResults" style="display: none;"></div>
        `;
        
        // Insert before settings tab
        const settingsTab = document.getElementById('settings-tab');
        if (settingsTab) {
            container.insertBefore(checkingTabDiv, settingsTab);
        } else {
            container.appendChild(checkingTabDiv);
        }
        
        console.log('✅ Checking account tab content added');
    }
}

// Make functions globally available
if (typeof window !== 'undefined') {
    window.loadCheckingAccounts = loadCheckingAccounts;
    window.showAddCheckingAccountForm = showAddCheckingAccountForm;
    window.addCheckingAccount = addCheckingAccount;
    window.loadRecurringTransactions = loadRecurringTransactions;
    window.showAddRecurringTransactionForm = showAddRecurringTransactionForm;
    window.addRecurringTransaction = addRecurringTransaction;
    window.generateAccountForecast = generateAccountForecast;
    window.displayForecastResults = displayForecastResults;
    window.hideForecastResults = hideForecastResults;
    window.showPayCreditCardForm = showPayCreditCardForm;
    window.payCredocardFromChecking = payCredocardFromChecking;
    window.setPaymentAmount = setPaymentAmount;
    window.updatePaymentSuggestion = updatePaymentSuggestion;
    window.validatePaymentFunds = validatePaymentFunds;
    window.exportForecast = exportForecast;
    window.createModal = createModal;
    window.closeModal = closeModal;
}