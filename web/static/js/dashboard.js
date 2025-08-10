// Dashboard Functions

async function loadDashboard() {
    if (isLoading) return;
    
    isLoading = true;
    const refreshBtn = document.getElementById('refreshBtn');
    const refreshIcon = document.getElementById('refreshIcon');
    const refreshText = document.getElementById('refreshText');
    const loading = document.getElementById('loading');
    const error = document.getElementById('error');
    const dashboard = document.getElementById('dashboard');

    // Better button state management
    if (refreshBtn) {
        refreshBtn.disabled = true;
        if (refreshIcon) refreshIcon.textContent = '⏳';
        if (refreshText) refreshText.textContent = 'Loading...';
    }
    
    if (loading) loading.style.display = 'block';
    if (error) error.style.display = 'none';
    if (dashboard) dashboard.style.display = 'none';

    try {
        console.log('Loading dashboard data...');
        
        const response = await fetch('/api/summary');
        
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }

        const result = await response.json();
        console.log('Dashboard data received:', result);
        
        if (!result.success) {
            throw new Error(result.error || 'Unknown error occurred');
        }

        displayDashboard(result.data);
        await loadCards();
        
        if (loading) loading.style.display = 'none';
        if (dashboard) dashboard.style.display = 'block';
        
        lastUpdateTime = new Date();
        updateLastUpdatedTime();

    } catch (err) {
        console.error('Error loading dashboard:', err);
        showError(`Failed to load dashboard: ${err.message}`);
        if (loading) loading.style.display = 'none';
    } finally {
        isLoading = false;
        if (refreshBtn) {
            refreshBtn.disabled = false;
            if (refreshIcon) refreshIcon.textContent = '🔄';
            if (refreshText) refreshText.textContent = 'Refresh Data';
        }
    }
}

async function loadCards() {
    try {
        const response = await fetch('/api/cards');
        const result = await response.json();
        
        if (result.success) {
            displayCards(result.data);
        }
    } catch (err) {
        console.error('Error loading cards:', err);
    }
}

function displayDashboard(data) {
    // Update spending summary
    document.getElementById('totalSpending').textContent = formatCurrency(data.total_spending);
    document.getElementById('balanceDue').textContent = formatCurrency(data.balance_due);
    document.getElementById('leftToSpend').textContent = formatCurrency(data.left_to_spend);
    
    // Update spending status
    const spendingElement = document.getElementById('totalSpending');
    const leftToSpendElement = document.getElementById('leftToSpend');
    const spendingMessage = document.getElementById('spendingMessage');
    const budgetStatus = document.getElementById('budgetStatus');

    spendingElement.className = 'status-amount';
    leftToSpendElement.className = 'status-amount';
    
    if (data.spending_status) {
        spendingElement.classList.add(data.spending_status.replace('status-', 'status-'));
    }
    
    leftToSpendElement.classList.add(data.left_to_spend < 0 ? 'status-critical' : 'status-good');
    
    spendingMessage.textContent = data.spending_message ? 
        data.spending_message.replace(/[🚨⚠️✅]/g, '').trim() : 'No status';
    budgetStatus.textContent = data.left_to_spend < 0 ? 'Over budget' : 'Within budget';

    displayCategories(data.category_budgets || []);
    displayDueDates(data.due_dates || []);
}

function displayCards(cards) {
    const cardsList = document.getElementById('cardsList');
    
    if (!cards || cards.length === 0) {
        cardsList.innerHTML = '<div class="empty-state"><div class="empty-state-icon">💳</div>No credit cards configured<br><small>Add cards using the "Manage Cards" tab</small></div>';
        return;
    }

    cardsList.innerHTML = cards.map(card => `
        <div class="list-item">
            <div class="item-info">
                <div class="item-name">${escapeHtml(card.name)}</div>
                <div class="item-details">
                    Available: ${formatCurrency(card.available_credit)} of ${formatCurrency(card.credit_limit)}
                    ${card.description ? ' • ' + escapeHtml(card.description) : ''}
                </div>
            </div>
            <div class="item-amount ${card.current_balance > 0 ? 'status-warning' : 'status-good'}">
                ${formatCurrency(card.current_balance)}
            </div>
        </div>
    `).join('');
}

function displayCategories(categories) {
    const categoriesList = document.getElementById('categoriesList');
    
    if (!categories || categories.length === 0) {
        categoriesList.innerHTML = '<div class="empty-state"><div class="empty-state-icon">📊</div>No budgets set<br><small>Set budgets using the "Budgets & Limits" tab</small></div>';
        return;
    }

    categoriesList.innerHTML = categories.map(cat => {
        const progressClass = cat.status ? cat.status.replace('budget-', 'progress-') : 'progress-good';
        const progressWidth = Math.min(cat.percentage || 0, 100);
        
        return `
            <div class="list-item">
                <div class="item-info">
                    <div class="item-name">${escapeHtml(cat.category)}</div>
                    <div class="progress-bar">
                        <div class="progress-fill ${progressClass}" style="width: ${progressWidth}%"></div>
                    </div>
                    <div class="item-details">
                        ${formatCurrency(cat.spent)} of ${formatCurrency(cat.budget)}
                    </div>
                </div>
                <div class="item-amount ${cat.status ? cat.status.replace('budget-', 'status-') : 'status-good'}">
                    ${formatCurrency(cat.remaining)}
                </div>
            </div>
        `;
    }).join('');
}

function displayDueDates(dueDates) {
    const dueDatesList = document.getElementById('dueDatesList');
    
    if (!dueDates || dueDates.length === 0) {
        dueDatesList.innerHTML = '<div class="empty-state"><div class="empty-state-icon">📅</div>No upcoming due dates</div>';
        return;
    }

    dueDatesList.innerHTML = dueDates.map(due => {
        let itemClass = 'list-item';
        if (due.urgency === 'budget-critical') {
            itemClass += ' due-date-urgent';
        } else if (due.urgency === 'budget-warning') {
            itemClass += ' due-date-soon';
        }
        
        return `
            <div class="${itemClass}">
                <div class="item-info">
                    <div class="item-name">${escapeHtml(due.card_name)}</div>
                    <div class="item-details">${due.status}</div>
                </div>
                <div class="item-amount ${due.balance > 0 ? 'status-warning' : 'status-good'}">
                    ${formatCurrency(due.balance)}
                </div>
            </div>
        `;
    }).join('');
}